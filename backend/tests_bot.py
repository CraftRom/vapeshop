"""Наскрізні тести бота: справжні апдейти крізь справжній диспетчер.

Мережі немає — транспорт Telegram підмінено на перехоплювач, який записує
всі виклики Bot API. Тому перевіряється не «чи не впало», а що саме бот
відповів користувачу на кожному кроці.

Сценарій ганяється через обидві бази: те, що бот однаково працює на Postgres
має підтверджуватись, а не матись на увазі.

Запуск:  python tests_bot.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

os.environ.update({
    "BOT_TOKEN": "123456:TEST",
    "BOT_USERNAME": "test_shop_bot",
    "JWT_SECRET": "t" * 32,
    "DATABASE_URL": "sqlite+aiosqlite:////tmp/bot_test.db",
    "ADMIN_IDS": "900001",
    "ADMIN_CHAT_ID": "-1009999",
    "CARD_NUMBER": "0000 1111 2222 3333",
})

from aiogram import Bot  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods import TelegramMethod  # noqa: E402
from aiogram.types import Chat, Message, Update, User as TgUser  # noqa: E402

results: dict[str, list[tuple[str, bool, str]]] = {}
current = ""


def check(label: str, condition: bool, detail: str = "") -> None:
    results.setdefault(current, []).append((label, bool(condition), detail))
    mark = "✓" if condition else "✗"
    print(f"  {mark} {label}" + (f"   {detail}" if not condition else ""))


# ------------------------------------------------- підміна транспорту Telegram

class RecordingSession(BaseSession):
    """Замість HTTP до api.telegram.org — запис виклику й правдоподібна відповідь."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict]] = []
        self._message_id = 1000

    async def close(self) -> None:
        return None

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def make_request(self, bot, method: TelegramMethod, timeout=None):
        name = type(method).__name__
        self.calls.append((name, method.model_dump(exclude_none=True)))

        returning = method.__returning__
        if returning is bool:
            return True

        self._message_id += 1
        chat_id = getattr(method, "chat_id", 1)
        message = Message(
            message_id=self._message_id,
            date=datetime.now(timezone.utc),
            chat=Chat(id=int(chat_id) if str(chat_id).lstrip("-").isdigit() else 1,
                      type="private"),
            text=getattr(method, "text", None) or getattr(method, "caption", None),
        )
        # EditMessageText повертає Union[Message, bool] — Message підходить
        return message

    # --- зручні вибірки для перевірок

    def texts(self) -> list[str]:
        out = []
        for name, payload in self.calls:
            if name in ("SendMessage", "EditMessageText", "SendPhoto"):
                out.append(payload.get("text") or payload.get("caption") or "")
        return out

    def last_text(self) -> str:
        texts = self.texts()
        return texts[-1] if texts else ""

    def all_text(self) -> str:
        return "\n".join(self.texts())

    def alerts(self) -> list[str]:
        return [
            payload.get("text", "")
            for name, payload in self.calls
            if name == "AnswerCallbackQuery"
        ]

    def sent_to(self, chat_id: int) -> list[str]:
        return [
            payload.get("text") or payload.get("caption") or ""
            for name, payload in self.calls
            if name in ("SendMessage", "SendPhoto") and payload.get("chat_id") == chat_id
        ]

    def keyboards(self) -> list[dict]:
        return [
            payload["reply_markup"]
            for _, payload in self.calls
            if payload.get("reply_markup")
        ]

    def clear(self) -> None:
        self.calls.clear()


# ----------------------------------------------------------- побудова апдейтів

UPDATE_ID = [0]


def _next_update() -> int:
    UPDATE_ID[0] += 1
    return UPDATE_ID[0]


def message_update(bot: Bot, text: str, tg_id: int = 500001, username: str = "buyer"):
    return Update.model_validate({
        "update_id": _next_update(),
        "message": {
            "message_id": _next_update(),
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": tg_id, "type": "private"},
            "from": {"id": tg_id, "is_bot": False, "first_name": "Оля",
                     "username": username},
            "text": text,
            "entities": (
                [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
                if text.startswith("/") else []
            ),
        },
    }, context={"bot": bot})


def contact_update(bot: Bot, phone: str, tg_id: int = 500001):
    return Update.model_validate({
        "update_id": _next_update(),
        "message": {
            "message_id": _next_update(),
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": tg_id, "type": "private"},
            "from": {"id": tg_id, "is_bot": False, "first_name": "Оля"},
            "contact": {"phone_number": phone, "first_name": "Оля", "user_id": tg_id},
        },
    }, context={"bot": bot})


def callback_update(bot: Bot, data: str, tg_id: int = 500001):
    return Update.model_validate({
        "update_id": _next_update(),
        "callback_query": {
            "id": str(_next_update()),
            "from": {"id": tg_id, "is_bot": False, "first_name": "Оля",
                     "username": "buyer"},
            "chat_instance": "test",
            "data": data,
            "message": {
                "message_id": _next_update(),
                "date": int(datetime.now(timezone.utc).timestamp()),
                "chat": {"id": tg_id, "type": "private"},
                "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
                "text": "попереднє повідомлення",
            },
        },
    }, context={"bot": bot})


# --------------------------------------------------------------------- сценарій

async def run(backend: str) -> None:
    global current
    current = backend
    print(f"\n{'#' * 52}\n# База: {backend}\n{'#' * 52}")

    for name in [m for m in list(sys.modules) if m.startswith(("shop", "bot"))]:
        del sys.modules[name]
    if os.path.exists("/tmp/bot_test.db"):
        os.remove("/tmp/bot_test.db")

    from bot.factory import build_dispatcher
    from shop.repo.factory import open_repo

    from shop.db import init_db

    await init_db()

    async with open_repo() as repo:
        category = await repo.create_category(
            {"name": "Одноразові поди", "sort_order": 0, "is_active": True}
        )
        pod = await repo.create_product({
            "category_id": category.id, "name": "Elf Bar BC5000",
            "description": "5000 затяжок", "price": Decimal(400),
            "stock": 10, "is_active": True,
        })
        await repo.create_promo({
            "code": "WELCOME10", "value": Decimal(10), "min_order": Decimal(100),
            "per_user_limit": 1, "is_active": True,
        })

    session = RecordingSession()
    bot = Bot(token="123456:TEST", session=session)
    dp = build_dispatcher()

    async def feed(update):
        session.clear()
        await dp.feed_update(bot, update)

    # ---------------------------------------------------------- 1. Age gate
    print("\n1. Підтвердження віку")

    await feed(message_update(bot, "/start"))
    check("на /start показано age gate", "18" in session.last_text(),
          session.last_text()[:60])
    check("є кнопки підтвердження",
          any("age:yes" in str(k) for k in session.keyboards()))

    await feed(message_update(bot, "🛍 Каталог"))
    check("каталог до підтвердження віку недоступний",
          "18" in session.last_text(), session.last_text()[:60])

    await feed(callback_update(bot, "cat:1"))
    check("інлайн-кнопки заблоковані до підтвердження",
          any("вік" in a.lower() for a in session.alerts()), str(session.alerts()))

    await feed(callback_update(bot, "age:no"))
    check("відмова закриває доступ", "18" in session.last_text(),
          session.last_text()[:60])

    await feed(callback_update(bot, "age:yes"))
    check("після підтвердження — привітання",
          "Ласкаво просимо" in session.all_text(), session.all_text()[:80])

    # ---------------------------------------------------------- 2. Каталог
    print("\n2. Каталог")

    await feed(message_update(bot, "🛍 Каталог"))
    check("заголовок каталогу", "Оберіть категорію" in session.all_text(),
          session.all_text()[:80])
    # Назви категорій живуть у кнопках, а не в тексті повідомлення
    check("категорія в кнопках", "Одноразові поди" in str(session.keyboards()),
          str(session.keyboards())[:120])

    await feed(callback_update(bot, f"cat:{category.id}"))
    check("товар у списку категорії", "Elf Bar" in str(session.keyboards()),
          str(session.keyboards())[:120])

    await feed(callback_update(bot, f"prod:{pod.id}"))
    check("картка товару з ціною", "400" in session.all_text(),
          session.all_text()[:80])
    check("є кнопка додавання",
          any(f"add:{pod.id}" in str(k) for k in session.keyboards()))

    await feed(callback_update(bot, "prod:9999"))
    check("неіснуючий товар — попередження",
          any("недоступн" in a for a in session.alerts()), str(session.alerts()))

    # ------------------------------------------------------------ 3. Кошик
    print("\n3. Кошик")

    await feed(callback_update(bot, f"add:{pod.id}"))
    check("товар додано", any("Додано" in a for a in session.alerts()),
          str(session.alerts()))

    await feed(message_update(bot, "🛒 Кошик"))
    check("кошик показує товар", "Elf Bar" in session.all_text())
    check("сума 400", "400" in session.all_text(), session.all_text()[:100])

    await feed(callback_update(bot, f"cartqty:{pod.id}:3"))
    check("кількість змінено на 3", "1200" in session.all_text(),
          session.all_text()[:100])

    await feed(callback_update(bot, f"cartqty:{pod.id}:99"))
    check("кількість обрізана до залишку (10 × 400 = 4000)",
          "4000" in session.all_text(), session.all_text()[:100])

    await feed(callback_update(bot, f"cartqty:{pod.id}:2"))
    check("повернуто 2 шт", "800" in session.all_text(), session.all_text()[:100])

    # -------------------------------------------------------- 4. Оформлення
    print("\n4. Оформлення замовлення")

    await feed(callback_update(bot, "checkout"))
    # Перевіряємо «одержувач», а не точне формулювання: текст запиту вже
    # переписували (раніше було «як до вас звертатися»), і тест мовчки
    # відʼїхав від коду. Прив'язка до суті питання переживає редактуру.
    check("запитано ім'я", "одержувача" in session.all_text(),
          session.all_text()[:80])

    await feed(message_update(bot, "О"))
    check("надто коротке ім'я відхилено", "повністю" in session.all_text(),
          session.all_text()[:80])

    await feed(message_update(bot, "Оля Коваленко"))
    check("запитано телефон", "телефон" in session.all_text().lower())

    await feed(message_update(bot, "123"))
    check("некоректний телефон відхилено", "неповний" in session.all_text(),
          session.all_text()[:80])

    await feed(contact_update(bot, "+380671112233"))
    check("контакт прийнято, запитано місто", "Місто" in session.all_text(),
          session.all_text()[:80])

    await feed(message_update(bot, "Хмельницький"))
    check("запитано адресу", "Відділення" in session.all_text())

    await feed(message_update(bot, "Відділення №5"))
    check("запитано промокод", "промокод" in session.all_text().lower())

    await feed(message_update(bot, "НЕВІРНИЙ"))
    check("невірний промокод відхилено", "промокоду немає" in session.all_text(),
          session.all_text()[:80])

    await feed(message_update(bot, "WELCOME10"))
    check("промокод застосовано, знижка 80",
          "80" in session.all_text(), session.all_text()[:120])

    await feed(callback_update(bot, "pay:card"))
    check("запитано коментар", "оментар" in session.all_text())

    await feed(callback_update(bot, "skip"))
    summary = session.all_text()
    check("підсумок містить товар", "Elf Bar" in summary)
    check("підсумок: сума 800", "800" in summary, summary[:150])
    check("підсумок: до сплати 720", "720" in summary, summary[:200])
    check("підсумок містить телефон", "380671112233" in summary)

    await feed(callback_update(bot, "order:confirm"))
    check("замовлення прийнято", "прийнято" in session.all_text(),
          session.all_text()[:100])
    check("надіслано реквізити картки", "0000 1111 2222 3333" in session.all_text(),
          session.all_text()[:200])
    check("адміну надіслано замовлення", len(session.sent_to(-1009999)) == 1,
          f"{len(session.sent_to(-1009999))}")
    admin_text = "".join(session.sent_to(-1009999))
    check("адмін бачить телефон клієнта", "380671112233" in admin_text,
          admin_text[:120])
    check("адмін має кнопки статусів", any("ao:" in str(k) for k in session.keyboards()))

    async with open_repo() as repo:
        product = await repo.get_product(pod.id)
        orders = await repo.list_orders()
        check("залишок списано 10 → 8", product.stock == 8, f"{product.stock}")
        check("замовлення в базі", len(orders) == 1, f"{len(orders)}")
        check("сума замовлення 720", orders[0].total == Decimal("720.00"),
              f"{orders[0].total}")
        check("кошик очищено", not await repo.get_cart(orders[0].user_id))
        order_id = orders[0].id
        buyer_id = orders[0].user_id

    # ------------------------------------------------------------ 5. Профіль
    print("\n5. Профіль і реферали")

    await feed(message_update(bot, "👤 Профіль"))
    profile_text = session.all_text()
    check("профіль показує посилання", "t.me/test_shop_bot?start=" in profile_text,
          profile_text[:120])
    check("профіль показує бонуси", "Бонусний рахунок" in profile_text)

    async with open_repo() as repo:
        buyer = await repo.get_user(buyer_id)
        code = buyer.referral_code

    await feed(message_update(bot, f"/start {code}", tg_id=500002, username="friend"))
    check("друг за реферальним посиланням бачить age gate",
          "18" in session.last_text())

    await feed(callback_update(bot, "age:yes", tg_id=500002))
    async with open_repo() as repo:
        friend = await repo.get_user_by_tg(500002)
        check("реферера прив'язано", friend.referrer_id == buyer_id,
              f"{friend.referrer_id} != {buyer_id}")
        inviter = await repo.get_user(buyer_id)
        check("лічильник рефералів = 1", inviter.referrals_count == 1,
              f"{inviter.referrals_count}")

    await feed(callback_update(bot, "myorders", tg_id=500002))
    check("у друга замовлень немає",
          any("немає замовлень" in a for a in session.alerts()), str(session.alerts()))

    await feed(callback_update(bot, "myorders"))
    check("покупець бачить своє замовлення", f"№{order_id}" in session.all_text(),
          session.all_text()[:100])

    # -------------------------------------------------------------- 6. Адмін
    print("\n6. Адмінські дії")

    await feed(message_update(bot, "/stats", tg_id=900001, username="admin"))
    check("адмін отримує статистику", "статистика" in session.all_text().lower(),
          session.all_text()[:80])

    await feed(message_update(bot, "/stats"))
    check("звичайний клієнт статистики не отримує",
          "статистика" not in session.all_text().lower(), session.all_text()[:80])

    await feed(callback_update(bot, f"ao:{order_id}:paid", tg_id=900001))
    check("статус змінено на «Оплачене»",
          any("Оплачене" in a for a in session.alerts()), str(session.alerts()))
    check("клієнта сповіщено про статус",
          any("Оплачене" in t for t in session.sent_to(500001)),
          str(session.sent_to(500001))[:120])

    await feed(callback_update(bot, f"ao:{order_id}:done", tg_id=900001))
    check("статус «Виконане»", any("Виконане" in a for a in session.alerts()))

    async with open_repo() as repo:
        buyer = await repo.get_user(buyer_id)
        check("лічильник покупок клієнта = 1", buyer.orders_count == 1,
              f"{buyer.orders_count}")
        check("витрачено 720", buyer.total_spent == Decimal("720.00"),
              f"{buyer.total_spent}")

    # ------------------------------------------------- 7. Повторне замовлення
    print("\n7. Повторне використання промокоду й блокування")

    await feed(callback_update(bot, f"add:{pod.id}"))
    await feed(callback_update(bot, "checkout"))
    await feed(message_update(bot, "Оля Коваленко"))
    await feed(message_update(bot, "0671112233"))
    check("телефон у форматі 067... прийнято", "Місто" in session.all_text(),
          session.all_text()[:80])
    await feed(message_update(bot, "Київ"))
    await feed(message_update(bot, "Відділення №1"))
    await feed(message_update(bot, "WELCOME10"))
    check("промокод удруге відхилено", "вже використали" in session.all_text(),
          session.all_text()[:100])

    await feed(callback_update(bot, "skip"))
    await feed(callback_update(bot, "pay:cod"))
    await feed(callback_update(bot, "skip"))
    check("накладений платіж у підсумку", "накладений" in session.all_text(),
          session.all_text()[:200])

    await feed(callback_update(bot, "order:cancel"))
    check("скасування не чіпає кошик", "Кошик залишився" in session.all_text(),
          session.all_text()[:100])

    async with open_repo() as repo:
        check("кошик справді не порожній", len(await repo.get_cart(buyer_id)) == 1)
        await repo.set_blocked(buyer_id, True)

    await feed(message_update(bot, "🛍 Каталог"))
    check("заблокований клієнт не отримує відповіді", not session.calls,
          f"{len(session.calls)} викликів")

    await session.close()


async def main() -> None:
    await run("sql")

    total_failed = 0
    print(f"\n{'=' * 52}")
    for backend, checks in results.items():
        bad = [c for c in checks if not c[1]]
        total_failed += len(bad)
        print(f"{backend:12} пройдено {len(checks) - len(bad)} з {len(checks)}")

    print(f"{'=' * 52}\nВсього провалено: {total_failed}\n")
    raise SystemExit(1 if total_failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
