"""Спільний сценарій зміни замовлення: статус, накладна, сповіщення, CRM.

Звідки б не прийшла зміна — з панелі, з SalesDrive чи з формування ТТН —
вона проходить тут і однаково:

  1. перевірка переходу (transition_error) і вимоги накладної для
     «Відправлено»;
  2. запис у базу через change_order_status — бонуси, склад, реферальна
     винагорода рахуються там і лише там;
  3. сповіщення клієнта в Telegram тим самим текстом;
  4. позначка для синхронізації з SalesDrive.

До цього модуля те саме було написано в роутері панелі, а адмін-хендлер
бота мав власну копію. Третя копія для SalesDrive гарантувала б, що рано чи
пізно статус із CRM не нарахує бонус або не повідомить клієнта про ТТН.

Походження зміни (origin) важливе в одному місці: зміну, що прийшла із
SalesDrive, не відправляємо назад у SalesDrive. Інакше кожен вебхук
породжував би оновлення, а те — новий вебхук.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from shop.entities import STATUS_LABELS, Order, OrderStatus
from shop.services.shop_service import OrderStateConflict, change_order_status, stages_for, transition_error

log = logging.getLogger(__name__)

ORIGIN_PANEL = "panel"
ORIGIN_BOT = "bot"
ORIGIN_SALESDRIVE = "salesdrive"
ORIGIN_WAYBILL = "waybill"
ORIGIN_CLIENT = "client"

# Звідки взялась накладна. Видаляти через API Нової пошти можна лише ту,
# яку створили звідси: ref чужої ТТН нам невідомий, а стерти номер, який
# менеджер вписав руками, означало б втратити його без сліду.
SOURCE_MANUAL = "manual"
SOURCE_NOVAPOSHTA = "novaposhta"
SOURCE_SALESDRIVE = "salesdrive"


class WorkflowError(Exception):
    """Зміну неможливо застосувати. code — HTTP-код для панелі."""

    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


@dataclass
class Outcome:
    """Результат зміни. delivered=None — сповіщення не надсилалось."""

    order: Order
    changed: bool = False
    delivered: bool | None = None
    reason: str = ""


def _normalize_tracking(value: str | None) -> str:
    # Номер ТТН Нової пошти — лише цифри, але менеджери вставляють його з
    # пробілами з кабінету («2045 0000 1234 56»). Пробіли прибираємо, решту
    # не чіпаємо: у Укрпошти й інших перевізників є літери.
    return "".join((value or "").split())


async def apply_tracking(
    repo, order: Order, tracking: str | None, *, origin: str, bot=None,
    ref: str | None = None, source: str | None = None, cost: Decimal | None = None,
) -> Outcome:
    """Записує накладну. Порожній рядок — прибрати.

    Якщо замовлення вже «Відправлено», клієнт отримує оновлений номер:
    виправлену накладну інакше він шукав би за старим.
    """
    new = _normalize_tracking(tracking)
    old = order.tracking_number or ""
    same_ref = ref is None or ref == (order.waybill_ref or "")
    same_source = source is None or source == (order.waybill_source or "")
    same_cost = cost is None or cost == order.waybill_cost
    if new == old and same_ref and same_source and same_cost:
        return Outcome(order=order)

    patch: dict = {"tracking_number": new or None}
    if new:
        patch["waybill_source"] = source or (order.waybill_source if new == old else SOURCE_MANUAL)
        if ref is not None:
            patch["waybill_ref"] = ref or None
        elif new != old:
            # Номер змінили руками — ref попередньої ТТН до нового номера
            # не стосується, і видалення за ним стерло б чужу накладну.
            patch["waybill_ref"] = None
        if cost is not None:
            patch["waybill_cost"] = cost
    else:
        patch.update(waybill_ref=None, waybill_source=None, waybill_cost=None)
    if origin != ORIGIN_SALESDRIVE:
        patch.update(_crm_pending_patch(order))
    await repo.update_order(order.id, patch)
    fresh = await repo.get_order(order.id) or order

    log.info(
        "Накладна замовлення %s: %s → %s", order.id, old or "—", new or "—",
        extra={"event": "order.tracking.changed", "orderId": order.id,
               "origin": origin, "source": patch.get("waybill_source")},
    )

    outcome = Outcome(order=fresh, changed=True)
    if new and new != old and order.status == OrderStatus.SHIPPED and bot:
        from shop.services.order_chat import send_tracking_update
        outcome.delivered = bool(await send_tracking_update(bot, repo, fresh, new))

    if origin != ORIGIN_SALESDRIVE:
        await _kick_crm(fresh.id)
    return outcome


async def apply_status(
    repo, order: Order, status: OrderStatus, *, origin: str, bot=None, on_saved=None,
) -> Outcome:
    """Змінює статус за спільними правилами й сповіщає клієнта.

    on_saved(fresh) викликається одразу після запису, до сповіщень. Бот
    знімає ним спінер кнопки: доставка клієнту може чекати мережевого
    таймауту Telegram, і менеджер не має думати, що кнопка зависла.
    """
    if status == order.status:
        return Outcome(order=order)

    # «Відправлено» без накладної залишає клієнта без найпотрібнішого.
    # Правило одне для всіх джерел — і для CRM теж. Перевіряється перед
    # переходом: панель розрізняє 422 (заповніть поле) і 409 (так не можна).
    tracking = (order.tracking_number or "").strip()
    if status == OrderStatus.SHIPPED and not tracking:
        raise WorkflowError("Вкажіть номер накладної — він потрібен клієнту", 422)

    problem = transition_error(order.status, status, order.payment_method)
    if problem:
        raise WorkflowError(problem, 409)

    try:
        reward = await change_order_status(repo, order, status, origin=origin)
    except OrderStateConflict as exc:
        raise WorkflowError(str(exc), 409) from exc
    fresh = await repo.get_order(order.id) or order
    if on_saved:
        await on_saved(fresh)
    outcome = Outcome(order=fresh, changed=True)
    outcome.delivered, outcome.reason = await _notify_status(repo, bot, order, fresh, status)
    # Реферальна винагорода нараховується в change_order_status для будь-
    # якого джерела, а сповіщав про неї раніше лише бот. «Виконано» з
    # панелі чи з CRM нараховувало бонус мовчки.
    if reward and bot:
        await _notify_referrer(repo, bot, fresh, reward)
    # Позначку CRM і фонову відправку ставить change_order_status — там
    # вона спільна з ботом і скасуванням покупцем.
    return outcome


def _progress_index(order: Order, status: OrderStatus, stages: tuple[OrderStatus, ...]) -> int | None:
    """Позиція локального статусу у послідовному маршруті.

    У базі ще можуть лишатися два історичні стани, яких уже немає у
    ``stages_for``. Для синхронізації з CRM трактуємо їх як уже пройдений
    найближчий етап, а не як причину зупинити весь ланцюжок.
    """
    try:
        return stages.index(status)
    except ValueError:
        pass

    if status == OrderStatus.CONFIRMED:
        # Старе «Підтверджено» було між NEW та ACCEPTED.
        try:
            return stages.index(OrderStatus.NEW)
        except ValueError:
            return None
    if status == OrderStatus.PAID and getattr(order, "payment_method", None) == "cod":
        # Історичний COD міг застрягти в PAID, хоча сучасний маршрут
        # переходить ACCEPTED → SHIPPED напряму.
        try:
            return stages.index(OrderStatus.ACCEPTED)
        except ValueError:
            return None
    return None


async def apply_crm_status_progression(
    repo, order: Order, status: OrderStatus, *, bot=None,
) -> Outcome:
    """Проєктує пізніший статус SalesDrive на локальний workflow.

    У CRM менеджер може одразу поставити, наприклад, «Відправлений». Це
    означає, що попередні етапи вже пройдено, тож локальний облік не повинен
    застрягати на NEW лише тому, що webhook перескочив через ACCEPTED/PAID.

    Проміжні кроки застосовуємо послідовно через ту саму бізнес-логіку
    (лічильники, бонуси, склад), але клієнта повідомляємо тільки про фінальний
    статус. Рух назад автоматично не робимо: CRM лишається авторитетним
    display-статусом, а відкат локальних фінансових побічних ефектів без
    окремої бізнес-операції був би небезпечним.
    """
    # Два історичні локальні коди ще можуть бути в старій CRM-мапі, хоча
    # сучасний workflow їх не використовує. Не даємо такій мапі ламати
    # синхронізацію: «Підтверджено» означає, що етап NEW уже пройдено і
    # замовлення щонайменше прийняте; «Оплачено» для COD не є окремим
    # локальним етапом, тому теж не вставляємо неіснуючий крок.
    if status == OrderStatus.CONFIRMED:
        status = OrderStatus.ACCEPTED
    if status == OrderStatus.PAID and getattr(order, "payment_method", None) == "cod":
        status = OrderStatus.ACCEPTED

    if status == order.status:
        return Outcome(order=order)

    # Скасування — не «наступний етап», а окрема гілка. Для нього працюють
    # звичайні правила переходів і повернення залишків/бонусів.
    if status == OrderStatus.CANCELLED:
        return await apply_status(repo, order, status, origin=ORIGIN_SALESDRIVE, bot=bot)

    stages = stages_for(getattr(order, "payment_method", None))
    current_index = _progress_index(order, order.status, stages)
    try:
        target_index = stages.index(status)
    except ValueError:
        # Невідомий/історичний стан — лишаємо звичайну перевірку, щоб не
        # вигадувати маршрут, якого немає у бізнес-логіці.
        return await apply_status(repo, order, status, origin=ORIGIN_SALESDRIVE, bot=bot)

    if current_index is None:
        return await apply_status(repo, order, status, origin=ORIGIN_SALESDRIVE, bot=bot)
    if target_index <= current_index:
        # Не відкочуємо локальні побічні ефекти через рух CRM назад.
        return Outcome(order=order, reason="CRM-статус не просуває локальний workflow вперед")

    current = order
    final = Outcome(order=order)
    for step in stages[current_index + 1:target_index + 1]:
        # Сповіщення про кожен пропущений етап створювало б серію з кількох
        # Telegram-повідомлень за одну дію в CRM. Надсилаємо лише фінальний.
        result = await apply_status(
            repo, current, step, origin=ORIGIN_SALESDRIVE,
            bot=bot if step == status else None,
        )
        current = result.order
        final = result
    return final


async def _notify_status(repo, bot, before: Order, fresh: Order, status: OrderStatus):
    """Сповіщення клієнта про новий статус. Той самий текст звідусіль."""
    if not bot or not before.user:
        return None, ""
    from shop.services.order_chat import announce_accepted, send_tracking

    if status in (OrderStatus.ACCEPTED, OrderStatus.SHIPPED):
        if status == OrderStatus.ACCEPTED:
            ok = await announce_accepted(bot, repo, fresh, fresh.operator_name)
        else:
            ok = await send_tracking(bot, repo, fresh, fresh.tracking_number or "")
        if ok:
            return True, ""
        # Спеціалізовані функції вже записали причину й оновили
        # bot_reachable лише для постійної відмови — читаємо підсумок.
        latest = await repo.get_user(before.user_id)
        if latest and latest.bot_reachable is False:
            return False, ("клієнт не має доступного приватного чату з ботом — "
                           "попросіть його відкрити або розблокувати бота")
        return False, "тимчасова помилка Telegram — спробуйте ще раз за хвилину"

    if before.user.bot_reachable is False:
        # Після постійної відмови Bot API повторювати той самий запит на
        # кожен статус немає сенсу. Будь-яке нове повідомлення клієнта боту
        # повертає прапорець у True через RepositoryMiddleware.
        log.info(
            "Сповіщення по замовленню %s пропущено: чат клієнта недоступний", before.id,
            extra={"event": "order.notify.skipped_unreachable", "orderId": before.id,
                   "clientId": before.user.tg_id, "status": status.value},
        )
        return False, "чат із ботом позначений недоступним"

    from shop.services.shop_settings import get_shop_settings
    from shop.services.status_messages import compose
    from shop.telegram import notify_user_detailed

    shop = await get_shop_settings(repo)
    text = compose(fresh, status, shop) or f"Замовлення №{before.id}: статус — «{STATUS_LABELS[status]}»."
    # Через переданого бота — того самого, що надсилає «Прийнято» й ТТН.
    # notify_user_detailed лишається запасним шляхом, коли екземпляра бота
    # немає (API без вебхука): так усі статуси доходять однаково.
    if bot is not None and hasattr(bot, "send_message"):
        delivery = await _send_via_bot(bot, before.user.tg_id, text)
    else:
        delivery = await notify_user_detailed(before.user.tg_id, text)
    # Успішна доставка підтверджує зв'язок, постійна відмова («chat not
    # found», blocked) — навпаки. Тимчасові збої стан клієнта не змінюють.
    if delivery.delivered:
        await repo.set_bot_reachable(before.user.tg_id, True)
    elif delivery.permanent:
        await repo.set_bot_reachable(before.user.tg_id, False)
    if not delivery.delivered:
        log.warning(
            "Клієнт не отримав сповіщення про статус замовлення %s", before.id,
            extra={"event": "order.notify.failed", "orderId": before.id,
                   "clientId": before.user.tg_id, "status": status.value,
                   "permanent": delivery.permanent,
                   "deliveryError": delivery.error or "unknown"},
        )
    if delivery.delivered:
        return True, ""
    from shop.services.status_messages import undelivered_reason
    return False, undelivered_reason(delivery.error or "")


async def _send_via_bot(bot, tg_id: int, text: str):
    from shop.services.status_messages import is_permanent_delivery_error
    from shop.telegram import DeliveryResult
    try:
        await bot.send_message(tg_id, text)
        return DeliveryResult(delivered=True, error=None, permanent=False)
    except Exception as exc:
        return DeliveryResult(delivered=False, error=str(exc),
                              permanent=is_permanent_delivery_error(exc))


async def _notify_referrer(repo, bot, order: Order, reward) -> None:
    client = order.user or await repo.get_user(order.user_id)
    if not client or not client.referrer_id:
        return
    referrer = await repo.get_user(client.referrer_id)
    if not referrer:
        return
    from shop.services.shop_settings import get_shop_settings
    shop = await get_shop_settings(repo)
    try:
        await bot.send_message(
            referrer.tg_id,
            f"🎁 Вам нараховано {reward:.0f} {shop.currency} бонусів "
            f"за замовлення запрошеного друга.",
        )
    except Exception:
        log.warning(
            "Реферальний бонус нараховано, але запрошувач не сповіщений",
            extra={"event": "referral.notify.failed",
                   "referrerId": referrer.tg_id, "orderId": order.id},
            exc_info=True,
        )


def _crm_pending_patch(order: Order) -> dict:
    """Позначає зміну для CRM лише у вже синхронізованому/новому замовленні.

    Порожні crm_id і crm_state означають історичне замовлення ELFAR. Його
    не ставимо в чергу навіть після зміни статусу/ТТН: backfill заборонений.
    """
    return {"crm_state": "pending"} if (order.crm_id or order.crm_state) else {}


async def _kick_crm(order_id: int) -> None:
    """Спроба відправити зміну в CRM одразу, не чекаючи планувальника."""
    try:
        from shop.services import salesdrive
        salesdrive.push_soon(order_id)
    except Exception:
        log.exception("Не вдалося запланувати синхронізацію замовлення %s", order_id)
