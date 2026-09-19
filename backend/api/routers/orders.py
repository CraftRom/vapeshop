from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.auth import Principal, require_staff, require_sysadmin
from api.schemas import OrderMessageIn, OrderMessageOut, OrderMessageResult, OrderOut, OrderPatch, SalesDriveStatusPatch
from shop.entities import OrderStatus
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services import order_workflow as flow
from shop.services.order_chat import announce_accepted, send_to_client
from shop.services.shop_service import change_order_status, transition_error

log = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_staff)])


@router.get("", response_model=list[OrderOut])
async def list_orders(
    status: OrderStatus | None = None,
    crm_status_id: str | None = Query(None, max_length=32),
    legacy_only: bool = False,
    search: str | None = None,
    # Дати у форматі YYYY-MM-DD, обидві межі включно
    date_from: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(100, le=500),
    offset: int = 0,
    repo: Repository = Depends(get_repo),
):
    return await repo.list_orders(
        status=status, crm_status_id=crm_status_id, legacy_only=legacy_only,
        search=search, date_from=date_from, date_to=date_to, limit=limit, offset=offset,
    )


@router.get("/salesdrive-statuses")
async def salesdrive_statuses(repo: Repository = Depends(get_repo)):
    """Поточний довідник статусів SalesDrive для робочих екранів панелі.

    Це не налаштування інтеграції, тому доступ має весь staff: менеджеру
    потрібні ті самі актуальні статуси, що й системному адміністратору.
    """
    from shop.services import salesdrive
    from shop.services.shop_settings import get_shop_settings

    shop = await get_shop_settings(repo)
    try:
        return {"statuses": await salesdrive.status_options(shop)}
    except salesdrive.SalesDriveError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, repo: Repository = Depends(get_repo)):
    """Картка замовлення. Нове замовлення відкриттям і приймається.

    Окремої кнопки «прийняти» більше немає. Вона просила менеджера
    підтвердити те, що він щойно зробив очима, і поки він її не натискав,
    клієнт сидів у невіданні — хоча замовлення вже дивилися.

    Ім'я менеджера тут не закріплюємо: відкрити картку може будь-хто,
    зокрема щоб просто глянути. Замовлення закріплюється за конкретною
    людиною тоді, коли вона напише клієнту.
    """
    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")

    # CRM-linked замовлення не змінюємо самим фактом відкриття картки.
    # Їхній статус є авторитетним у SalesDrive; автоматичний local NEW→ACCEPTED
    # раніше міг одразу поставити зворотну зміну в CRM і перетерти роботу менеджера.
    if order.status == OrderStatus.NEW and not order.crm_id:
        await change_order_status(repo, order, OrderStatus.ACCEPTED)
        order = await repo.get_order(order_id)
        bot = _bot()
        if bot and order:
            await announce_accepted(bot, repo, order, None)

    return order


@router.delete("/{order_id}", status_code=204)
async def delete_order(
    order_id: int,
    repo: Repository = Depends(get_repo),
    who: Principal = Depends(require_sysadmin),
):
    """Стирає замовлення. Лише системний адміністратор.

    Менеджерам і адміністраторам видалення не дають навмисно: замовлення
    це первинний документ. Помилкове скасовують статусом — так лишається
    слід. Стирати доводиться хіба що тестові записи після налаштування,
    і це разова дія власника системи.
    """
    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")

    log.warning(
        "Видалено замовлення %s", order_id,
        extra={"event": "order.deleted", "orderId": order_id,
               "actor": who.login, "total": str(order.total)},
    )
    await repo.delete_order(order_id)


@router.delete("", status_code=200)
async def delete_all_orders(
    confirm: str = Query("", description="Введіть DELETE ALL для підтвердження"),
    repo: Repository = Depends(get_repo),
    who: Principal = Depends(require_sysadmin),
):
    """Стирає всі замовлення разом із підсумками клієнтів.

    Підтвердження — не формальність: відновити це можна лише з резервної
    копії, а вона може бути вчорашньою.
    """
    if confirm != "DELETE ALL":
        raise HTTPException(
            400,
            "Для підтвердження передайте confirm=DELETE ALL. "
            "Дія незворотна: замовлення відновлюються лише з резервної копії",
        )

    removed = await repo.delete_all_orders()
    log.warning(
        "Видалено всі замовлення: %s", removed,
        extra={"event": "orders.purged", "removed": removed, "actor": who.login},
    )
    return {"removed": removed}


@router.patch("/{order_id}", response_model=OrderOut)
async def patch_order(
    order_id: int,
    data: OrderPatch,
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    """Нотатка, накладна, статус — через спільний сценарій замовлення.

    Правила переходів, вимога накладної для «Відправлено», сповіщення
    клієнта й черга SalesDrive живуть в order_workflow. Раніше вони були
    написані тут, а SalesDrive вимагав би третьої копії.
    """
    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")

    if data.admin_note is not None:
        await repo.update_order(order_id, {"admin_note": data.admin_note})

    bot = _bot()
    # Спершу перевіряємо статус, потім пишемо накладну: відмова в переході
    # не має лишати половину змін збереженою.
    if data.status and data.status != order.status:
        tracking_after = flow._normalize_tracking(
            data.tracking_number if data.tracking_number is not None else order.tracking_number)
        # Порядок перевірок той самий, що був до спільного сценарію: спершу
        # накладна (422), потім перехід (409). Панель розрізняє ці коди.
        if data.status == OrderStatus.SHIPPED and not tracking_after:
            raise HTTPException(422, "Вкажіть номер накладної — він потрібен клієнту")
        problem = transition_error(order.status, data.status, order.payment_method)
        if problem:
            raise HTTPException(409, problem)

    if data.tracking_number is not None:
        # Сповіщення про виправлену накладну — лише коли статус не
        # змінюється цим самим запитом: інакше клієнт отримав би два
        # повідомлення з тим самим номером.
        await flow.apply_tracking(repo, order, data.tracking_number, origin=flow.ORIGIN_PANEL,
                                  bot=bot if data.status is None else None)
        order = await repo.get_order(order_id) or order

    if data.status and data.status != order.status:
        try:
            await flow.apply_status(repo, order, data.status, origin=flow.ORIGIN_PANEL, bot=bot)
        except flow.WorkflowError as exc:
            raise HTTPException(exc.code, str(exc)) from exc

    return await repo.get_order(order_id)


@router.post("/{order_id}/waybill", response_model=OrderOut)
async def create_waybill(order_id: int, repo: Repository = Depends(get_repo)):
    """Створює ТТН Нової пошти й записує її в замовлення."""
    from shop.services import waybill
    from shop.services.shop_settings import get_shop_settings

    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")
    try:
        await waybill.create(repo, order, await get_shop_settings(repo), bot=_bot())
    except waybill.WaybillError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await repo.get_order(order_id)


@router.get("/{order_id}/waybill/readiness")
async def waybill_readiness(order_id: int, repo: Repository = Depends(get_repo)):
    """Чи можна створити ТТН і що заважає. Кнопка в панелі показує причину
    заздалегідь, а не після натискання."""
    from shop.services import waybill
    from shop.services.shop_settings import get_shop_settings

    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")
    problem = waybill.readiness(order, await get_shop_settings(repo))
    return {"ready": problem is None, "problem": problem}


@router.delete("/{order_id}/waybill", response_model=OrderOut)
async def delete_waybill(order_id: int, repo: Repository = Depends(get_repo)):
    """Видаляє ТТН, створену з панелі, у Новій пошті й у замовленні."""
    from shop.services import waybill
    from shop.services.shop_settings import get_shop_settings

    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")
    try:
        await waybill.delete(repo, order, await get_shop_settings(repo), bot=_bot())
    except waybill.WaybillError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await repo.get_order(order_id)


@router.get("/{order_id}/waybill/label")
async def waybill_label(order_id: int, repo: Repository = Depends(get_repo)):
    """Маркування ТТН у PDF. Сервер тягне файл сам — ключ у браузер не йде."""
    from shop.services import waybill
    from shop.services.shop_settings import get_shop_settings

    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")
    try:
        pdf = await waybill.label_pdf(order, await get_shop_settings(repo))
    except waybill.WaybillError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="ttn-{order.tracking_number}.pdf"',
        "Cache-Control": "no-store",
    })




@router.post("/{order_id}/salesdrive-refresh", response_model=OrderOut)
async def refresh_salesdrive_order(
    order_id: int, _who: Principal = Depends(require_staff), repo: Repository = Depends(get_repo),
):
    """Читає фактичний стан вже пов'язаної заявки CRM. Старі замовлення не шукає і не імпортує."""
    from shop.services import salesdrive
    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")
    if not order.crm_id:
        raise HTTPException(409, "Legacy-замовлення не пов’язане із SalesDrive")
    try:
        return await salesdrive.pull_order(repo, order_id)
    except salesdrive.SalesDriveError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.patch("/{order_id}/salesdrive-status", response_model=OrderOut)
async def patch_salesdrive_status(
    order_id: int, data: SalesDriveStatusPatch,
    _who: Principal = Depends(require_staff), repo: Repository = Depends(get_repo),
):
    """Змінює статус заявки прямо в SalesDrive.

    Це єдиний UI-шлях для нових CRM-пов'язаних замовлень. Старі замовлення
    без crm_id принципово не створюємо в CRM (no-backfill).
    """
    from shop.services import salesdrive
    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")
    if not order.crm_id:
        raise HTTPException(409, "Старе замовлення не пов’язане із SalesDrive")
    try:
        return await salesdrive.set_crm_status(repo, order, data.status_id, data.status_name)
    except salesdrive.SalesDriveError as exc:
        raise HTTPException(502, str(exc)) from exc

@router.post("/{order_id}/crm-sync", response_model=OrderOut)
async def retry_crm_sync(order_id: int, repo: Repository = Depends(get_repo)):
    """Повторна відправка в SalesDrive — після виправлення причини.

    Лічильник спроб скидаємо: планувальник зупиняється після MAX_ATTEMPTS,
    і людина, яка виправила ключ, має отримати свіжу серію.
    """
    from shop.services import salesdrive
    from shop.services.shop_settings import get_shop_settings

    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")
    shop = await get_shop_settings(repo)
    if not shop.salesdrive_ready:
        raise HTTPException(409, "Інтеграцію з SalesDrive вимкнено або не налаштовано")
    if not order.crm_id and not order.crm_state:
        raise HTTPException(409, "Історичне замовлення не експортується в SalesDrive")
    # Заявка вже є — оновлюємо. Створення могло дійти без відповіді —
    # спершу пробуємо оновити, щоб не створити дубль. Інакше — створюємо.
    if order.crm_id:
        state = salesdrive.STATE_SYNCED
    elif order.crm_state in (salesdrive.STATE_UNCERTAIN, salesdrive.STATE_CREATING):
        state = salesdrive.STATE_UNCERTAIN
    else:
        state = salesdrive.STATE_PENDING
    await repo.update_order(order_id, {"crm_state": state, "crm_attempts": 0})
    await salesdrive.push_order(repo, order_id, shop)
    return await repo.get_order(order_id)


def _bot():
    """Екземпляр бота для доставки повідомлень. None — якщо недоступний."""
    try:
        from api.routers.telegram import _instances

        bot, _ = _instances()
        return bot
    except Exception:
        log.warning("Бот недоступний — повідомлення клієнту не піде", exc_info=True)
        return None


@router.get("/{order_id}/messages", response_model=list[OrderMessageOut])
async def order_messages(
    order_id: int, mark_read: bool = False, repo: Repository = Depends(get_repo)
):
    """Стрічка листування.

    mark_read вимикається за замовчуванням навмисно: сторінка замовлення
    оновлює стрічку у фоні кожні 15 секунд, і якби кожен такий запит гасив
    лічильник, непрочитані зникали б у вкладці, на яку ніхто не дивиться.
    """
    if not await repo.get_order(order_id):
        raise HTTPException(404, "Замовлення не знайдено")
    if mark_read:
        await repo.mark_messages_read(order_id)
    return await repo.list_order_messages(order_id)


@router.post("/{order_id}/messages/read")
async def mark_order_messages_read(order_id: int, repo: Repository = Depends(get_repo)):
    """Позначити вхідні повідомлення замовлення прочитаними без повторної
    передачі всієї історії чату.

    Картка замовлення спочатку читає історію з ``mark_read=false``, щоб
    зафіксувати точні ID нових реплік для UI, і лише потім викликає цей
    endpoint. Старий query-параметр лишається для сумісності клієнтів.
    """
    if not await repo.get_order(order_id):
        raise HTTPException(404, "Замовлення не знайдено")
    marked = await repo.mark_messages_read(order_id)
    return {"marked": marked}


@router.post("/{order_id}/messages", response_model=OrderMessageResult, status_code=201)
async def send_message(
    order_id: int,
    data: OrderMessageIn,
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    """Повідомлення менеджера клієнту.

    Якщо Telegram недоступний, запис усе одно зберігається: менеджер бачить
    свою репліку в стрічці, а попередження каже, що клієнт її не отримав.
    """
    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")

    author = who.name or who.login

    # Перше повідомлення закріплює замовлення за менеджером. Раніше це
    # робив перехід у «Прийнято», але той став автоматичним, і на момент
    # прийняття конкретної людини ще немає. Прив'язка саме тут, а не при
    # відкритті картки: подивитись може будь-хто, а веде замовлення той,
    # хто заговорив із клієнтом.
    if not order.operator_id:
        await repo.update_order(order_id, {
            "operator_id": who.operator_id,
            "operator_name": author,
        })
        order = await repo.get_order(order_id)

    bot = _bot()
    delivered = False
    if bot:
        delivered = await send_to_client(bot, repo, order, data.text, author)

    if delivered:
        messages = await repo.list_order_messages(order_id)
        return OrderMessageResult(message=messages[-1], delivered=True)

    saved = await repo.add_order_message({
        "order_id": order_id, "user_id": order.user_id, "direction": "out",
        "author": author, "text": data.text, "tg_message_id": None, "is_read": True,
    })
    return OrderMessageResult(
        message=saved, delivered=False,
        warning="Повідомлення збережено, але клієнту не доставлено. "
                "Можливо, він заблокував бота.",
    )


@router.get("/{order_id}/files/{message_id}")
async def order_file(order_id: int, message_id: int, repo: Repository = Depends(get_repo)):
    """Віддає вкладення з Telegram.

    Файл не зберігається у нас: панель тягне його через бота на льоту.
    Так уникаємо і сховища, і того, щоб токен бота світився у браузері —
    посилання на Telegram містить його у відкритому вигляді.
    """
    messages = await repo.list_order_messages(order_id)
    target = next((m for m in messages if m.id == message_id), None)
    if not target:
        raise HTTPException(404, "Вкладення не знайдено")
    if not target.file_id:
        # Файл був, але код доступу до нього прибрано за строком
        # зберігання. Окремий код відповіді, щоб панель сказала саме це,
        # а не «Telegram видалив» — Telegram тут ні до чого.
        raise HTTPException(410, "Вкладення прибране за строком зберігання")

    bot = _bot()
    if not bot:
        raise HTTPException(503, "Бот недоступний — файл не отримати")

    try:
        info = await bot.get_file(target.file_id)
        content = await bot.download_file(info.file_path)
    except Exception:
        log.warning("Не вдалося отримати файл %s", target.file_id, exc_info=True)
        raise HTTPException(502, "Telegram не віддав файл. Можливо, він застарів")

    media = {"photo": "image/jpeg", "video": "video/mp4", "voice": "audio/ogg"}
    return Response(
        content=content.read(),
        media_type=media.get(target.file_kind, "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{target.file_name or "file"}"'},
    )


@router.get("/unread/counts")
async def unread(repo: Repository = Depends(get_repo)):
    """Скільки непрочитаних у кожному замовленні — для індикаторів у списку."""
    return await repo.unread_counts()
