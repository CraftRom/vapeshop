"""SALESDRIVE І ТТН: одна структура замовлення, накладної й синхронізації.

Що стережемо:
  - заявка SalesDrive і ТТН Нової пошти будуються з одних і тих самих даних
    (shop/services/shipment.py) — імʼя, телефон, сума, накладений платіж;
  - черга CRM не губить змін і не створює дублів після таймауту;
  - вебхук застосовує статус і накладну за тими ж правилами, що й панель,
    і не відправляє їх назад у SalesDrive (петля);
  - секрети не повертаються в панель і не лишаються в журналі.

HTTP-виклики SalesDrive і Нової пошти підмінено: набір не ходить у мережу.
"""
import asyncio
import json
import os
import sys
import tempfile
from decimal import Decimal

sys.path.insert(0, "/tmp")
from cryptography.fernet import Fernet  # noqa: E402

DB = "/tmp/qa_salesdrive.db"
for suffix in ("", "-wal", "-shm"):
    try:
        os.unlink(DB + suffix)
    except FileNotFoundError:
        pass
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  DASHBOARD_LOGIN="root", DASHBOARD_PASSWORD="Pa$$w0rd123",
                  DATA_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                  ELFAR_DATA_ROOT=tempfile.mkdtemp(prefix="qa_sd_"),
                  PUBLIC_URL="https://elfar.pp.ua",
                  DATABASE_URL=f"sqlite+aiosqlite:///{DB}")

from qa_common import Report, seed_operators                  # noqa: E402

r = Report("SALESDRIVE І ТТН")

import httpx                                                  # noqa: E402

from api.auth import create_token                             # noqa: E402
from api.main import app                                      # noqa: E402
from shop.entities import OperatorRole, Order, OrderLine, OrderStatus  # noqa: E402
from shop.repo.factory import open_repo                       # noqa: E402
from shop.services import novaposhta, order_workflow as flow, salesdrive, shipment, waybill  # noqa: E402
from shop.services.shop_settings import get_shop_settings, save_shop_settings, invalidate_cache  # noqa: E402

ROOT = create_token("root", OperatorRole.SYSADMIN, 1, "Root")
ANNA = create_token("anna", OperatorRole.MANAGER, 7, "Анна")
TOKEN = "Wh00k-" + "x" * 30

STATUS_MAP = {"new": "1", "confirmed": "2", "accepted": "2", "paid": "3",
              "shipped": "4", "done": "5", "cancelled": "6"}


class FakeBot:
    def __init__(self):
        self.sent = []
        self._i = 0

    async def send_message(self, chat_id, text, **kw):
        self._i += 1
        self.sent.append(text)
        return type("M", (), {"message_id": self._i})()


class FakeSalesDrive:
    """Відповіді SalesDrive за сценарієм. Записує, що саме пішло."""

    def __init__(self):
        self.calls = []
        self.script = []

    async def __call__(self, url, payload, headers):
        self.calls.append((url, payload, headers))
        action = self.script.pop(0) if self.script else ("ok", {"success": True})
        kind, body = action
        if kind == "timeout":
            raise httpx.ReadTimeout("timeout")
        status = body.pop("_status", 200) if isinstance(body, dict) else 200
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))


async def make_order(repo, tg_id, payment="card", with_refs=True, surname="Шевченко"):
    user = await repo.create_user(tg_id, f"u{tg_id}", "Клієнт", None)
    category = await repo.create_category({"name": f"Кат{tg_id}"})
    product = await repo.create_product({
        "name": f"Рідина {tg_id} 30 мл 50 мг", "category_id": category.id,
        "price": Decimal(349), "stock": 10, "is_active": True,
    })
    order = await repo.create_order(
        Order(id=0, user_id=user.id, subtotal=Decimal(698), discount=Decimal(50),
              bonus_used=Decimal(48), total=Decimal(600), promo_code_id=None,
              payment_method=payment, contact_name=f"{surname} Тарас Григорович",
              contact_surname=surname, contact_patronymic="Григорович",
              contact_phone="+38 (067) 111-22-33", delivery_city="Хмельницький",
              delivery_address="Відділення №5", delivery_method="warehouse",
              delivery_city_ref="city-ref-1" if with_refs else None,
              delivery_warehouse_ref="wh-ref-5" if with_refs else None,
              comment="Подзвоніть перед відправкою"),
        [OrderLine(product_id=product.id, name=product.name, price=Decimal(349), qty=2)],
    )
    return await repo.get_order(order.id)


async def scenario():
    from shop.db import init_db
    import api.routers.telegram as tg

    from shop.config import settings as app_settings
    app_settings.salesdrive_telegram_form_id = 4242

    await init_db()
    bot = FakeBot()
    tg._instances = lambda: (bot, None)

    print("\n--- вимкнена інтеграція не запускає фонових задач ---")
    # Саме цей збій вішав tests_repo: зміна статусу без увімкненого
    # SalesDrive запускала фонову задачу з власним зʼєднанням до бази.
    invalidate_cache()
    real_push = salesdrive.push_soon
    real_push(424242)
    r.check(not salesdrive._tasks and 424242 not in salesdrive._inflight,
            "без увімкненої інтеграції push_soon нічого не запускає",
            len(salesdrive._tasks))

    # Далі фонові відправки викликаємо явно, щоб бачити кожен крок.
    kicked = []
    salesdrive.push_soon = lambda order_id: kicked.append(order_id)

    async with open_repo() as repo:
        await seed_operators(repo, {1: ("root", "Root", OperatorRole.SYSADMIN),
                                    7: ("anna", "Анна", OperatorRole.MANAGER)})
        await save_shop_settings(repo, {
            "salesdrive_enabled": True, "salesdrive_domain": "elfar",
            "salesdrive_form_key": "FORM-SECRET-123", "salesdrive_api_key": "API-SECRET-456",
            "salesdrive_webhook_token": TOKEN,
            "salesdrive_status_map": json.dumps(STATUS_MAP),
            "salesdrive_payment_map": json.dumps({"card": "Переказ на картку", "cod": "Накладений платіж"}),
            "salesdrive_shipping_map": json.dumps({"warehouse": "Нова Пошта", "courier": "Курʼєр НП"}),
            "novaposhta_api_key": "NP-KEY-789", "novaposhta_sender_city": "Хмельницький",
            "novaposhta_sender_phone": "0671234567", "novaposhta_sender_warehouse_ref": "sender-wh",
            "delivery_weight_per_item": "0.3",
        })
        shop = await get_shop_settings(repo)
        order = await make_order(repo, 7001, payment="cod")

    print("\n--- спільна структура: отримувач і посилка ---")
    person = shipment.recipient(order)
    r.check((person.last_name, person.first_name, person.middle_name)
            == ("Шевченко", "Тарас", "Григорович"), "ПІБ складовими", person)
    r.check(person.phone == "380671112233", "телефон у форматі 380…", person.phone)
    legacy = Order(id=1, user_id=1, contact_name="Коваль Олена Петрівна", contact_phone="0501234567")
    r.check(shipment.recipient(legacy).first_name == "Олена", "старе замовлення без складових")
    box = shipment.parcel(order, shop)
    r.check(box.declared_cost == Decimal("600.00") and box.cod_amount == Decimal("600.00"),
            "оголошена вартість і післяплата — сума до сплати, а не кошика", box)
    r.check(box.weight_kg == Decimal("0.60"), "вага — позиції × вага позиції", box.weight_kg)

    print("\n--- заявка SalesDrive з тієї самої структури ---")
    created = salesdrive.create_payload(order, shop)
    r.check(created["externalId"] == str(order.id), "externalId — номер замовлення")
    r.check((created["lName"], created["fName"], created["mName"], created["phone"])
            == (person.last_name, person.first_name, person.middle_name, person.phone),
            "імʼя й телефон у заявці збігаються з накладною")
    r.check(created["products"][0]["costPerItem"] == "349" and created["products"][0]["amount"] == "2",
            "товари з ціною й кількістю", created["products"])
    r.check(created["payment_method"] == "Накладений платіж"
            and created["shipping_method"] == "Нова Пошта", "оплата й доставка — з відповідностей")
    r.check(created["novaposhta"].get("city") == "city-ref-1"
            and created["novaposhta"].get("WarehouseNumber") == "wh-ref-5",
            "коди Нової пошти — ті самі, що зберегла вітрина", created["novaposhta"])
    r.check("знижка 50" in created["comment"] and "до сплати 600" in created["comment"],
            "знижка й бонуси видно в коментарі заявки", created["comment"])
    r.check(created["statusId"] == "1", "статус заявки — з відповідності")

    print("\n--- відповідності перевіряються на вході ---")
    from api.schemas import ShopSettingsIn
    for bad, why in (('{"new": ', "зіпсований JSON"), ('{"sent": "4"}', "невідомий статус"),
                     ('["1"]', "не обʼєкт"), ('{"new": ""}', "порожнє значення")):
        try:
            ShopSettingsIn(salesdrive_status_map=bad)
            r.check(False, f"відхиляється: {why}")
        except ValueError:
            r.check(True, f"відхиляється: {why}")
    r.check(salesdrive.status_from_crm(shop, "2") == OrderStatus.ACCEPTED,
            "два наші статуси в один статус CRM — назад найпізніший, без відкату")
    r.check(salesdrive.status_from_crm(shop, "999") is None, "невідомий statusId ігнорується")

    print("\n--- черга: створення, збій, таймаут без дублів ---")
    fake = FakeSalesDrive()
    salesdrive._post = fake
    async with open_repo() as repo:
        fake.script = [("ok", {"success": True, "data": {"orderId": 5501}})]
        state = await salesdrive.push_order(repo, order.id, shop)
        saved = await repo.get_order(order.id)
    r.check(state == "synced" and saved.crm_id == "5501", "заявку створено, номер збережено",
            (state, saved.crm_id))
    r.check(fake.calls[-1][0] == "https://elfar.salesdrive.me/handler/", "адреса — лише з субдомену")

    async with open_repo() as repo:
        timeout_order = await make_order(repo, 7002)
        fake.script = [("timeout", None)]
        state = await salesdrive.push_order(repo, timeout_order.id, shop)
        after = await repo.get_order(timeout_order.id)
    r.check(state == "uncertain" and after.crm_attempts == 1,
            "таймаут на створенні — стан невідомий, а не «помилка»", (state, after.crm_attempts))

    async with open_repo() as repo:
        fake.calls.clear()
        fake.script = [("ok", {"success": True})]
        state = await salesdrive.push_order(repo, timeout_order.id, shop)
    r.check(state == "synced" and len(fake.calls) == 1
            and fake.calls[0][0].endswith("/api/order/update/"),
            "після таймауту спершу оновлення — заявка вже була, дубль не створено",
            [c[0] for c in fake.calls])

    async with open_repo() as repo:
        lost = await make_order(repo, 7003)
        await repo.update_order(lost.id, {"crm_state": "uncertain"})
        fake.calls.clear()
        fake.script = [("ok", {"success": False, "message": "order not found"}),
                       ("ok", {"success": True, "data": {"id": 5503}})]
        state = await salesdrive.push_order(repo, lost.id, shop)
        lost = await repo.get_order(lost.id)
    r.check(state == "synced" and lost.crm_id == "5503"
            and [c[0].rsplit("/", 2)[-2] for c in fake.calls] == ["update", "handler"],
            "оновлювати нічого — тоді створення", [c[0] for c in fake.calls])

    async with open_repo() as repo:
        down = await make_order(repo, 7004)
        fake.script = [("ok", {"_status": 503})]
        state = await salesdrive.push_order(repo, down.id, shop)
        down = await repo.get_order(down.id)
    r.check(state == "failed" and "503" in (down.crm_error or ""),
            "SalesDrive лежить — причина видна в замовленні", down.crm_error)

    print("\n--- кожна зміна стає в чергу CRM тим самим записом ---")
    async with open_repo() as repo:
        fresh = await repo.get_order(order.id)
        await flow.apply_status(repo, fresh, OrderStatus.ACCEPTED, origin=flow.ORIGIN_PANEL, bot=bot)
        fresh = await repo.get_order(order.id)
    r.check(fresh.crm_state == "pending", "зміна статусу з панелі ставить позначку", fresh.crm_state)
    r.check(order.id in kicked, "і одразу запускає фонову відправку")
    update = salesdrive.update_payload(fresh, shop)
    r.check(update.get("id") == "5501" and update["data"].get("statusId") == "2"
            and "comment" not in update["data"],
            "оновлення — за номером заявки, лише статус, чужі правки в CRM не затираються", update)

    print("\n--- ТТН Нової пошти: та сама структура, той самий шлях ---")
    async with open_repo() as repo:
        manual_ref = await make_order(repo, 7005, with_refs=False)
        await repo.update_order(manual_ref.id, {"status": OrderStatus.ACCEPTED})
        manual_ref = await repo.get_order(manual_ref.id)
    problem = waybill.readiness(manual_ref, shop)
    r.check(problem and "без коду довідника" in problem, "без кодів відділення — зрозуміла причина", problem)

    np_calls = []

    async def fake_np(payload):
        np_calls.append(payload)
        method = (payload["modelName"], payload["calledMethod"])
        if method == ("Counterparty", "getCounterparties"):
            return {"success": True, "data": [{"Ref": "sender-cp"}]}
        if method == ("Counterparty", "getCounterpartyContactPersons"):
            return {"success": True, "data": [{"Ref": "sender-contact"}]}
        if method == ("Address", "searchSettlements"):
            return {"success": True, "data": [{"Addresses": [{"DeliveryCity": "sender-city", "Ref": "s",
                                                             "MainDescription": "Хмельницький",
                                                             "Warehouses": "10"}]}]}
        if method == ("Counterparty", "save"):
            return {"success": True, "data": [{"Ref": "rcp", "ContactPerson": {"data": [{"Ref": "rcp-contact"}]}}]}
        if method == ("InternetDocument", "save"):
            return {"success": True, "data": [{"Ref": "doc-ref", "IntDocNumber": "20450000123456",
                                               "CostOnSite": "85", "EstimatedDeliveryDate": "20.09.2026"}]}
        if method == ("InternetDocument", "delete"):
            return {"success": True, "data": [{"Ref": "doc-ref"}]}
        return {"success": True, "data": []}

    novaposhta._post = fake_np
    waybill.reset_sender_cache()

    async def fake_city(key, name):
        return "sender-city"
    novaposhta.city_ref_by_name = fake_city

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        anna = {"Authorization": f"Bearer {ANNA}"}
        async with open_repo() as repo:
            await repo.update_order(order.id, {"crm_state": "synced"})
        response = await client.post(f"/api/orders/{order.id}/waybill", headers=anna)
        r.check(response.status_code == 200, "ТТН створено з панелі", response.text[:200])
        body = response.json()
        r.check(body["tracking_number"] == "20450000123456" and body["waybill_source"] == "novaposhta"
                and body["waybill_ref"] == "doc-ref", "номер, ref і джерело в замовленні", body)
        r.check(body["crm_state"] == "pending", "нова ТТН стає в чергу SalesDrive", body["crm_state"])
        doc = next(p for p in np_calls if p["calledMethod"] == "save" and p["modelName"] == "InternetDocument")
        props = doc["methodProperties"]
        r.check(props["RecipientsPhone"] == person.phone and props["Cost"] == "600",
                "телефон і сума в ТТН — ті самі, що в заявці CRM", props)
        r.check(props.get("BackwardDeliveryData", [{}])[0].get("RedeliveryString") == "600",
                "накладений платіж — на суму до сплати", props.get("BackwardDeliveryData"))
        r.check(props["CityRecipient"] == "city-ref-1" and props["RecipientAddress"] == "wh-ref-5",
                "адреса ТТН — коди, збережені вітриною")

        async with open_repo() as repo:
            synced_order = await repo.get_order(order.id)
        ttn_update = salesdrive.update_payload(synced_order, shop)
        r.check(ttn_update["data"].get("novaposhta") == {"ttn": "20450000123456"},
                "ТТН із панелі їде в заявку SalesDrive", ttn_update["data"])

        again = await client.post(f"/api/orders/{order.id}/waybill", headers=anna)
        r.check(again.status_code == 422 and "вже є накладна" in again.text,
                "друга ТТН на те саме замовлення не створюється", again.text[:120])

        print("\n--- вебхук: ті самі правила, без петлі ---")
        wrong = await client.post("/api/integrations/salesdrive/webhook/" + "y" * 36, json={})
        r.check(wrong.status_code == 404, "невірний токен — адреса «не існує»", wrong.status_code)
        foreign = await client.post(f"/api/integrations/salesdrive/webhook/{TOKEN}",
                                    json={"info": {"webhookEvent": "status_change", "account": "elfar"},
                                          "data": {"id": 9001, "formId": 9999, "statusId": "4"}})
        r.check(foreign.status_code == 200 and foreign.json().get("reason") == "інша база заявок SalesDrive",
                "webhook з іншої бази SalesDrive ігнорується", foreign.text[:160])

        async with open_repo() as repo:
            # Накладений платіж: «Прийняте → Відправлене» дозволено спільним
            # маршрутом. Для картки той самий стрибок відхилився б — і це
            # правильно, CRM не обходить правила магазину.
            hooked = await make_order(repo, 7006, payment="cod")
            await repo.update_order(hooked.id, {"crm_id": "9001", "crm_state": "synced",
                                                "status": OrderStatus.ACCEPTED})
        payload = {"info": {"webhookType": "order", "webhookEvent": "status_change", "account": "elfar"},
                   "data": {"id": 9001, "formId": 4242, "statusId": "4",
                            "ord_novaposhta": {"EN": "20450000999999", "ENref": "sd-ref", "cost": "90"}}}
        kicked.clear()
        sent_before = len(bot.sent)
        response = await client.post(f"/api/integrations/salesdrive/webhook/{TOKEN}", json=payload)
        result = response.json()
        async with open_repo() as repo:
            hooked = await repo.get_order(hooked.id)
        r.check(result.get("applied") == ["tracking", "status"], "накладна, потім статус", result)
        r.check(hooked.status == OrderStatus.SHIPPED and hooked.tracking_number == "20450000999999"
                and hooked.waybill_source == "salesdrive", "замовлення відправлене з ТТН із CRM",
                (hooked.status, hooked.tracking_number, hooked.waybill_source))
        r.check(len(bot.sent) > sent_before, "клієнт отримав ТТН, як і зі зміною з панелі")
        r.check(hooked.crm_state == "synced" and hooked.id not in kicked,
                "зміна з CRM не повертається в CRM — петлі немає", (hooked.crm_state, kicked))

        repeat = await client.post(f"/api/integrations/salesdrive/webhook/{TOKEN}", json=payload)
        r.check(repeat.json().get("result") == "unchanged", "повтор того самого вебхука нічого не робить")

        async with open_repo() as repo:
            jump = await make_order(repo, 7007)
            await repo.update_order(jump.id, {"crm_id": "9002"})
        bad = {"info": {"webhookEvent": "status_change", "account": "elfar"}, "data": {"id": "9002", "formId": 4242, "statusId": "5"}}
        response = await client.post(f"/api/integrations/salesdrive/webhook/{TOKEN}", json=bad)
        async with open_repo() as repo:
            jump = await repo.get_order(jump.id)
        r.check(response.status_code == 200 and response.json()["result"] == "rejected",
                "недопустимий перехід із CRM відхилено, SalesDrive не повторює", response.text[:160])
        r.check(jump.status == OrderStatus.NEW and "не застосовано" in (jump.crm_error or ""),
                "причина відмови видна біля замовлення", jump.crm_error)

        unknown = await client.post(f"/api/integrations/salesdrive/webhook/{TOKEN}",
                                    json={"info": {"webhookEvent": "new_order", "account": "elfar"}, "data": {"id": 777, "formId": 4242}})
        r.check(unknown.json()["result"] == "ignored", "заявка, створена в CRM руками, ігнорується")

        print("\n--- секрети ---")
        shown = (await client.get("/api/settings", headers=anna)).json()
        r.check(not any(k in shown for k in salesdrive_secret_fields()),
                "ключі SalesDrive не повертаються в панель")
        r.check(shown.get("salesdrive_form_connected") is True, "замість ключа — ознака «підключено»")
        denied = await client.put("/api/settings", headers=anna, json={"salesdrive_form_key": "hack"})
        r.check(denied.status_code == 403, "менеджер не змінює ключі SalesDrive", denied.status_code)
        async with open_repo() as repo:
            raw = await repo.get_settings_map()
        r.check(raw.get("salesdrive_form_key", "").startswith("enc:v1:"), "ключ форми зашифровано в базі")

    from shop.logging_setup import redact
    line = f"POST /api/integrations/salesdrive/webhook/{TOKEN} → 200"
    r.check(TOKEN not in redact(line), "токен вебхука вирізається з журналу", redact(line))
    r.check("NP-KEY-789" not in redact("GET https://my.novaposhta.ua/orders/x/apiKey/NP-KEY-789"),
            "ключ Нової пошти з адреси друку не потрапляє в журнал")


def salesdrive_secret_fields():
    return ("salesdrive_form_key", "salesdrive_api_key", "salesdrive_webhook_token")


asyncio.run(scenario())
invalidate_cache()
r.done()
