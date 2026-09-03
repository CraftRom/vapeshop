"""Довідник Нової пошти: населені пункти й відділення.

Звертаємось зі свого сервера, а не з вітрини. Причин дві. Ключ приватний —
ним створюють накладні від нашого імені, а в браузері він видимий кожному,
хто відкриє інструменти розробника. І політика безпеки вітрини дозволяє
запити лише на власний домен, тож прямий виклик просто не пішов би.

Відповіді кешуються на півдоби. Людина, набираючи «Дніпро», шле запит на
кожну літеру; без кешу одне місто коштувало б шести звернень до перевізника.
Довідник міняється рідко — нове відділення зʼявляється не щохвилини.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

API_URL = "https://api.novaposhta.ua/v2.0/json/"

# Півдоби. Довідник оновлюється рідко, а помилитись тут дешево: найгірше,
# що станеться, — щойно відкрите відділення зʼявиться в списку за 12 годин.
CACHE_TTL_SECONDS = 12 * 3600
# Скільки різних запитів тримаємо. Кожен набраний рядок — окремий ключ,
# тож без межі кеш ріс би разом із фантазією покупців.
CACHE_MAX_ENTRIES = 512

CITY_LIMIT = 20
WAREHOUSE_LIMIT = 50
REQUEST_TIMEOUT = 8.0


class NovaPoshtaError(RuntimeError):
    """Довідник не відповів або відмовив."""


@dataclass
class Settlement:
    """Населений пункт.

    ref — те, що йде в getWarehouses як CityRef. Для сіл і селищ його може
    не бути зовсім; тоді відділення шукаються за settlement_ref. Тримаємо
    обидва, бо вгадати наперед, який знадобиться, неможливо.
    """

    ref: str
    settlement_ref: str
    name: str
    area: str
    region: str
    label: str
    warehouses: int


@dataclass
class Price:
    """Попередній розрахунок доставки.

    Саме попередній, і це не обережність у формулюваннях. Перевізник
    рахує за фактичною вагою й габаритами, а їх ніхто не знає, поки
    посилку не зважать на відділенні. Ми підставляємо припущену вагу з
    налаштувань — тож число показуємо як орієнтир, а не як ціну.
    """

    cost: int
    redelivery: int
    weight: float


@dataclass
class Warehouse:
    ref: str
    number: int
    label: str
    short: str
    is_postomat: bool


# ------------------------------------------------------------------- кеш

_cache: dict[str, tuple[float, list]] = {}


def reset_cache() -> None:
    """Скидає кеш. Викликається при зміні ключа в налаштуваннях.

    Без цього магазин ще півдоби працював би на відповідях, отриманих
    старим ключем, і людина, яка щойно вписала новий, вирішила б, що він
    не застосувався.
    """
    _cache.clear()


def _cached(key: str):
    found = _cache.get(key)
    if not found:
        return None
    stamp, value = found
    if time.monotonic() - stamp > CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return value


def _store(key: str, value: list) -> None:
    if len(_cache) >= CACHE_MAX_ENTRIES:
        # Викидаємо найстаріший запис, а не весь кеш: скидати все через
        # переповнення означало б віддати перевізнику й ті запити, які
        # щойно приходили і прийдуть знову.
        oldest = min(_cache, key=lambda k: _cache[k][0])
        _cache.pop(oldest, None)
    _cache[key] = (time.monotonic(), value)


# --------------------------------------------------------------- виклики


async def _post(payload: dict) -> dict:
    """Один HTTP-запит до довідника. Винесено окремо — так набір
    перевірок підставляє свої відповіді, не чіпаючи логіки навколо."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(API_URL, json=payload)
        response.raise_for_status()
        return response.json()


async def _call(api_key: str, model: str, method: str, properties: dict) -> list[dict]:
    if not api_key:
        raise NovaPoshtaError("Ключ API Нової пошти не заданий у налаштуваннях")

    payload = {
        "apiKey": api_key,
        "modelName": model,
        "calledMethod": method,
        "methodProperties": properties,
    }
    try:
        data = await _post(payload)
    except httpx.HTTPError as exc:
        # Мережа лягла або перевізник віддав 5xx. Для покупця це не
        # відрізняється від «нічого не знайшлося», але в журналі має
        # лишитися саме причина, інакше шукатимемо помилку в себе.
        log.warning("novaposhta.unreachable %s.%s: %s", model, method, exc)
        raise NovaPoshtaError("Довідник Нової пошти зараз недоступний") from exc

    if not isinstance(data, dict) or not data.get("success"):
        reasons = []
        for field in ("errors", "warnings", "info"):
            value = (data or {}).get(field)
            if isinstance(value, list):
                reasons += [str(v) for v in value if v]
            elif isinstance(value, dict):
                reasons += [str(v) for v in value.values() if v]
        detail = "; ".join(reasons) or "невідома причина"
        # Найчастіша причина — прострочений або чужий ключ. Пишемо саме
        # текст перевізника: він відрізняє «ключ недійсний» від
        # «перевищено ліміт», а це різні дії адміністратора.
        log.warning("novaposhta.rejected %s.%s: %s", model, method, detail)
        raise NovaPoshtaError(f"Нова пошта відмовила: {detail}")

    result = data.get("data")
    return result if isinstance(result, list) else []


# ------------------------------------------------------------- довідники


def _int(value) -> int:
    try:
        return int(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0


async def search_settlements(api_key: str, query: str,
                             limit: int = CITY_LIMIT) -> list[Settlement]:
    """Населені пункти за початком назви.

    Пункти без жодного відділення відсіюємо: вибрати такий означає зайти
    в глухий кут — список відділень буде порожній, і людина вирішить, що
    зламалась форма.
    """
    query = (query or "").strip()
    if len(query) < 2:
        return []

    key = f"settlements:{query.lower()}:{limit}"
    hit = _cached(key)
    if hit is not None:
        return hit

    rows = await _call(api_key, "Address", "searchSettlements", {
        "CityName": query, "Limit": str(limit), "Page": "1",
    })
    # Відповідь приходить обгорнутою: список із одного запису, всередині
    # якого лежить сам перелік адрес.
    addresses = []
    for row in rows:
        addresses += row.get("Addresses") or []

    found = []
    for row in addresses:
        count = _int(row.get("Warehouses"))
        if count <= 0:
            continue
        name = (row.get("MainDescription") or "").strip()
        area = (row.get("Area") or "").strip()
        region = (row.get("Region") or "").strip()
        found.append(Settlement(
            ref=(row.get("DeliveryCity") or "").strip(),
            settlement_ref=(row.get("Ref") or "").strip(),
            name=name,
            area=area,
            region=region,
            # Present від перевізника вже містить область і район —
            # беремо його, а свій рядок складаємо лише якщо його немає.
            label=(row.get("Present") or "").strip() or ", ".join(
                p for p in (name, region and f"{region} р-н", area and f"{area} обл.") if p
            ),
            warehouses=count,
        ))

    _store(key, found)
    return found


async def warehouses(api_key: str, city_ref: str, settlement_ref: str = "",
                     query: str = "", limit: int = WAREHOUSE_LIMIT) -> list[Warehouse]:
    """Відділення й поштомати населеного пункту.

    Перелік для міста тягнемо цілком і кладемо в кеш, а фільтр і межу
    застосовуємо вже до нього. Так сортування за номером правильне:
    попроси перевізника про перші пʼятдесят — і №100 може приїхати
    раніше за №7, бо порядок у відповіді не наш.
    """
    city_ref = (city_ref or "").strip()
    settlement_ref = (settlement_ref or "").strip()
    if not city_ref and not settlement_ref:
        return []

    key = f"warehouses:{city_ref or settlement_ref}"
    everything = _cached(key)
    if everything is None:
        # CityRef — для міст, SettlementRef — для сіл, у яких свого
        # CityRef немає. Питати обома одразу не можна: перевізник
        # відповідає порожнім переліком.
        props = {"CityRef": city_ref} if city_ref else {"SettlementRef": settlement_ref}
        rows = await _call(api_key, "Address", "getWarehouses", props)

        everything = []
        for row in rows:
            description = (row.get("Description") or "").strip()
            category = (row.get("CategoryOfWarehouse") or "").strip()
            everything.append(Warehouse(
                ref=(row.get("Ref") or "").strip(),
                number=_int(row.get("Number")),
                label=description,
                short=(row.get("ShortAddress") or "").strip(),
                # Поштомат позначаємо окремо: у нього не приймають
                # накладений платіж і не кладуть великі посилки.
                is_postomat=category == "Postomat" or "оштомат" in description,
            ))
        everything.sort(key=lambda w: (w.number == 0, w.number, w.label))
        _store(key, everything)

    needle = (query or "").strip().lower()
    if needle:
        picked = [w for w in everything
                  if needle in w.label.lower() or needle in w.short.lower()
                  or needle == str(w.number)]
    else:
        picked = everything
    return picked[:limit]


# ----------------------------------------------------------- розрахунок


async def city_ref_by_name(api_key: str, name: str) -> str:
    """Код міста відправлення за назвою з налаштувань.

    Адміністратор вписує «Хмельницький», а не набір із тридцяти шести
    символів: код відправника нікого не цікавить, і помилитись у ньому
    легше, ніж у назві міста.
    """
    found = await search_settlements(api_key, name, limit=1)
    return found[0].ref or found[0].settlement_ref if found else ""


async def document_price(api_key: str, sender_ref: str, recipient_ref: str,
                         to_door: bool, declared: float, weight: float,
                         cash_on_delivery: float = 0) -> Price:
    """Скільки перевізник візьме за таку посилку.

    Оголошена вартість впливає на ціну — страхування рахується від неї,
    тож підставляємо суму замовлення, а не нуль.
    """
    props = {
        "CitySender": sender_ref,
        "CityRecipient": recipient_ref,
        "ServiceType": "WarehouseDoors" if to_door else "WarehouseWarehouse",
        "CargoType": "Cargo",
        "Cost": str(int(declared)),
        "Weight": str(weight),
        "SeatsAmount": "1",
    }
    if cash_on_delivery > 0:
        # Комісія за переказ грошей назад продавцеві. Її платить покупець
        # окремо від доставки, і не показати її означає здивувати людину
        # на відділенні.
        props["RedeliveryCalculate"] = {
            "CargoType": "Money", "Amount": str(int(cash_on_delivery)),
        }

    key = f"price:{sender_ref}:{recipient_ref}:{int(to_door)}:{int(declared)}:{weight}:{int(cash_on_delivery)}"
    hit = _cached(key)
    if hit is not None:
        return hit[0]

    rows = await _call(api_key, "InternetDocument", "getDocumentPrice", props)
    if not rows:
        raise NovaPoshtaError("Перевізник не повернув розрахунку")

    row = rows[0]
    price = Price(
        cost=_int(row.get("Cost")),
        redelivery=_int(row.get("CostRedelivery")),
        weight=weight,
    )
    _store(key, [price])
    return price
