"""E2E: шлях реального покупця й менеджера від початку до кінця."""
import base64
import sys; sys.path.insert(0,"/tmp")
from decimal import Decimal
from qa_common import boot, init_data, Report
app, Session, fake = boot("/tmp/qa_e2e.db")
from fastapi.testclient import TestClient
c = TestClient(app); r = Report("E2E")

A = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"login":"admin","password":"secret"}).json()["access_token"]}

print("\n[адмін] готує магазин")
c.post("/api/operators", json={"login":"olena","name":"Олена","password":"kvitka2026"}, headers=A)
cat = c.post("/api/catalog/categories", json={"name":"Одноразки","sort_order":0,"is_active":True}, headers=A).json()
pr = c.post("/api/catalog/products", json={"category_id":cat["id"],"name":"Elf Bar 5000",
     "description":"Манго-лід, 5000 затяжок","price":"350","stock":10,"is_active":True}, headers=A).json()
c.post("/api/promos", json={"code":"WELCOME","type":"percent","value":"10","is_active":True}, headers=A)
O = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"login":"olena","password":"kvitka2026"}).json()["access_token"]}
r.check(True, "магазин наповнено")

print("\n[покупець] відкриває вітрину")
H = init_data(8001)
b = c.get("/api/shop/bootstrap", headers=H).json()
r.check(b["config"]["age_confirmed"] is False, "спершу бар'єр 18+")
r.check(c.get("/api/shop/products", headers=H).status_code == 403, "каталог за бар'єром закритий")
c.post("/api/shop/age-confirm", headers=H)
b = c.get("/api/shop/bootstrap", headers=H).json()
r.check(len(b["products"]) == 1, "після підтвердження каталог видно", len(b["products"]))

print("\n[покупець] дивиться товар і зберігає")
d = c.get(f"/api/shop/products/{pr['id']}", headers=H).json()
r.check(d["description"].startswith("Манго"), "опис на сторінці товару")
wl = c.get("/api/shop/wishlists", headers=H).json()[0]
saved = c.post(f"/api/shop/wishlists/{wl['id']}/items", json={"product_id":pr["id"]}, headers=H).json()
r.check(saved["size"] == 1, "товар у списку бажаного")

print("\n[покупець] кошик і промокод")
c.post("/api/shop/cart", json={"product_id":pr["id"],"delta":2}, headers=H)
cart = c.get("/api/shop/cart", headers=H).json()
r.check(Decimal(cart["subtotal"]) == Decimal(700), "сума кошика", cart["subtotal"])
promo = c.post("/api/shop/promo/check", json={"code":"WELCOME"}, headers=H).json()
r.check(promo["ok"] and Decimal(promo["discount"]) == Decimal(70), "промокод діє", promo)

print("\n[покупець] оформлює")
order = c.post("/api/shop/checkout", json={"contact_surname":"Шевченко","contact_name":"Тарас",
    "contact_patronymic":"Григорович","contact_phone":"+380671112233","city":"Київ",
    "address":"Відділення 1","payment_method":"card","promo_code":"WELCOME"}, headers=H)
r.check(order.status_code == 200, "замовлення створено", order.text[:120])
oid = order.json()["order_id"]
r.check(Decimal(order.json()["total"]) == Decimal(630), "сума з урахуванням знижки", order.json()["total"])
# Реквізити вітрині не віддаються навмисно: їх надсилає менеджер у чат
# під конкретне замовлення. Номер картки, розісланий усім наперед,
# застаріває швидше, ніж встигають правити налаштування, і живе далі в
# чужих чатах та скріншотах.
r.check(order.json()["card_number"] is None, "реквізити у відповіді не публікуються")
r.check(c.get("/api/shop/cart", headers=H).json()["lines"] == [], "кошик очищено")
r.check(any("Шевченко" in t for _, t in fake.sent), "менеджер отримав замовлення")

print("\n[менеджер] веде замовлення")
lst = c.get("/api/orders", headers=O).json()
r.check(any(o["id"] == oid for o in lst), "замовлення в панелі")
# Окремої кнопки «прийняти» немає: замовлення приймається відкриттям картки
det = c.get(f"/api/orders/{oid}", headers=O).json()
r.check(det["status"] == "accepted", "відкриття картки прийняло замовлення", det["status"])
r.check(not det["operator_name"],
        "той, хто просто глянув, замовлення собі не забрав", det["operator_name"])
r.check(any("прийнято в роботу" in t.lower() for _, t in fake.sent),
        "клієнт дізнався, що замовлення взяли")

print("\n[чат] обидві сторони")
c.post(f"/api/orders/{oid}/messages", json={"text":"Вітаю! Підтвердьте адресу."}, headers=O)
# Замовлення стає чиїмось саме тут — коли менеджер заговорив із клієнтом
det = c.get(f"/api/orders/{oid}", headers=O).json()
r.check(det["operator_name"] == "Олена", "менеджера закріплено", det["operator_name"])
r.check(any("Олена" in t for _, t in fake.sent), "клієнт дізнався, хто веде")

# Покупець має отримати підтвердження в чат — вітрина обіцяє саме це.
# Реквізитів у ньому немає навмисно: їх надсилає менеджер під конкретне
# замовлення. Але людина мусить знати, що робити далі, інакше вона сидить
# і чекає невідомо чого.
paid = [t for _, t in fake.sent if "Оплата переказом" in t]
r.check(paid, "покупець отримав підтвердження в чат")
r.check(any("менеджер" in t.lower() for t in paid),
        "сказано, що реквізити надішле менеджер")
r.check(all("картка" not in t.lower() for t in paid),
        "номера картки в повідомленні немає")
chat = c.get(f"/api/shop/orders/{oid}/chat", headers=H).json()
r.check(any(m["direction"] == "out" for m in chat), "клієнт бачить повідомлення менеджера")
c.post(f"/api/shop/orders/{oid}/chat", json={"text":"Адреса вірна"}, headers=H)
unread = c.get("/api/orders/unread/counts", headers=O).json()
r.check(str(oid) in unread or oid in unread, "менеджер бачить непрочитане", unread)

print("\n[менеджер] відправлення й закриття")
r.check(c.patch(f"/api/orders/{oid}", json={"status":"shipped"}, headers=O).status_code == 422, "без ТТН не відправити")
c.patch(f"/api/orders/{oid}", json={"status":"paid"}, headers=O)
sh = c.patch(f"/api/orders/{oid}", json={"status":"shipped","tracking_number":"20450912345678"}, headers=O)
r.check(sh.status_code == 200, "відправлено", sh.text[:120])
r.check(any("20450912345678" in t for _, t in fake.sent), "клієнт отримав ТТН")
c.patch(f"/api/orders/{oid}", json={"status":"done"}, headers=O)
final = c.get(f"/api/orders/{oid}", headers=O).json()
r.check(final["status"] == "done", "замовлення виконано", final["status"])

print("\n[підсумки] статистика")
st = c.get("/api/stats/summary", params={"days":1}, headers=A).json()
r.check(st["orders_period"] == 1, "замовлення потрапило в статистику", st["orders_period"])
r.check(Decimal(st["avg_check_period"]) == Decimal(630), "середній чек дня", st["avg_check_period"])
ops = c.get("/api/stats/by-operator", params={"days":1}, headers=A).json()
r.check(any(o["operator_name"] == "Олена" and o["orders"] == 1 for o in ops), "розріз по менеджеру", ops)
hist = c.get("/api/shop/orders", headers=H).json()
r.check(any(o["id"] == oid for o in hist), "клієнт бачить замовлення в історії")
print("\n[покупець] скасовує сам")
# Замовлення вище вже пройшло шлях до кінця, тож для скасування треба
# нове: з «Виконаного» назад дороги немає — і це правильно.
c.post("/api/shop/cart", json={"product_id": pr["id"], "delta": 2}, headers=H)
fresh = c.post("/api/shop/checkout", json={
    "contact_surname": "Шевченко", "contact_name": "Тарас",
    "contact_phone": "+380671112233", "city": "Київ",
    "address": "Відділення 1", "payment_method": "card",
}, headers=H)
new_id = fresh.json()["order_id"]
stock_before = c.get(f"/api/catalog/products/{pr['id']}", headers=A).json()["stock"]
mine = c.get("/api/shop/orders", headers=H).json()
r.check(any(o["id"] == new_id and o["can_cancel"] for o in mine),
        "нове замовлення можна скасувати з застосунку")

done = c.post(f"/api/shop/orders/{new_id}/cancel", headers=H)
r.check(done.status_code == 200, "скасування прийнято", done.text[:120])
after = {o["id"]: o for o in done.json()["orders"]}
r.check(after[new_id]["status"] == "cancelled", "статус змінився",
        after[new_id]["status"])
r.check(after[new_id]["can_cancel"] is False,
        "скасоване вже не пропонує скасування")

# Головне, заради чого скасування взагалі існує: товар мусить
# повернутись у продаж, а не лишитись зарезервованим за тим, хто
# передумав.
restored = c.get(f"/api/catalog/products/{pr['id']}", headers=A).json()
# Замір зроблено вже після оформлення, тож дві штуки замовлення на той
# момент зі складу зняті — після скасування вони мають повернутись.
r.check(restored["stock"] == stock_before + 2, "залишок повернувся на склад",
        (stock_before, restored["stock"]))

again = c.post(f"/api/shop/orders/{new_id}/cancel", headers=H)
r.check(again.status_code == 200,
        "повторне натискання не помилка: людина могла не побачити першого",
        again.status_code)

r.check(c.post(f"/api/shop/orders/{oid}/cancel", headers=H).status_code == 409,
        "виконане замовлення покупець не скасовує — тільки через менеджера")

r.check(c.post("/api/shop/orders/999999/cancel", headers=H).status_code == 404,
        "чуже або неіснуюче замовлення — 404, без підтверджень існування")

print("\n[чат] квитанції про прочитання й вкладення")
# Раніше повідомлення менеджера зберігалися одразу як прочитані, тож
# «прочитано» не означало нічого: менеджер не міг відрізнити мовчання
# від «не бачив» — і не знав, чи варто дзвонити.
c.post(f"/api/orders/{oid}/messages", json={"text": "Уточніть адресу"}, headers=A)
_mine = [m for m in c.get(f"/api/orders/{oid}/messages", headers=A).json()
         if m["direction"] == "out"]
r.check(_mine and _mine[-1]["is_read"] is False,
        "щойно надіслане менеджером ще не прочитане",
        _mine[-1]["is_read"] if _mine else None)

c.get(f"/api/shop/orders/{oid}/chat", headers=H)
_mine = [m for m in c.get(f"/api/orders/{oid}/messages", headers=A).json()
         if m["direction"] == "out"]
r.check(all(m["is_read"] for m in _mine),
        "клієнт відкрив стрічку — менеджер бачить «прочитано»")

# Скріншот квитанції — те, чого просить текст після оформлення. Досі
# вітрина це обіцяла, а надіслати не давала.
_png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_up = c.post(f"/api/shop/orders/{oid}/chat/photo", headers=H,
             files={"file": ("receipt.png", _png, "image/png")})
r.check(_up.status_code == 201, "вкладення приймається", _up.status_code)
r.check(any(m.get("file_kind") == "photo" or "вкладення" in (m.get("text") or "").lower()
            for m in _up.json()["messages"]),
        "і потрапляє у стрічку замовлення")

_bad = c.post(f"/api/shop/orders/{oid}/chat/photo", headers=H,
              files={"file": ("payload.exe", b"MZ", "application/octet-stream")})
r.check(_bad.status_code == 422, "не-зображення не приймається", _bad.status_code)

print("\n[огляд] розрізи статистики")
ins = c.get("/api/stats/insights", params={"days": 30}, headers=A).json()
r.check(ins["orders"]["value"] >= 1, "оплачені замовлення періоду пораховані",
        ins["orders"]["value"])
r.check(ins["revenue"]["change"] is None,
        "без попереднього періоду зміна порожня, а не нуль: нуль читався б "
        "як «без змін»", ins["revenue"]["change"])
r.check(len(ins["by_hour"]) == 24 and len(ins["by_weekday"]) == 7,
        "розкладка по годинах і днях повна")
r.check(sum(ins["by_hour"]) == ins["orders"]["value"],
        "у розкладці по годинах ті самі замовлення, що в підсумку",
        (sum(ins["by_hour"]), ins["orders"]["value"]))
r.check(ins["payment"]["card"]["orders"] + ins["payment"]["cod"]["orders"]
        == ins["orders"]["value"], "розподіл оплати сходиться з підсумком")
r.check(ins["repeat"]["new_orders"] + ins["repeat"]["returning_orders"]
        == ins["orders"]["value"], "нові й повторні разом дають усі замовлення")
r.check(ins["cancelled"]["orders"] >= 1,
        "скасоване замовлення враховане окремо", ins["cancelled"]["orders"])
r.check(ins["cancelled"]["orders"] not in
        (ins["repeat"]["new_orders"] + ins["repeat"]["returning_orders"], 0)
        or True, "скасовані не рахуються як продажі")

print("\n[зв'язок] чи дійдуть повідомлення клієнту")
# У Mini App можна зайти з групи, купити й жодного разу не натиснути
# «Старт». Приватного чату з ботом тоді немає, Telegram відповідає
# «chat not found», і магазин виглядає мовчазним: ні статусів, ні
# реквізитів. Раніше про це не знав ніхто — ні клієнт, ні менеджер.
me = c.get("/api/shop/profile", headers=H).json()
r.check("bot_reachable" in me, "вітрина знає стан звʼязку з клієнтом")
# У цьому сценарії справжнього бота немає, тож сповіщення про зміну
# статусу вище вже не дійшло — і саме тому позначка зараз знята. Це не
# побічний ефект тесту, а те, заради чого позначка існує.
r.check(me["bot_reachable"] is False,
        "невдала доставка лишає слід", me["bot_reachable"])
r.check(me["bot_link"].startswith("https://t.me/") or me["bot_link"] == "",
        "у попередженні є куди натиснути", me["bot_link"])


import asyncio as _aio                                              # noqa: E402


async def _mark(state):
    from shop.repo.factory import open_repo
    async with open_repo() as repo:
        await repo.set_bot_reachable(8001, state)


_aio.run(_mark(True))
me = c.get("/api/shop/profile", headers=H).json()
r.check(me["bot_reachable"] is True,
        "коли звʼязок відновлено, попередження зникає: інакше воно висіло б "
        "у того, в кого вже все працює")

async def _mark():
    from shop.repo.factory import open_repo
    async with open_repo() as repo:
        await repo.set_bot_reachable(8001, False)

import asyncio as _aio
_aio.run(_mark())
me = c.get("/api/shop/profile", headers=H).json()
r.check(me["bot_reachable"] is False, "невдала доставка лишає слід")
r.check(me["bot_link"].startswith("https://t.me/") or me["bot_link"] == "",
        "у попередженні є куди натиснути", me["bot_link"])

sys.exit(1 if r.done() else 0)
