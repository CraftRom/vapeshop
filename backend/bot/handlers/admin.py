from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from shop.services.shop_settings import current, get_shop_settings
from shop.entities import STATUS_LABELS, OrderStatus
from shop.repo.base import Repository
from shop.services.order_chat import announce_accepted, send_tracking
from shop.services.shop_service import change_order_status, transition_error
from shop.services.status_messages import (
    compose,
    is_permanent_delivery_error,
    undelivered_reason,
)

import logging

log = logging.getLogger("bot.admin")

router = Router()


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        # Список редагується з панелі; .env лишається дефолтом
        return event.from_user.id in current().admin_id_list


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(Command("stats"))
async def stats(message: Message, repo: Repository) -> None:
    # Лише в адмінському чаті. Раніше вистачало бути в ADMIN_IDS, і власник,
    # покликавши /stats у сторонній групі, вивалив би туди виручку магазину
    # перед усіма присутніми.
    if message.chat.id != current().admin_chat_id:
        log.info("Спроба /stats поза адмінським чатом: %s", message.chat.id)
        return

    summary = await repo.stats_summary(30)
    shop = await get_shop_settings(repo)
    await message.answer(
        f"<b>Коротка статистика</b>\n\n"
        f"Клієнтів: {summary.customers_total}\n"
        f"Нових замовлень: {summary.orders_new}\n"
        f"Виручка: {summary.revenue_total:.0f} {shop.currency}\n"
        f"Товарів із залишком &lt; 5: {summary.low_stock}\n\n"
        f"Повна аналітика — у дашборді."
    )


async def _warn_delivery(callback: CallbackQuery, label: str, reason: str) -> None:
    """Другий сигнал менеджеру після успішної зміни статусу.

    Перший callback.answer знімає спінер одразу після запису в БД. Якщо
    Telegram потім не доставив повідомлення клієнту, показуємо окремий alert.
    Це повторює попередню UX-модель, але причина тепер розрізняє постійну
    недоступність і тимчасовий збій мережі.
    """
    try:
        await callback.answer(
            f"Статус: {label}. Але сповіщення не дійшло: {reason}",
            show_alert=True,
        )
    except Exception:
        # Статус уже збережено. Прострочений callback не повинен перетворити
        # успішну бізнес-дію на помилку обробника.
        log.info("Не вдалося показати менеджеру alert про доставку", exc_info=True)


@router.callback_query(F.data.startswith("ao:"))
async def admin_change_status(callback: CallbackQuery, repo: Repository) -> None:
    # Дані кнопки приходять ззовні: зіпсований рядок не має валити обробник
    try:
        _, raw_id, status_value = callback.data.split(":")
        order_id = int(raw_id)
        status = OrderStatus(status_value)
    except (TypeError, ValueError):
        await callback.answer("Кнопка застаріла, оновіть повідомлення", show_alert=True)
        return

    order = await repo.get_order(order_id)
    if not order:
        await callback.answer("Замовлення не знайдено", show_alert=True)
        return

    label = STATUS_LABELS[status]

    # Стара клавіатура лишається у вже надісланих Telegram-повідомленнях.
    # Тому перевірки тут обов'язкові навіть після того, як нова клавіатура
    # почала показувати лише допустимий наступний крок.
    if order.status == status:
        await callback.answer(f"Статус уже «{label}»")
        try:
            await callback.message.edit_reply_markup(
                reply_markup=kb.admin_order(order.id, order.payment_method, order.status)
            )
        except Exception:
            pass
        return

    problem = transition_error(order.status, status, order.payment_method)
    if problem:
        await callback.answer(problem, show_alert=True)
        return

    # Через Telegram-кнопку немає поля для ТТН. Раніше натискання
    # «Відправлено» просто ставило статус без накладної, хоча панель той самий
    # перехід правильно забороняє. Дозволяємо кнопку лише якщо ТТН уже внесено
    # в картці замовлення; інакше просимо зробити це там.
    tracking = (order.tracking_number or "").strip()
    if status == OrderStatus.SHIPPED and not tracking:
        await callback.answer(
            "Спочатку вкажіть номер накладної в панелі замовлення. "
            "Без ТТН статус «Відправлено» не встановлюється.",
            show_alert=True,
        )
        return

    reward = await change_order_status(repo, order, status)
    fresh = await repo.get_order(order.id) or order

    # Знімаємо спінер одразу після того, як БД уже змінилась. Доставка
    # повідомлення клієнту — окрема операція і не повинна створювати враження,
    # що кнопка «зависла» на мережевому timeout Telegram.
    await callback.answer(f"Статус: {label}")
    try:
        await callback.message.edit_reply_markup(
            reply_markup=kb.admin_order(order.id, order.payment_method, fresh.status)
        )
    except Exception:
        # Старе повідомлення могли видалити/змінити вручну. Статус у БД уже
        # коректний, тому це лише косметична невдача.
        log.info("Не вдалося оновити кнопки замовлення %s", order.id, exc_info=True)

    client = await repo.get_user(order.user_id)
    if not client:
        return

    # Після першого постійного «chat not found / blocked» повторювати той
    # самий запит при кожній зміні статусу безглуздо. У журналі саме це
    # сталося тричі за 23 секунди з замовленням №21. /start автоматично
    # повертає bot_reachable=True, тому після дії клієнта доставка відновиться.
    if client.bot_reachable is False:
        log.info(
            "Сповіщення по замовленню %s пропущено: клієнт уже позначений недоступним",
            order.id,
            extra={"event": "order.notify.skipped_unreachable", "orderId": order.id,
                   "clientId": client.tg_id, "status": status.value},
        )
        await _warn_delivery(
            callback,
            label,
            "чат із ботом уже позначений недоступним — попросіть клієнта "
            "відкрити/розблокувати бота або напишіть у стрічку замовлення",
        )
    else:
        delivered = True

        if status == OrderStatus.ACCEPTED:
            delivered = await announce_accepted(
                callback.bot, repo, fresh, fresh.operator_name
            )
        elif status == OrderStatus.SHIPPED:
            delivered = await send_tracking(callback.bot, repo, fresh, tracking)
        else:
            shop_now = await get_shop_settings(repo)
            text = compose(fresh, status, shop_now)
            try:
                await callback.bot.send_message(
                    client.tg_id,
                    text or f"Замовлення №{order.id}: статус — «{label}».",
                )
                await repo.set_bot_reachable(client.tg_id, True)
            except Exception as exc:
                delivered = False
                permanent = is_permanent_delivery_error(exc)
                if permanent:
                    await repo.set_bot_reachable(client.tg_id, False)

                log.warning(
                    "Клієнт не отримав сповіщення про статус замовлення %s",
                    order.id,
                    extra={"event": "order.notify.failed", "orderId": order.id,
                           "clientId": client.tg_id, "status": status.value,
                           "permanent": permanent},
                    exc_info=True,
                )
                await _warn_delivery(callback, label, undelivered_reason(exc))

        if not delivered and status in (OrderStatus.ACCEPTED, OrderStatus.SHIPPED):
            # Спеціалізовані функції вже записали точну причину в traceback і
            # оновили bot_reachable лише для постійної відмови. Після них
            # перечитуємо користувача, щоб менеджеру дати правильну дію.
            latest = await repo.get_user(order.user_id)
            if latest and latest.bot_reachable is False:
                reason = (
                    "клієнт не має доступного приватного чату з ботом — "
                    "попросіть його відкрити/розблокувати бота"
                )
            else:
                reason = "тимчасова помилка Telegram — спробуйте ще раз за хвилину"
            await _warn_delivery(callback, label, reason)

    if reward and client.referrer_id:
        shop = await get_shop_settings(repo)
        referrer = await repo.get_user(client.referrer_id)
        if referrer:
            try:
                await callback.bot.send_message(
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
