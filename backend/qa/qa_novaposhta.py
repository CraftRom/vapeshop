"""НОВА ПОШТА: довідник населених пунктів і відділень.

Живого API тут немає й бути не може: домен перевізника недоступний зі
складального середовища, а ганяти чужий сервіс на кожному прогоні тестів
означало б залежати від його доступності. Тому весь набір працює на
підставних відповідях у тій формі, яку описує документація.

Що це перевіряє: нашу логіку — кеш, сортування, відсів, обробку відмов,
відрив ключа від вітрини. Чого не перевіряє: що ми правильно вгадали
назви полів у відповіді. Це підтверджується лише справжнім ключем, і
саме тому перше після розгортання — знайти в панелі своє місто.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, "/tmp")
os.environ.update(BOT_TOKEN="777001:TESTTOKEN", JWT_SECRET="t" * 32,
                  DASHBOARD_LOGIN="root", DASHBOARD_PASSWORD="Pa$$w0rd123",
                  ELFAR_DATA_ROOT=tempfile.mkdtemp(prefix="qa_np_"),
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_np.db")

from qa_common import Report, boot, init_data                    # noqa: E402

r = Report("НОВА ПОШТА")

import httpx                                                     # noqa: E402
from shop.services import novaposhta as np                       # noqa: E402

app, Session, fake = boot("/tmp/qa_np.db")

KEY = "0123456789abcdef0123456789abcdef"

# --------------------------------------------------------- підставні дані

CITY_ROW = {
    "TotalCount": "3",
    "Addresses": [
        {"Present": "м. Дніпро, Дніпропетровська обл.", "Warehouses": 180,
         "MainDescription": "Дніпро", "Area": "Дніпропетровська", "Region": "",
         "SettlementTypeCode": "м.",
         "Ref": "settlement-dnipro", "DeliveryCity": "city-dnipro"},
        # Село без жодного відділення: у переліку його бути не повинно —
        # вибравши таке, людина впирається в порожній список відділень.
        {"Present": "с. Дніпрове, Черкаська обл.", "Warehouses": 0,
         "MainDescription": "Дніпрове", "Area": "Черкаська", "Region": "Золотоніський",
         "Ref": "settlement-dniprove", "DeliveryCity": ""},
        # Село з відділенням, але без свого CityRef — саме той випадок,
        # заради якого тримаємо settlement_ref окремо.
        {"Present": "с. Дніпряни, Херсонська обл.", "Warehouses": 1,
         "MainDescription": "Дніпряни", "Area": "Херсонська", "Region": "Новокаховський",
         "Ref": "settlement-dnipryany", "DeliveryCity": ""},
    ],
}

WAREHOUSE_ROWS = [
    {"Ref": "wh-100", "Number": "100", "Description": "Відділення №100: вул. Широка, 1",
     "ShortAddress": "Дніпро, Широка, 1", "CategoryOfWarehouse": "Branch",
     "CityRef": "city-dnipro"},
    {"Ref": "wh-7", "Number": "7", "Description": "Відділення №7: вул. Січова, 12",
     "ShortAddress": "Дніпро, Січова, 12", "CategoryOfWarehouse": "Branch",
     "CityRef": "city-dnipro"},
    {"Ref": "wh-pm3", "Number": "3", "Description": "Поштомат №3: вул. Січова, 20",
     "ShortAddress": "Дніпро, Січова, 20", "CategoryOfWarehouse": "Postomat",
     "CityRef": "city-dnipro"},
]

calls: list[dict] = []
response_queue: list = []


async def fake_post(payload):
    """Підставний перевізник. Записує запити — щоб перевіряти не лише
    результат, а й те, скільки разів ми пішли назовні."""
    calls.append(payload)
    if response_queue:
        nxt = response_queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt
    method = payload.get("calledMethod")
    if method == "searchSettlements":
        return {"success": True, "data": [CITY_ROW]}
    if method == "getWarehouses":
        return {"success": True, "data": WAREHOUSE_ROWS}
    return {"success": False, "errors": ["Невідомий метод"]}


np._post = fake_post


def reset():
    calls.clear()
    response_queue.clear()
    np.reset_cache()


# ------------------------------------------------------------- сценарій


async def scenario():
    print("\n--- населені пункти ---")
    reset()
    found = await np.search_settlements(KEY, "Дніпро")
    names = [s.name for s in found]
    r.check(names == ["Дніпро", "Дніпряни"],
            "пункти без жодного відділення відсіяні", names)
    r.check(found[0].ref == "city-dnipro",
            "CityRef береться з DeliveryCity", found[0].ref)
    r.check(found[0].settlement_ref == "settlement-dnipro",
            "код населеного пункту зберігається окремо", found[0].settlement_ref)
    r.check(found[1].ref == "" and found[1].settlement_ref == "settlement-dnipryany",
            "у села без CityRef лишається лише код населеного пункту")
    r.check("Дніпро" in found[0].label and "обл" in found[0].label,
            "підпис містить область — інакше однойменні села не розрізнити",
            found[0].label)
    r.check(found[0].warehouses == 180, "кількість відділень збережена",
            found[0].warehouses)

    print("\n--- запит іде з ключем і в правильний метод ---")
    r.check(calls[0]["apiKey"] == KEY, "ключ підставляється в запит")
    r.check(calls[0]["modelName"] == "Address"
            and calls[0]["calledMethod"] == "searchSettlements",
            "викликається searchSettlements", calls[0].get("calledMethod"))

    print("\n--- короткий запит не турбує перевізника ---")
    reset()
    r.check(await np.search_settlements(KEY, "Д") == [],
            "один символ — порожньо, без звернення")
    r.check(not calls, "жодного запиту назовні", len(calls))

    print("\n--- кеш ---")
    reset()
    await np.search_settlements(KEY, "Дніпро")
    await np.search_settlements(KEY, "Дніпро")
    await np.search_settlements(KEY, "дніпро")
    r.check(len(calls) == 1,
            "повторний набір того ж міста не йде до перевізника", len(calls))

    print("\n--- відділення ---")
    reset()
    picked = await np.warehouses(KEY, "city-dnipro")
    numbers = [w.number for w in picked]
    r.check(numbers == [3, 7, 100],
            "відділення сортуються за номером, а не за назвою", numbers)
    r.check(picked[0].is_postomat and not picked[1].is_postomat,
            "поштомат позначений окремо")
    r.check(calls[0]["methodProperties"] == {"CityRef": "city-dnipro"},
            "місто шукається за CityRef", calls[0]["methodProperties"])

    print("\n--- село без CityRef ---")
    reset()
    await np.warehouses(KEY, "", "settlement-dnipryany")
    r.check(calls[0]["methodProperties"] == {"SettlementRef": "settlement-dnipryany"},
            "село шукається за SettlementRef", calls[0]["methodProperties"])
    r.check("CityRef" not in calls[0]["methodProperties"],
            "обидва ключі одразу не надсилаються — перевізник відповів би порожньо")

    print("\n--- пошук усередині міста ---")
    reset()
    only7 = await np.warehouses(KEY, "city-dnipro", query="7")
    r.check([w.number for w in only7] == [7], "фільтр за номером",
            [w.number for w in only7])
    by_street = await np.warehouses(KEY, "city-dnipro", query="широка")
    r.check([w.number for w in by_street] == [100], "фільтр за вулицею",
            [w.number for w in by_street])
    r.check(len(calls) == 1,
            "перелік міста тягнеться один раз, фільтр рахується в нас", len(calls))

    print("\n--- зміна ключа знецінює кеш ---")
    reset()
    await np.warehouses(KEY, "city-dnipro")
    np.reset_cache()
    await np.warehouses(KEY, "city-dnipro")
    r.check(len(calls) == 2, "після скидання кешу дані беруться заново", len(calls))

    print("\n--- відмови перевізника ---")
    reset()
    response_queue.append({"success": False, "errors": ["API key expired"]})
    try:
        await np.search_settlements(KEY, "Львів")
        r.check(False, "відмова перевізника стає помилкою")
    except np.NovaPoshtaError as exc:
        r.check("API key expired" in str(exc),
                "текст відмови зберігається — «ключ прострочено» і «ліміт» "
                "вимагають різних дій", str(exc))

    reset()
    response_queue.append(httpx.ConnectError("мережа лягла"))
    try:
        await np.warehouses(KEY, "city-dnipro")
        r.check(False, "мережева помилка стає зрозумілою")
    except np.NovaPoshtaError as exc:
        r.check("недоступний" in str(exc), "мережева помилка не витікає трейсбеком",
                str(exc))

    reset()
    try:
        await np.search_settlements("", "Львів")
        r.check(False, "порожній ключ зупиняється до запиту")
    except np.NovaPoshtaError as exc:
        r.check(not calls, "без ключа запит назовні не йде")
        r.check("Ключ" in str(exc), "сказано, чого бракує", str(exc))

    print("\n--- точки вітрини ---")
    reset()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        head = init_data(70701)
        await client.post("/api/shop/age-confirm", headers=head)

        # Ключа в налаштуваннях ще немає
        resp = await client.get("/api/shop/delivery/cities?q=Дніпро", headers=head)
        r.check(resp.status_code == 503,
                "без ключа довідник відповідає 503, а не 500", resp.status_code)

        cfg = (await client.get("/api/shop/config", headers=head)).json()
        r.check(cfg.get("novaposhta_enabled") is False,
                "вітрина знає, що вибору відділень немає", cfg.get("novaposhta_enabled"))

        from api.auth import create_token
        from shop.entities import OperatorRole

        token = {"Authorization": f"Bearer {create_token('root', OperatorRole.SYSADMIN, 0, 'Root')}"}
        saved = await client.put("/api/settings",
                                 json={"novaposhta_api_key": KEY}, headers=token)
        r.check(saved.status_code == 200, "ключ зберігається з панелі", saved.status_code)
        r.check("novaposhta_api_key" not in saved.text,
                "ключ не повертається у відповіді")
        r.check(saved.json().get("novaposhta_connected") is True,
                "панель бачить ознаку «підключено»")

        cities = await client.get("/api/shop/delivery/cities?q=Дніпро", headers=head)
        items = cities.json()["items"]
        r.check(cities.status_code == 200 and len(items) == 2,
                "вітрина отримує перелік міст", cities.status_code)
        r.check(all("apiKey" not in str(i) for i in items),
                "ключ не просочується у відповідь вітрині")

        whs = await client.get(
            "/api/shop/delivery/warehouses?city_ref=city-dnipro", headers=head)
        r.check([w["number"] for w in whs.json()["items"]] == [3, 7, 100],
                "вітрина отримує відділення по порядку")

        response_queue.append({"success": False, "errors": ["Ліміт запитів"]})
        np.reset_cache()
        broken = await client.get("/api/shop/delivery/cities?q=Одеса", headers=head)
        r.check(broken.status_code == 502,
                "відмова перевізника не виглядає як наша поломка", broken.status_code)


asyncio.run(scenario())
sys.exit(1 if r.done() else 0)
