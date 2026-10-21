"""Checkout navigation through real Telegram updates, FSM and SQLite repository."""
import os
from qa_paths import qa_db_url
from tests_bot import RecordingSession, message_update, callback_update, contact_update
os.environ.update(BOT_TOKEN="123456:TEST", JWT_SECRET="t" * 32,
                  DATABASE_URL=qa_db_url("bot_checkout_navigation.db"), REDIS_URL="")

import asyncio
from dataclasses import replace
from decimal import Decimal
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from bot.factory import build_dispatcher
from bot.states import Checkout
from shop.db import engine
from shop.models import Base
from shop.repo.factory import open_repo
from shop.services.shop_settings import ShopSettings, prime_cache
from qa_common import Report

r = Report("BOT CHECKOUT NAVIGATION")


async def main():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = replace(ShopSettings.from_env(), bonus_enabled=True,
                       bonus_max_percent=Decimal("30"), volume_discount_enabled=False,
                       salesdrive_enabled=False)
    prime_cache(settings)
    async with open_repo() as repo:
        category = await repo.create_category({"name": "QA"})
        product = await repo.create_product({"category_id": category.id, "name": "QA",
                                             "price": Decimal("100"), "stock": 30})
        user = await repo.create_user(500001, "buyer", "QA", None)
        await repo.confirm_age(user)
        await repo.add_bonus(user.id, Decimal("100"), "manual")
        await repo.set_cart_qty(user.id, product.id, 1)
        promo = await repo.create_promo({"code": "TEN", "value": Decimal("10"), "per_user_limit": 5})
    session = RecordingSession()
    bot = Bot(token="123456:TEST", session=session,
              default=DefaultBotProperties(parse_mode="HTML"))
    dp = build_dispatcher()
    state = dp.fsm.get_context(bot=bot, chat_id=500001, user_id=500001)

    def button(prefix):
        return next(b["callback_data"] for _, payload in reversed(session.calls)
                    for row in payload.get("reply_markup", {}).get("inline_keyboard", [])
                    for b in row if b.get("callback_data", "").startswith(prefix))

    async def feed(value, callback=False):
        session.clear()
        await dp.feed_update(bot, callback_update(bot, value) if callback else message_update(bot, value))

    async def press(action):
        await feed(button("checkout:" + action + ":"), True)

    async def edit(field):
        await feed(button("order:edit:" + field + ":"), True)

    async def is_summary(label):
        data = await state.get_data()
        r.check(await state.get_state() == Checkout.confirm.state and bool(data.get("quote_token"))
                and bool(data.get("confirmation_id")), label)

    try:
        await feed("checkout", True)
        key = (await state.get_data())["checkout_key"]
        await feed("Покупець Тестовий")
        old_phone_back = button("checkout:back:")
        await press("back")
        r.check((await state.get_data())["name"] == "Покупець Тестовий", "Back preserves entered recipient")
        await press("keep")
        snapshot = await state.get_data()
        await feed(old_phone_back, True)
        r.check(await state.get_state() == Checkout.phone.state and await state.get_data() == snapshot
                and "застаріла" in session.alerts()[-1], "old button rejected after returning to same step")
        await dp.feed_update(bot, contact_update(bot, "0671234567"))
        r.check((await state.get_data())["phone"] == "+380671234567", "Telegram contact still accepted")
        await feed("Київ")
        await feed("Відділення 1")
        old_skip = button("checkout:skip:")
        await press("skip")
        old_bonus = button("checkout:bonusyes:")
        await press("bonusno")
        await press("back")
        r.check(await state.get_state() == Checkout.bonus.state, "payment Back returns to available bonus step")
        await press("keep")
        await press("paycard")
        await feed("Початковий коментар")
        await is_summary("initial completed form has server quote")
        initial_confirm = button("order:confirm:")
        initial_cancel = button("order:cancel:")

        for field, value, expected in (
            ("name", "Новий <Отримувач>", "Новий <Отримувач>"),
            ("phone", "0991234567", "+380991234567"),
            ("city", "Львів & область", "Львів & область"),
            ("address", "Відділення 22", "Відділення 22"),
            ("comment", "Новий <коментар>", "Новий <коментар>"),
        ):
            await edit(field)
            data = await state.get_data()
            r.check(not data.get("quote_token") and not data.get("confirmation_id"), field + ": editing invalidates confirmation")
            if field == "name":
                before = await state.get_data()
                for stale in (initial_confirm, initial_cancel, old_skip, old_bonus, "skip", "pay:cod", "bonus:yes"):
                    await feed(stale, True)
                    r.check(await state.get_data() == before and "застаріла" in session.alerts()[-1], "stale callback cannot mutate edited form: " + stale.split(":")[0])
                await feed("x")
                r.check(await state.get_state() == Checkout.name.state and await state.get_data() == before, "invalid edited value preserves previous data")
            await feed(value)
            await is_summary(field + ": one-field edit returns directly to summary")
            r.check((await state.get_data())[field] == expected, field + ": new value saved")
        r.check("&lt;Отримувач&gt;" in session.all_text() and "&lt;коментар&gt;" in session.all_text()
                and "Львів &amp; область" in session.all_text(), "edited summary escapes HTML")

        await edit("promo")
        await feed("TEN")
        await is_summary("editing promo requotes directly")
        r.check("90,00" in session.all_text(), "new promo changes payable total")
        await edit("bonus")
        await press("bonusyes")
        r.check("63,00" in session.all_text(), "bonus limit recomputed after promo")
        await edit("promo")
        await press("skip")
        r.check("70,00" in session.all_text() and (await state.get_data())["promo"] is None, "removing promo recomputes bonus and total")
        await edit("payment")
        await press("paycod")
        r.check((await state.get_data())["payment"] == "cod", "payment editable")
        await edit("comment")
        await press("skip")
        r.check((await state.get_data())["comment"] is None and "Новий &lt;коментар&gt;" not in session.all_text(), "skip clears previous comment")
        await edit("city")
        await press("back")
        r.check((await state.get_data())["city"] == "Львів & область", "Back from edit returns without changing value")
        await is_summary("Back regenerates summary")
        r.check((await state.get_data())["checkout_key"] == key, "navigation preserves idempotency key")

        old_confirm = button("order:confirm:")
        await edit("name")
        await feed("Фінальний Отримувач")
        current_confirm = button("order:confirm:")
        await feed(old_confirm, True)
        async with open_repo() as repo:
            r.check(await repo.count_orders() == 0, "old summary cannot create order after edit")
            await repo.set_cart_qty(user.id, product.id, 2)
        await feed(current_confirm, True)
        await is_summary("changed cart requires fresh explicit confirmation")
        async with open_repo() as repo:
            r.check(await repo.count_orders() == 0, "changed cart not bought silently")
        fresh = button("order:confirm:")
        await feed(fresh, True)
        async with open_repo() as repo:
            orders = await repo.list_orders()
            order = orders[0]
            r.check(len(orders) == 1 and order.contact_name == "Фінальний Отримувач"
                    and order.delivery_city == "Львів & область" and order.payment_method == "cod"
                    and order.comment is None and order.total == Decimal("140"), "committed order contains edited data and fresh amount")
            await repo.set_cart_qty(user.id, product.id, 1)
        await feed(fresh, True)
        async with open_repo() as repo:
            r.check(await repo.count_orders() == 1, "double confirmation creates one order")

        await feed("checkout", True)
        cancel = button("checkout:cancel:")
        await feed(cancel, True)
        async with open_repo() as repo:
            r.check(await state.get_state() is None and bool(await repo.get_cart(user.id)), "cancel first step retains cart")
        await feed("checkout", True)
        before = await state.get_data()
        await feed(cancel, True)
        r.check(await state.get_data() == before, "old cancel cannot cancel next checkout")
        await feed("/cancel")
        r.check(await state.get_state() is None and await state.get_data() == {}, "/cancel clears uncommitted form")

        # No bonus step: Back from payment must not loop forward to payment.
        prime_cache(replace(settings, bonus_enabled=False))
        await feed("checkout", True)
        for value in ("Тест Отримувач", "0671234567", "Київ", "1"):
            await feed(value)
        await press("skip")
        r.check(await state.get_state() == Checkout.payment.state, "zero bonus skips unavailable step")
        await press("back")
        r.check(await state.get_state() == Checkout.promo.state, "Back skips unavailable bonus without loop")
        # An active form from before deployment gets new scoped controls.
        await state.update_data(step_id=None)
        before = (await state.get_data()).get("promo")
        await feed("skip", True)
        r.check(await state.get_state() == Checkout.promo.state and bool((await state.get_data()).get("step_id"))
                and (await state.get_data()).get("promo") == before, "legacy prompt refreshed without applying unscoped action")
        await press("skip")
        await press("paycard")
        await press("skip")
        await edit("phone")
        await press("keep")
        r.check(any(p.get("reply_markup", {}).get("remove_keyboard") for _, p in session.calls),
                "keeping phone removes contact keyboard")
        await edit("phone")
        await press("back")
        r.check(any(p.get("reply_markup", {}).get("remove_keyboard") for _, p in session.calls),
                "leaving phone edit removes contact keyboard")
        await edit("bonus")
        await is_summary("unavailable bonus edit returns to valid summary")
        r.check((await state.get_data())["use_bonus"] is False, "unavailable bonus resets previous selection")
        await edit("promo")
        await feed("TEN")
        async with open_repo() as repo:
            await repo.update_promo(promo.id, {"is_active": False})
        await edit("city")
        await feed("Одеса")
        r.check(await state.get_state() == Checkout.promo.state
                and (await state.get_data())["city"] == "Одеса"
                and not (await state.get_data()).get("quote_token"),
                "expired promo redirects to repair without losing edited city")
        await press("skip")
        await is_summary("removing expired promo restores confirmation")
        await edit("address")
        async with open_repo() as repo:
            await repo.set_cart_qty(user.id, product.id, 0)
        await feed("Відділення 3")
        r.check(await state.get_state() == Checkout.confirm.state
                and not (await state.get_data()).get("quote_token"),
                "empty cart during edit cannot be confirmed")
        refresh = button("order:refresh:")
        async with open_repo() as repo:
            await repo.set_cart_qty(user.id, product.id, 1)
        await feed(refresh, True)
        await is_summary("restored cart can refresh preserved form")
        await feed(button("order:cancel:"), True)
        async with open_repo() as repo:
            r.check(await state.get_state() is None and await repo.count_orders() == 1
                    and bool(await repo.get_cart(user.id)), "summary cancel preserves cart and existing order")
    finally:
        await dp.storage.close()
        await dp.fsm.events_isolation.close()
        await bot.session.close()
        await engine.dispose()


asyncio.run(main())
raise SystemExit(bool(r.done()))
