from __future__ import annotations

import logging

from fastapi import Response, APIRouter, Depends, HTTPException, Query

from api.auth import require_staff
from api.auth import Principal, require_staff
from api.schemas import OrderMessageIn, OrderMessageOut, OrderMessageResult, OrderOut, OrderPatch
from shop.entities import STATUS_LABELS, OrderStatus
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services.order_chat import announce_accepted, send_to_client, send_tracking
from shop.services.shop_service import change_order_status
from shop.telegram import notify_user

log = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_staff)])


@router.get("", response_model=list[OrderOut])
async def list_orders(
    status: OrderStatus | None = None,
    search: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    repo: Repository = Depends(get_repo),
):
    return await repo.list_orders(status=status, search=search, limit=limit, offset=offset)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, repo: Repository = Depends(get_repo)):
    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")
    return order


@router.patch("/{order_id}", response_model=OrderOut)
async def patch_order(
    order_id: int,
    data: OrderPatch,
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")

    patch: dict = {}
    if data.admin_note is not None:
        patch["admin_note"] = data.admin_note
    if data.tracking_number is not None:
        patch["tracking_number"] = data.tracking_number.strip()
    if patch:
        await repo.update_order(order_id, patch)

    # Перехід у «Відправлено» без накладної залишив би клієнта без
    # найпотрібнішої інформації, тож просимо її одразу
    tracking = (data.tracking_number or order.tracking_number or "").strip()
    if data.status == OrderStatus.SHIPPED and not tracking:
        raise HTTPException(422, "Вкажіть номер накладної — він потрібен клієнту")

    if data.status and data.status != order.status:
        # «Прийнято» закріплює замовлення за оператором: клієнт має знати,
        # з ким саме він спілкується
        if data.status == OrderStatus.ACCEPTED:
            await repo.update_order(order_id, {
                "operator_id": who.operator_id,
                "operator_name": who.name or who.login,
            })

        await change_order_status(repo, order, data.status)
        fresh = await repo.get_order(order_id)

        bot = _bot()
        if data.status == OrderStatus.ACCEPTED and bot and fresh:
            await announce_accepted(bot, repo, fresh, fresh.operator_name)
        elif data.status == OrderStatus.SHIPPED and bot and fresh:
            await send_tracking(bot, repo, fresh, tracking)
        elif order.user:
            await notify_user(
                order.user.tg_id,
                f"Замовлення №{order.id}: статус змінено на «{STATUS_LABELS[data.status]}».",
            )

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


@router.post("/{order_id}/messages", response_model=OrderMessageResult, status_code=201)
async def send_message(
    order_id: int,
    data: OrderMessageIn,
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    """Повідомлення оператора клієнту.

    Якщо Telegram недоступний, запис усе одно зберігається: оператор бачить
    свою репліку в стрічці, а попередження каже, що клієнт її не отримав.
    """
    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")

    author = who.name or who.login
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
    target = next((m for m in messages if m.id == message_id and m.file_id), None)
    if not target:
        raise HTTPException(404, "Вкладення не знайдено")

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
