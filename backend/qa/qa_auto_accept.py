"""АВТОПРИЙНЯТТЯ: замовлення приймається відкриттям картки.

Окремої кнопки «прийняти» більше немає. Замість неї працюють дві події:
відкриття картки переводить замовлення в «Прийняте» і повідомляє клієнта,
а перше повідомлення менеджера закріплює замовлення за ним і називає
клієнту ім'я.

Розділення важливе саме тому, що його легко зламати назад. Якщо відкриття
почне закріплювати менеджера, замовлення дістанеться першому, хто просто
глянув, — а вести його буде інший.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, "/tmp")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  DASHBOARD_LOGIN="root", DASHBOARD_PASSWORD="Pa$$w0rd123",
                  ELFAR_DATA_ROOT=tempfile.mkdtemp(prefix="qa_accept_"),
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_accept.db")

from qa_common import Report                              # noqa: E402

r = Report("АВТОПРИЙНЯТТЯ")

import httpx                                              # noqa: E402
from decimal import Decimal                               # noqa: E402

from api.auth import create_token                         # noqa: E402
from api.main import app                                  # noqa: E402
from shop.entities import (                               # noqa: E402
    OperatorRole, Order, OrderLine, OrderStatus,
)
from shop.repo.factory import open_repo                   # noqa: E402

ANNA = create_token("anna", OperatorRole.MANAGER, 7, "Анна")
BORYS = create_token("borys", OperatorRole.MANAGER, 9, "Борис")


class FakeBot:
    """Замість Telegram. Збирає те, що пішло б клієнту."""

    def __init__(self):
        self.sent = []
        self._i = 0

    async def send_message(self, chat_id, text, **kw):
        self._i += 1
        self.sent.append(text)
        return type("M", (), {"message_id": self._i})()


async def make_order(repo, tg_id: int, payment: str = "card"):
    user = await repo.create_user(tg_id, f"u{tg_id}", "Клієнт", None)
    category = await repo.create_category({"name": f"Кат{tg_id}"})
    product = await repo.create_product({
        "name": f"Товар{tg_id}", "category_id": category.id,
        "price": Decimal(100), "stock": 10, "is_active": True,
    })
    order = await repo.create_order(
        Order(id=0, user_id=user.id, subtotal=Decimal(100), discount=Decimal(0),
              bonus_used=Decimal(0), total=Decimal(100), promo_code_id=None,
              payment_method=payment, contact_name="Тест",
              contact_phone="+380671112233"),
        [OrderLine(product_id=product.id, name=product.name,
                   price=Decimal(100), qty=1)],
    )
    return user, order


async def scenario():
    from shop.db import init_db
    import api.routers.telegram as tg

    await init_db()
    bot = FakeBot()
    tg._instances = lambda: (bot, None)
    transport = httpx.ASGITransport(app=app)

    async with open_repo() as repo:
        _, first = await make_order(repo, 6001)
        _, second = await make_order(repo, 6002, "cod")

    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        anna = {"Authorization": f"Bearer {ANNA}"}
        borys = {"Authorization": f"Bearer {BORYS}"}

        print("\n--- відкриття картки приймає замовлення ---")
        async with open_repo() as repo:
            before = await repo.get_order(first.id)
        r.check(before.status == OrderStatus.NEW,
                "до відкриття замовлення нове", before.status.value)

        response = await client.get(f"/api/orders/{first.id}", headers=anna)
        r.check(response.status_code == 200, "картка відкрилась", response.text[:120])
        r.check(response.json()["status"] == "accepted",
                "у відповіді вже «Прийняте», а не старий статус",
                response.json()["status"])

        async with open_repo() as repo:
            after = await repo.get_order(first.id)
        r.check(after.status == OrderStatus.ACCEPTED,
                "статус збережено в базі", after.status.value)

        print("\n--- клієнта повідомили, але без імені ---")
        r.check(len(bot.sent) == 1, "пішло рівно одне повідомлення", str(len(bot.sent)))
        text = bot.sent[0] if bot.sent else ""
        r.check("прийнято в роботу" in text.lower(),
                "клієнт дізнався, що замовлення взяли", text[:80])
        r.check("Анна" not in text,
                "імені того, хто просто відкрив картку, у тексті немає", text[:120])

        print("\n--- відкриття не закріплює менеджера ---")
        r.check(not after.operator_id,
                "замовлення ще нічиє", str(after.operator_id))
        r.check(not (after.operator_name or ""),
                "імені менеджера ще немає", after.operator_name)

        print("\n--- повторне відкриття нічого не робить ---")
        sent_before = len(bot.sent)
        await client.get(f"/api/orders/{first.id}", headers=borys)
        r.check(len(bot.sent) == sent_before,
                "друге відкриття не шле клієнту ще одне повідомлення",
                f"{sent_before} → {len(bot.sent)}")

        print("\n--- перше повідомлення закріплює замовлення ---")
        response = await client.post(f"/api/orders/{first.id}/messages",
                                     headers=borys, json={"text": "Вітаю!"})
        r.check(response.status_code == 201, "повідомлення надіслано",
                response.text[:120])
        async with open_repo() as repo:
            owned = await repo.get_order(first.id)
        r.check(owned.operator_name == "Борис",
                "замовлення закріпилось за тим, хто написав", owned.operator_name)
        r.check(owned.operator_id == 9, "збережено і номер менеджера",
                str(owned.operator_id))

        print("\n--- друга людина не перехоплює замовлення ---")
        await client.post(f"/api/orders/{first.id}/messages",
                          headers=anna, json={"text": "Я підміню"})
        async with open_repo() as repo:
            still = await repo.get_order(first.id)
        r.check(still.operator_name == "Борис",
                "власник замовлення не змінився", still.operator_name)

        print("\n--- маршрут накладеного платежу ---")
        # Спосіб оплати звіряємо явно. Перша версія цього набору його не
        # задавала, отримувала картковий маршрут — і «перевірка COD»
        # проходила повз те, що мала перевіряти.
        async with open_repo() as repo:
            cod_order = await repo.get_order(second.id)
        r.check(cod_order.payment_method == "cod",
                "друге замовлення справді з накладеним платежем",
                cod_order.payment_method)

        await client.get(f"/api/orders/{second.id}", headers=anna)
        response = await client.patch(f"/api/orders/{second.id}", headers=anna,
                                      json={"status": "paid"})
        r.check(response.status_code == 409,
                "«Оплачено» при накладеному платежі відхилено",
                f"{response.status_code}")

        print("\n--- прибраний крок недосяжний ---")
        response = await client.patch(f"/api/orders/{first.id}", headers=anna,
                                      json={"status": "confirmed"})
        r.check(response.status_code == 409,
                "перевести в «Підтверджене» більше не можна",
                f"{response.status_code}")


asyncio.run(scenario())
r.done()
sys.exit(1 if r.fails else 0)
