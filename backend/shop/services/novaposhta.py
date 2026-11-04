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

import asyncio
import logging
import time
import hashlib
from urllib.parse import urljoin, urlsplit
from weakref import WeakValueDictionary
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

API_URL = "https://api.novaposhta.ua/v2.0/json/"

# Півдоби. Довідник оновлюється рідко, а помилитись тут дешево: найгірше,
# що станеться, — щойно відкрите відділення зʼявиться в списку за 12 годин.
CACHE_TTL_SECONDS = 12 * 3600
# Під час короткого outage краще показати вчорашній довідник, ніж змусити
# кожного покупця переходити на ручний ввід. Stale використовується тільки
# якщо свіжий запит до провайдера справді впав.
STALE_CACHE_SECONDS = 72 * 3600
OUTAGE_COOLDOWN_SECONDS = 20
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
_locks = WeakValueDictionary()
_provider_unavailable_until: dict[str, float] = {}


def reset_cache() -> None:
    """Скидає кеш. Викликається при зміні ключа в налаштуваннях.

    Без цього магазин ще півдоби працював би на відповідях, отриманих
    старим ключем, і людина, яка щойно вписала новий, вирішила б, що він
    не застосувався.
    """
    _cache.clear()
    _locks.clear()
    _provider_unavailable_until.clear()


def _cached(key: str, *, allow_stale: bool = False):
    found = _cache.get(key)
    if not found:
        return None
    stamp, value = found
    age = time.monotonic() - stamp
    if age <= CACHE_TTL_SECONDS:
        return value
    if allow_stale and age <= STALE_CACHE_SECONDS:
        return value
    if age > STALE_CACHE_SECONDS:
        _cache.pop(key, None)
    return None


def _key_lock(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        # Weak references release idle locks while active readers keep theirs.
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


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
    # The provider may redirect with 303; implicit HTTP redirect handling
    # would turn the original POST into GET and discard its JSON body.
    # Preserve the JSON POST across bounded, same-origin redirects. Never
    # forward an apiKey to an arbitrary redirect target or downgrade HTTPS.
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
        url = API_URL
        for _ in range(3):
            response = await client.post(url, json=payload)
            if response.status_code not in {301, 302, 303, 307, 308}:
                response.raise_for_status()
                try:
                    return response.json()
                except ValueError:
                    raise NovaPoshtaError('Нова пошта повернула нечитабельну JSON-відповідь') from None
            target = urljoin(url, response.headers.get('Location', ''))
            parsed = urlsplit(target)
            origin = urlsplit(API_URL)
            if (not response.headers.get('Location') or parsed.scheme != 'https'
                    or parsed.netloc != origin.netloc or parsed.username or parsed.password):
                raise NovaPoshtaError('Нова пошта повернула неприпустиме перенаправлення')
            url = target
        raise NovaPoshtaError('Нова пошта повернула забагато перенаправлень')


def _scope(api_key):
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


async def _call(api_key: str, model: str, method: str, properties: dict) -> list[dict]:
    if not api_key:
        raise NovaPoshtaError("Ключ API Нової пошти не заданий у налаштуваннях")
    scope = _scope(api_key)
    if time.monotonic() < _provider_unavailable_until.get(scope, 0):
        raise NovaPoshtaError("Довідник Нової пошти тимчасово недоступний")

    payload = {
        "apiKey": api_key,
        "modelName": model,
        "calledMethod": method,
        "methodProperties": properties,
    }
    try:
        data = await _post(payload)
        _provider_unavailable_until.pop(scope, None)
    except (httpx.HTTPError, NovaPoshtaError) as exc:
        delay = OUTAGE_COOLDOWN_SECONDS
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
            from shop.http_utils import retry_after_seconds
            delay = max(delay, retry_after_seconds(exc.response.headers.get('Retry-After'), default=60))
        _provider_unavailable_until[scope] = time.monotonic() + delay
        # Мережа лягла або перевізник віддав 5xx. Для покупця це не
        # відрізняється від «нічого не знайшлося», але в журналі має
        # лишитися саме причина, інакше шукатимемо помилку в себе.
        log.warning("novaposhta.unreachable %s.%s: %s", model, method, type(exc).__name__)
        raise NovaPoshtaError("Довідник Нової пошти зараз недоступний") from exc

    if not isinstance(data, dict):
        raise NovaPoshtaError('Нова пошта повернула некоректну структуру відповіді')
    if data.get("success") is not True:
        reasons = []
        for field in ("errors", "warnings", "info"):
            value = (data or {}).get(field)
            if isinstance(value, list):
                reasons += [str(v) for v in value if v]
            elif isinstance(value, dict):
                reasons += [str(v) for v in value.values() if v]
        detail = ('; '.join(reasons) or 'невідома причина').replace(api_key, '[redacted]')[:500]
        # Найчастіша причина — прострочений або чужий ключ. Пишемо саме
        # текст перевізника: він відрізняє «ключ недійсний» від
        # «перевищено ліміт», а це різні дії адміністратора.
        log.warning("novaposhta.rejected %s.%s: %s", model, method, detail)
        raise NovaPoshtaError(f"Нова пошта відмовила: {detail}")

    result = data.get('data')
    if not isinstance(result, list):
        raise NovaPoshtaError('Нова пошта не повернула список даних')
    return [row for row in result if isinstance(row, dict)]


# ------------------------------------------------------------- довідники


def _int(value) -> int:
    try:
        return int(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0


async def search_settlements(api_key: str, query: str,
                             limit: int = CITY_LIMIT, page: int = 1,
                             return_meta: bool = False):
    """Посторінковий пошук населених пунктів, включно з однойменними селами.

    За замовчуванням повертає список, щоб старі внутрішні виклики й бот
    залишилися сумісними. Для WebView повертаємо items/has_more/total.
    """
    query = (query or "").strip()[:120]
    limit = max(1, min(int(limit), 50))
    page = max(1, min(int(page), 1000))
    empty = {"items": [], "has_more": False, "total": 0}
    if len(query) < 2:
        return empty if return_meta else []

    key = f"{_scope(api_key)}:settlements:{query.casefold()}:{limit}:{page}"
    cached = _cached(key)
    if cached is None:
        async with _key_lock(key):
            cached = _cached(key)
            if cached is None:
                try:
                    rows = await _call(api_key, "Address", "searchSettlements", {
                        "CityName": query, "Limit": str(limit), "Page": str(page),
                    })
                except NovaPoshtaError:
                    cached = _cached(key, allow_stale=True)
                    if cached is None:
                        raise
                    log.info("novaposhta.stale_cache settlements page=%s", page)
                else:
                    addresses = []
                    total = 0
                    for row in rows:
                        if isinstance(row.get("Addresses"), list):
                            addresses.extend(x for x in row["Addresses"] if isinstance(x, dict))
                        total = max(total, _int(row.get("TotalCount")))
                    found = []
                    for row in addresses:
                        count = _int(row.get("Warehouses"))
                        if count <= 0:
                            continue
                        name = str(row.get("MainDescription") or "").strip()
                        area = str(row.get("Area") or "").strip()
                        region = str(row.get("Region") or "").strip()
                        ref = str(row.get("DeliveryCity") or "").strip()
                        settlement_ref = str(row.get("SettlementRef") or row.get("Ref") or "").strip()
                        if not name or not (ref or settlement_ref):
                            continue
                        found.append(Settlement(
                            ref=ref, settlement_ref=settlement_ref,
                            name=name, area=area, region=region,
                            label=str(row.get("Present") or "").strip() or ", ".join(
                                part for part in (name, region and f"{region} р-н", area and f"{area} обл.") if part
                            ), warehouses=count,
                        ))
                    has_more = page * limit < total if total else len(addresses) >= limit
                    cached = {"items": found, "has_more": has_more, "total": total}
                    _store(key, cached)
    return cached if return_meta else cached["items"]


def _warehouse_row(row: dict) -> Warehouse | None:
    ref = str(row.get("Ref") or "").strip()
    if not ref:
        return None
    description = str(row.get("Description") or "").strip()
    category = str(row.get("CategoryOfWarehouse") or "").strip().casefold()
    return Warehouse(
        ref=ref, number=_int(row.get("Number")), label=description,
        short=str(row.get("ShortAddress") or "").strip(),
        is_postomat=category == "postomat" or "оштомат" in description.casefold(),
    )


async def warehouses(api_key: str, city_ref: str, settlement_ref: str = "",
                     query: str = "", limit: int = WAREHOUSE_LIMIT,
                     page: int = 1, return_meta: bool = False):
    """Пошук у провайдера: номер/вулиця і сторінки, а не перші 50 локально.

    Номер перевіряється додатковим WarehouseId, коли звичайний пошук
    нічого не знайшов. Якщо CityRef не дає результату, пробуємо
    SettlementRef. Помилка мережі не перетворюється на порожній список.
    """
    city_ref = (city_ref or "").strip()
    settlement_ref = (settlement_ref or "").strip()
    query = (query or "").strip()[:120]
    page = max(1, min(int(page), 1000))
    limit = max(1, min(int(limit), 100))
    empty = {"items": [], "has_more": False}
    if not city_ref and not settlement_ref:
        return empty if return_meta else []

    cache_key = f"{_scope(api_key)}:wh:{city_ref}:{settlement_ref}:{query.casefold()}:{page}:{limit}"
    result = _cached(cache_key)
    if result is None:
        async with _key_lock(cache_key):
            result = _cached(cache_key)
            if result is None:
                base_refs = ([{"CityRef": city_ref}] if city_ref else [])
                if settlement_ref:
                    base_refs.append({"SettlementRef": settlement_ref})
                # Provider filtering is essential in cities with thousands of points.
                # Never silently truncate the unfiltered result before searching.
                best_rows = []
                last_error = None
                for ref_props in base_refs:
                    variants = [{"FindByString": query}] if query else [{}]
                    if query.isdecimal():
                        variants.append({"WarehouseId": query})
                    for variant in variants:
                        props = {**ref_props, **variant, "Page": str(page), "Limit": str(limit)}
                        try:
                            rows = await _call(api_key, "Address", "getWarehouses", props)
                        except NovaPoshtaError as exc:
                            last_error = exc
                            # Do not try another query kind after transport failure;
                            # keep the provider failure visible to the buyer.
                            break
                        if query:
                            needle = query.casefold()
                            rows = [w for w in rows if (
                                (query.isdecimal() and _int(w.get("Number")) == int(query))
                                or (not query.isdecimal() and (needle in str(w.get("Description") or "").casefold()
                                     or needle in str(w.get("ShortAddress") or "").casefold()))
                            )]
                        if rows:
                            best_rows = rows
                            break
                    if best_rows or last_error:
                        break
                if last_error is not None:
                    result = _cached(cache_key, allow_stale=True)
                    if result is None:
                        raise last_error
                    log.info("novaposhta.stale_cache warehouses page=%s", page)
                else:
                    found = [w for row in best_rows if (w := _warehouse_row(row)) is not None]
                    unique = {w.ref: w for w in found}
                    items = sorted(unique.values(), key=lambda w: (w.number == 0, w.number, w.label))
                    result = {"items": items, "has_more": len(best_rows) >= limit}
                    _store(cache_key, result)
    return result if return_meta else result["items"]


async def search_streets(api_key: str, settlement_ref: str, query: str,
                         page: int = 1, limit: int = 20) -> dict:
    """Необов'язкові підказки кур'єрських вулиць (ручне введення дозволено)."""
    settlement_ref = (settlement_ref or "").strip()
    query = (query or "").strip()[:120]
    page = max(1, min(int(page), 1000))
    if not settlement_ref or len(query) < 2:
        return {"items": [], "has_more": False}
    key = f"{_scope(api_key)}:streets:{settlement_ref}:{query.casefold()}:{page}:{limit}"
    cached = _cached(key)
    if cached is not None:
        return cached
    async with _key_lock(key):
        cached = _cached(key)
        if cached is not None:
            return cached
        try:
            rows = await _call(api_key, "Address", "searchSettlementStreets", {
                "SettlementRef": settlement_ref, "StreetName": query,
                "Page": str(page), "Limit": str(limit),
            })
        except NovaPoshtaError:
            stale = _cached(key, allow_stale=True)
            if stale is not None:
                return stale
            raise
        addresses = []
        total = 0
        for row in rows:
            addresses.extend(x for x in (row.get("Addresses") or []) if isinstance(x, dict))
            total = max(total, _int(row.get("TotalCount")))
        result = {"items": [
            {"ref": str(x.get("Ref") or ""),
             "name": str(x.get("SettlementStreetDescription") or x.get("Description") or x.get("Present") or "").strip()}
            for x in addresses if x.get("SettlementStreetDescription") or x.get("Description") or x.get("Present")
        ], "has_more": page * limit < total if total else len(addresses) >= limit}
        _store(key, result)
        return result


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
        # Перевізник не приймає нульову оголошену вартість, а нуль сюди
        # потрапляє легко: кошик спорожнили в іншій вкладці, знижка
        # зʼїла суму. Одна гривня — достатньо, щоб розрахунок пройшов.
        "Cost": str(max(int(declared), 1)),
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

    key = f"{_scope(api_key)}:price:{sender_ref}:{recipient_ref}:{int(to_door)}:{int(declared)}:{weight}:{int(cash_on_delivery)}"
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
