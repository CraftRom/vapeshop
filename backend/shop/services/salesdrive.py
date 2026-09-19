"""Інтеграція з SalesDrive: заявки, статуси, накладні.

Замовлення одне. SalesDrive не отримує «копію замовлення», яку далі веде
окремо: заявка в CRM — це те саме замовлення Elfar, повʼязане за
externalId (номер замовлення) і crm_id (номер заявки). Зміни ходять в
обидва боки через ті самі правила (shop/services/order_workflow.py):

  Elfar → SalesDrive
    нове замовлення        POST /handler/            (створення заявки)
    статус, накладна       POST /api/order/update/   (за externalId)
  SalesDrive → Elfar
    вебхук new_order / status_change → статус і ТТН через order_workflow

Черга. Кожна зміна ставить замовленню crm_state=pending тим самим записом,
що й сама зміна. Далі відправка намагається пройти одразу (push_soon), а
планувальник доганяє все, що не пройшло: SalesDrive недоступний, ключ
змінили, мережа впала. Втратити зміну неможливо — вона або в CRM, або в
черзі з причиною в crm_error, яку видно в панелі.

Дублі. Найнебезпечніший збій — таймаут на створенні: заявка в CRM могла
зʼявитись, а відповіді ми не отримали. Повторне створення дало б дві
заявки. Тому такий стан позначається uncertain, і наступна спроба спершу
оновлює заявку за externalId; створює нову, лише якщо оновлювати нічого.

Джерело контракту — офіційна база знань SalesDrive (Swagger у кабінеті
недоступний без облікового запису): order-update-api, order-list, webhook.
Значення статусів, способів оплати й доставки в кожному акаунті свої, тому
відповідності задаються в налаштуваннях, а не зашиті в коді.
"""
from __future__ import annotations

import asyncio
import hmac
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from shop.entities import Order, OrderStatus
from shop.services import shipment

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20.0
DICTIONARY_TTL_SECONDS = 10 * 60
ORDER_PULL_MIN_AGE_SECONDS = 90
READ_RETRY_DELAY_SECONDS = 0.35
# Після стількох невдалих спроб планувальник зупиняється: помилка, яка не
# минає за добу повторів (зіпсований ключ, видалена форма), сама не мине.
# Далі — кнопка «Повторити» в панелі після виправлення.
MAX_ATTEMPTS = 12

STATE_PENDING = "pending"
STATE_CREATING = "creating"
STATE_UNCERTAIN = "uncertain"
STATE_SYNCED = "synced"
STATE_FAILED = "failed"
RETRY_STATES = (STATE_PENDING, STATE_UNCERTAIN, STATE_FAILED)

STATUS_KEYS = tuple(s.value for s in OrderStatus)
PAYMENT_KEYS = (shipment.PAYMENT_CARD, shipment.PAYMENT_COD)
SHIPPING_KEYS = (shipment.METHOD_WAREHOUSE, shipment.METHOD_COURIER)

# /handler/ expects the textual option value for payment_method/shipping_method,
# while statusId is an ID.  The dictionaries API returns {id, name}; older
# panel builds accidentally stored the ID for all three fields.  Keep safe
# canonical fallbacks so already-created Elfar orders never lose data in CRM.
DEFAULT_PAYMENT_NAMES = {
    shipment.PAYMENT_CARD: "Переказ на картку",
    shipment.PAYMENT_COD: "Накладений платіж",
}
DEFAULT_SHIPPING_NAMES = {
    shipment.METHOD_WAREHOUSE: "Нова пошта",
    shipment.METHOD_COURIER: "Кур'єр на адресу",
}
_MAP_KEYS = {
    "salesdrive_status_map": STATUS_KEYS,
    "salesdrive_payment_map": PAYMENT_KEYS,
    "salesdrive_shipping_map": SHIPPING_KEYS,
}


class SalesDriveError(Exception):
    """SalesDrive відмовив або недоступний. temporary — чи варто повторювати."""

    def __init__(self, message: str, *, temporary: bool = True, uncertain: bool = False):
        super().__init__(message)
        self.temporary = temporary
        self.uncertain = uncertain



def telegram_form_id(shop) -> int:
    """ID дозволеної бази/форми SalesDrive «ELFAR — Telegram Bot».

    Значення зберігається разом з іншими налаштуваннями інтеграції та
    редагується системним адміністратором у панелі. 0/відсутність означає
    fail-closed: запис і webhook-синхронізація блокуються.
    """
    try:
        return int(getattr(shop, "salesdrive_telegram_form_id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def source_matches(payload: dict, shop) -> bool:
    """Webhook належить саме нашому акаунту і базі «ELFAR — Telegram Bot»."""
    expected = telegram_form_id(shop)
    if expected <= 0:
        return False
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    account = str(info.get("account") or "").strip().lower()
    if account and account != (shop.salesdrive_domain or "").strip().lower():
        return False
    try:
        return int(data.get("formId")) == expected
    except (TypeError, ValueError):
        return False


# ------------------------------------------------------------- відповідності

def validate_mapping(field: str, raw: str) -> str | None:
    """Причина, чому відповідність не годиться. None — годиться."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "Очікується JSON-обʼєкт, наприклад {\"new\": \"1\"}"
    if not isinstance(data, dict):
        return "Очікується JSON-обʼєкт «наше значення → значення SalesDrive»"
    allowed = _MAP_KEYS.get(field, ())
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        return f"Невідомі ключі: {', '.join(unknown)}. Допустимі: {', '.join(allowed)}"
    bad = [k for k, v in data.items() if not isinstance(v, (str, int)) or str(v).strip() == ""]
    if bad:
        return f"Порожнє або нетекстове значення для: {', '.join(sorted(bad))}"
    return None


def mapping(raw: str | None) -> dict[str, str]:
    """Відповідність із налаштувань. Зіпсована — порожня, а не падіння:
    валідатор панелі не пропускає зіпсоване, а значення з .env могли
    вписати руками."""
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v).strip() for k, v in data.items()} if isinstance(data, dict) else {}


def status_from_crm(shop, status_id) -> OrderStatus | None:
    """Статус Elfar за statusId SalesDrive.

    Кілька наших статусів можуть вести в один статус CRM (наприклад,
    «Підтверджено» і «Прийнято» → «В роботі»). Назад такий statusId
    перекладаємо в найпізніший із них за порядком обробки: інакше
    підтвердження з CRM відкочувало б уже прийняте замовлення.
    """
    wanted = str(status_id or "").strip()
    if not wanted:
        return None
    matches = [key for key, value in mapping(shop.salesdrive_status_map).items() if value == wanted]
    if not matches:
        return None
    order = list(STATUS_KEYS)
    matches.sort(key=lambda key: order.index(key) if key in order else -1)
    return OrderStatus(matches[-1])


# ------------------------------------------------------------------ заявка

def base_url(shop) -> str:
    domain = (shop.salesdrive_domain or "").strip().lower()
    return f"https://{domain}.salesdrive.me"


def _site(shop) -> str:
    if (shop.salesdrive_site or "").strip():
        return shop.salesdrive_site.strip()
    url = (shop.public_url or "").split("://")[-1]
    return url.split("/")[0]


def _comment(order: Order, shop) -> str:
    """Коментар заявки: побажання покупця й розклад суми.

    Знижку й бонуси передаємо текстом. Окремого поля знижки на всю заявку
    в API додавання немає, а розкидати її по позиціях означало б показати
    в CRM ціни, яких у магазині не було.
    """
    lines = []
    if order.comment:
        lines.append(order.comment.strip())
    money = []
    if order.discount and order.discount > 0:
        money.append(f"знижка {shipment.money(order.discount)} {shop.currency}")
    if order.bonus_used and order.bonus_used > 0:
        money.append(f"бонуси {shipment.money(order.bonus_used)} {shop.currency}")
    if money:
        lines.append(f"Сума товарів {shipment.money(order.subtotal)}; "
                     + ", ".join(money)
                     + f"; до сплати {shipment.money(order.total)} {shop.currency}")
    if order.promo_code:
        lines.append(f"Промокод: {order.promo_code}")
    lines.append(f"Замовлення Elfar №{order.id}")
    return "\n".join(lines)


def _novaposhta_block(order: Order) -> dict:
    """Дані Нової пошти для ``POST /handler/`` SalesDrive.

    Важливо не плутати цей контракт із Nova Poshta InternetDocument API:
    SalesDrive для доставки у відділення документує ``ServiceType=Warehouse``.
    Для адресної доставки лишаємо сумісне значення ``WarehouseDoors``, яке
    описує фактичний маршрут від нашого відділення-відправника до дверей;
    текстова адреса також завжди передається у ``shipping_address``.
    """
    where = shipment.destination(order)
    block = {
        "ServiceType": "WarehouseDoors" if where.to_door else "Warehouse",
        "payer": "Recipient",
    }
    if where.city_ref:
        block["city"] = where.city_ref
    if where.warehouse_ref and not where.to_door:
        block["WarehouseNumber"] = where.warehouse_ref
    if order.tracking_number:
        block["ttn"] = order.tracking_number
    return block


def create_payload(order: Order, shop) -> dict:
    """Тіло POST /handler/ — нова заявка."""
    person = shipment.recipient(order)
    where = shipment.destination(order)
    payments = mapping(shop.salesdrive_payment_map)
    shippings = mapping(shop.salesdrive_shipping_map)
    statuses = mapping(shop.salesdrive_status_map)
    payload = {
        "form": shop.salesdrive_form_key,
        "getResultData": "1",
        "externalId": str(order.id),
        "fName": person.first_name,
        "lName": person.last_name,
        "mName": person.middle_name,
        "phone": person.phone,
        "products": [
            {
                "id": str(line.product_id) if line.product_id else f"line-{line.id or 0}",
                "name": line.name,
                "costPerItem": shipment.money(line.price),
                "amount": str(line.qty),
            }
            for line in order.items
        ],
        "comment": _comment(order, shop),
        "shipping_address": where.text,
        "sajt": _site(shop),
        "novaposhta": _novaposhta_block(order),
    }
    # SalesDrive form fields use the *textual option value*, not dictionary ID.
    # 1.36.0 stored IDs here by mistake. Numeric legacy values are therefore
    # treated as unusable and replaced with the canonical value we already
    # know from the Elfar checkout. This makes payment/delivery non-lossy even
    # before an administrator re-saves the corrected mappings.
    payment_value = str(payments.get(order.payment_method, "") or "").strip() if order.payment_method else ""
    if not payment_value or payment_value.isdigit():
        payment_value = DEFAULT_PAYMENT_NAMES.get(order.payment_method or "", "")
    if payment_value:
        payload["payment_method"] = payment_value

    shipping_value = str(shippings.get(where.method, "") or "").strip()
    if not shipping_value or shipping_value.isdigit():
        shipping_value = DEFAULT_SHIPPING_NAMES.get(where.method, "")
    if shipping_value:
        payload["shipping_method"] = shipping_value
    if statuses.get(order.status.value):
        payload["statusId"] = statuses[order.status.value]
    return payload


def update_payload(order: Order, shop) -> dict:
    """Тіло POST /api/order/update/ — лише те, що веде Elfar.

    Коментар, адресу, менеджера в CRM не перезаписуємо: їх там редагують
    руками, і кожна наша зміна статусу затирала б чужу роботу.
    """
    data: dict = {}
    status_id = mapping(shop.salesdrive_status_map).get(order.status.value)
    if status_id:
        data["statusId"] = status_id
    if order.tracking_number and order.waybill_source != "salesdrive":
        data["novaposhta"] = {"ttn": order.tracking_number}
    payload = {"form": shop.salesdrive_form_key, "data": data}
    if order.crm_id:
        payload["id"] = order.crm_id
    else:
        payload["externalId"] = str(order.id)
    return payload


# -------------------------------------------------------------------- HTTP

async def _post(url: str, payload: dict, headers: dict) -> httpx.Response:
    """Один запит. Окремою функцією — набір перевірок підставляє свій."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
        return await client.post(url, json=payload, headers=headers)


def _headers(shop) -> dict:
    """Заголовки для write API та /handler/.

    Поточний Swagger SalesDrive документує ``X-Api-Key`` для API, тоді як
    старі endpoint/акаунти використовують ``Form-Api-Key``. Відправляємо
    обидва для API-ключа; /handler/ додатково автентифікується полем ``form``
    у payload, тому зайвий сумісний заголовок не змінює семантику заявки.
    """
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if shop.salesdrive_api_connected:
        key = str(shop.salesdrive_api_key or "").strip()
        if key:
            headers["Form-Api-Key"] = key
            headers["X-Api-Key"] = key
    return headers


def _read_headers(shop) -> dict:
    """Авторизація read API SalesDrive.

    SalesDrive у поточній документації приймає X-Api-Key; старі акаунти й
    частина endpoint також працюють з Form-Api-Key. Відправляємо обидва з
    тим самим read-key — це сумісно з обома варіантами й уже використовується
    в інших read-side запитах проєкту.
    """
    key = str(getattr(shop, "salesdrive_api_key", "") or "").strip()
    return {"Accept": "application/json", "Form-Api-Key": key, "X-Api-Key": key}


def dictionary_items(payload) -> list[dict]:
    """Нормалізований довідник SalesDrive ``[{id, name}]``.

    У різних endpoint/версіях API список приходить напряму або під
    ``data/items/list/results``. Тут не вгадуємо бізнес-значення, лише
    нормалізуємо документований ``id`` + ``name`` і сумісні назви полів.
    """
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next((payload[k] for k in ("data", "items", "list", "results")
                     if isinstance(payload.get(k), list)), [])
    else:
        rows = []
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident = row.get("id", row.get("value", row.get("statusId")))
        name = row.get("name", row.get("label", row.get("title")))
        sid = str(ident or "").strip()
        title = str(name or "").strip()
        if not sid or not title or sid in seen:
            continue
        seen.add(sid)
        result.append({"id": sid, "name": title})
    return result


def _cache_key(shop) -> str:
    """Ключ кешу без збереження API-ключа у відкритому вигляді."""
    domain = str(getattr(shop, "salesdrive_domain", "") or "").strip().lower()
    key = str(getattr(shop, "salesdrive_api_key", "") or "")
    fingerprint = hashlib.sha256(key.encode()).hexdigest()[:12] if key else "no-key"
    return f"{domain}:{fingerprint}"


_dictionary_cache: dict[str, dict] = {}
_status_cache: dict[str, dict] = {}


def cached_dictionary_bundle(shop) -> dict:
    """Останні довідники без мережевого запиту (для швидкого webhook)."""
    cached = _dictionary_cache.get(_cache_key(shop))
    if not cached:
        return {"statuses": [], "payments": [], "deliveries": []}
    return cached.get("value") or {"statuses": [], "payments": [], "deliveries": []}


def _option_map(items: list[dict]) -> dict[str, str]:
    return {str(x.get("id") or "").strip(): str(x.get("name") or "").strip()
            for x in items if str(x.get("id") or "").strip() and str(x.get("name") or "").strip()}


def _resolve_option(raw, items: list[dict]) -> tuple[str, str]:
    """Повертає ``(id/raw, human name)``.

    order-list/webhook в різних полях можуть віддати або ID опції, або її
    текст. Панель завжди повинна показувати людині текст, але сире значення
    лишаємо у snapshot для діагностики й майбутніх змін API.
    """
    value = str(raw or "").strip()
    if not value:
        return "", ""
    by_id = _option_map(items)
    if value in by_id:
        return value, by_id[value]
    lowered = value.casefold()
    for item in items:
        name = str(item.get("name") or "").strip()
        if name and name.casefold() == lowered:
            return str(item.get("id") or "").strip(), name
    return value, value


async def _get_json(shop, path: str, *, params: dict | None = None, client: httpx.AsyncClient | None = None):
    """GET із SalesDrive з одним обережним retry для read-only помилок.

    Write-запити навмисно НЕ повторюємо автоматично: після таймауту POST міг
    уже виконатися в CRM, а повтор створив би дубль/подвійну дію. Для GET
    повтор безпечний, але 429 не ретраїмо — поважаємо rate-limit SalesDrive.
    """
    if not (getattr(shop, "salesdrive_domain", "") or "").strip():
        raise SalesDriveError("Не задано домен SalesDrive", temporary=False)
    if not getattr(shop, "salesdrive_api_connected", False):
        raise SalesDriveError("Не задано API-ключ SalesDrive", temporary=False)
    owned = client is None
    if owned:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False)

    response = None
    try:
        for attempt in range(2):
            try:
                response = await client.get(base_url(shop) + path, params=params, headers=_read_headers(shop))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == 0:
                    log.warning(
                        "SalesDrive GET %s тимчасово недоступний (%s), одна повторна спроба",
                        path, type(exc).__name__,
                        extra={"event": "salesdrive.read.retry", "path": path, "attempt": 1},
                    )
                    await asyncio.sleep(READ_RETRY_DELAY_SECONDS)
                    continue
                message = "SalesDrive не відповів вчасно" if isinstance(exc, httpx.TimeoutException) else f"SalesDrive недоступний: {type(exc).__name__}"
                raise SalesDriveError(message) from exc

            if response.status_code in (502, 503, 504) and attempt == 0:
                log.warning(
                    "SalesDrive GET %s повернув %s, одна повторна спроба",
                    path, response.status_code,
                    extra={"event": "salesdrive.read.retry", "path": path,
                           "attempt": 1, "status": response.status_code},
                )
                await asyncio.sleep(READ_RETRY_DELAY_SECONDS)
                continue
            break
    finally:
        if owned and client is not None:
            await client.aclose()

    if response is None:
        raise SalesDriveError("SalesDrive не повернув відповідь")
    if response.status_code in (401, 403):
        raise SalesDriveError("SalesDrive відхилив API-ключ", temporary=False)
    if response.status_code == 429:
        retry = str(response.headers.get("Retry-After") or "").strip()
        suffix = f"; повторити через {retry} с" if retry.isdigit() else ""
        raise SalesDriveError(f"SalesDrive обмежив частоту запитів (429){suffix}")
    if response.status_code >= 500:
        raise SalesDriveError(f"SalesDrive тимчасово відмовив ({response.status_code})")
    if response.status_code >= 400:
        raise SalesDriveError(f"SalesDrive відповів {response.status_code} для {path}", temporary=False)
    try:
        return response.json()
    except ValueError as exc:
        raise SalesDriveError("SalesDrive повернув некоректну JSON-відповідь", temporary=False) from exc


async def dictionary_bundle(shop, *, force: bool = False) -> dict:
    """Статуси, оплати й доставки одним кешованим read-side викликом.

    Довідники змінюються рідко, а SalesDrive має окремі rate limits для
    читання. Тому робочі екрани не повинні робити три HTTP-запити при
    кожному відкритті заявки. Коротка недоступність CRM повертає останній
    успішний кеш, якщо він існує.
    """
    key = _cache_key(shop)
    now = time.monotonic()
    cached = _dictionary_cache.get(key)
    if cached and not force and now - cached["stored"] < DICTIONARY_TTL_SECONDS:
        return {**cached["value"], "cached": True}

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
            raw_statuses, raw_payments, raw_deliveries = await asyncio.gather(
                _get_json(shop, "/api/statuses/", client=client),
                _get_json(shop, "/api/payment-methods/", client=client),
                _get_json(shop, "/api/delivery-methods/", client=client),
            )
        value = {
            "statuses": dictionary_items(raw_statuses),
            "payments": dictionary_items(raw_payments),
            "deliveries": dictionary_items(raw_deliveries),
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
        }
        _dictionary_cache[key] = {"stored": now, "value": value}
        _status_cache[key] = {"stored": now, "value": value["statuses"]}
        return {**value, "cached": False}
    except SalesDriveError:
        # force=True використовується кнопкою/діагностикою «Перевірити».
        # У цьому режимі stale-cache не має маскувати реальну недоступність CRM.
        if cached and not force:
            return {**cached["value"], "cached": True, "stale": True}
        raise


async def status_options(shop, *, force: bool = False) -> list[dict]:
    """Поточний довідник статусів CRM без зайвих payment/delivery запитів.

    Робочі сторінки оновлюють список статусів частіше за налаштування, тому
    тягнути три довідники щоразу було зайвим. Повний ``dictionary_bundle``
    лишається для налаштувань і одночасно прогріває цей кеш.
    """
    key = _cache_key(shop)
    now = time.monotonic()
    cached = _status_cache.get(key)
    if cached and not force and now - cached["stored"] < DICTIONARY_TTL_SECONDS:
        return cached["value"]

    full = _dictionary_cache.get(key)
    if full and not force and now - full["stored"] < DICTIONARY_TTL_SECONDS:
        value = full.get("value", {}).get("statuses", [])
        _status_cache[key] = {"stored": now, "value": value}
        return value

    try:
        value = dictionary_items(await _get_json(shop, "/api/statuses/"))
        _status_cache[key] = {"stored": now, "value": value}
        return value
    except SalesDriveError:
        if cached and not force:
            return cached["value"]
        raise


def status_name_from_options(status_id, options: list[dict]) -> str:
    wanted = str(status_id or "").strip()
    return next((str(x.get("name") or "").strip() for x in options
                 if str(x.get("id") or "") == wanted), "")


def _pairs_from_options(value) -> dict[str, str]:
    """Нормалізує ``options`` із meta[fields] до ``id -> label``.

    SalesDrive документує meta[fields] як джерело значень полів, але форма
    конкретних option залежить від типу поля. Підтримуємо лише очевидні
    структури й не намагаємося вгадувати невідомі значення.
    """
    result: dict[str, str] = {}
    if isinstance(value, dict):
        # Простий словник {id: name}.
        if all(not isinstance(v, (dict, list)) for v in value.values()):
            for k, v in value.items():
                sid, name = str(k or "").strip(), str(v or "").strip()
                if sid and name:
                    result[sid] = name
            return result
        for key in ("options", "values", "items", "list", "data"):
            if key in value:
                result.update(_pairs_from_options(value.get(key)))
    elif isinstance(value, list):
        for row in value:
            if not isinstance(row, dict):
                continue
            ident = row.get("id", row.get("value", row.get("key")))
            name = row.get("name", row.get("label", row.get("title", row.get("text"))))
            sid, title = str(ident or "").strip(), str(name or "").strip()
            if sid and title:
                result[sid] = title
    return result


def _field_key(value) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _meta_field_options(body, aliases: tuple[str, ...]) -> dict[str, str]:
    """Шукає опції конкретного поля у документованому ``meta[fields]``.

    SalesDrive повертає ``meta[fields]`` у різних формах залежно від поля та
    версії API: словником або масивом описів полів. Обидві форми читаємо, але
    лише за явним ім'ям/ключем поля — ніякого вгадування опцій за позицією.
    """
    if not isinstance(body, dict):
        return {}
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    fields = meta.get("fields")
    wanted = {_field_key(a) for a in aliases}

    candidates: list[tuple[object, object]] = []
    if isinstance(fields, dict):
        candidates.extend(fields.items())
    elif isinstance(fields, list):
        for row in fields:
            if not isinstance(row, dict):
                continue
            key = (row.get("name") or row.get("key") or row.get("field") or
                   row.get("code") or row.get("slug"))
            candidates.append((key, row))

    for key, value in candidates:
        if _field_key(key) not in wanted:
            continue
        pairs = _pairs_from_options(value)
        if pairs:
            return pairs
    return {}


def _manager_name(data: dict, body=None) -> str:
    for key in ("userName", "managerName", "responsibleName"):
        value = data.get(key)
        if str(value or "").strip():
            return str(value).strip()
    for key in ("user", "manager", "responsible"):
        value = data.get(key)
        if isinstance(value, dict):
            name = value.get("name") or value.get("title") or value.get("label")
            if str(name or "").strip():
                return str(name).strip()
        elif str(value or "").strip() and not str(value).strip().isdigit():
            return str(value).strip()
    uid = str(data.get("userId") or "").strip()
    if uid:
        names = _meta_field_options(body, ("userId", "manager", "managerId", "user"))
        if uid in names:
            return names[uid]
    return ""


async def _send(shop, path: str, payload: dict) -> dict:
    if telegram_form_id(shop) <= 0:
        raise SalesDriveError("Не вказано ID форми SalesDrive «ELFAR — Telegram Bot»; запис заблоковано", temporary=False)
    url = base_url(shop) + path
    try:
        response = await _post(url, payload, _headers(shop))
    except httpx.TimeoutException as exc:
        # Запит міг дійти й виконатись — відповіді просто не дочекались.
        raise SalesDriveError("SalesDrive не відповів вчасно", uncertain=True) from exc
    except httpx.HTTPError as exc:
        raise SalesDriveError(f"SalesDrive недоступний: {type(exc).__name__}") from exc

    if response.status_code in (401, 403):
        raise SalesDriveError("SalesDrive відхилив ключ форми або API-ключ", temporary=False)
    if response.status_code == 429 or response.status_code >= 500:
        raise SalesDriveError(f"SalesDrive тимчасово відмовив ({response.status_code})")
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400:
        raise SalesDriveError(f"SalesDrive відхилив запит ({response.status_code}): "
                              f"{_reason(body)}", temporary=False)
    if isinstance(body, dict) and body.get("success") is False:
        raise SalesDriveError(f"SalesDrive відхилив запит: {_reason(body)}", temporary=False)
    return body if isinstance(body, dict) else {}


def _reason(body) -> str:
    if not isinstance(body, dict):
        return "без пояснення"
    for key in ("message", "error", "errors"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:300]
        if isinstance(value, (list, dict)) and value:
            return json.dumps(value, ensure_ascii=False)[:300]
    return "без пояснення"


def _crm_id_from(body: dict) -> str | None:
    """ID заявки з відповіді ``/handler/`` при ``getResultData=1``.

    Поточний документований формат — ``data.orderId``; сумісні fallback-и
    лишені для старих акаунтів/відповідей, які вже підтримував проєкт.
    """
    for container in (body.get("data") if isinstance(body.get("data"), dict) else {}, body):
        for key in ("orderId", "id", "order_id"):
            value = container.get(key)
            if value not in (None, "", 0):
                return str(value)
    return None


def _created_manager_id(body: dict) -> str:
    data = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else {}
    value = data.get("userId")
    return str(value).strip() if value not in (None, "", 0) else ""


# ------------------------------------------------------------ синхронізація

async def push_order(repo, order_id: int, shop=None) -> str:
    """Відправляє замовлення в SalesDrive. Повертає новий crm_state."""
    from shop.services.shop_settings import get_shop_settings
    shop = shop or await get_shop_settings(repo)
    order = await repo.get_order(order_id)
    if not order:
        return ""
    if not shop.salesdrive_ready:
        # Вимкнено — позначка лишається в черзі й поїде після ввімкнення.
        return order.crm_state

    try:
        if order.crm_id or order.crm_state in (STATE_SYNCED, STATE_UNCERTAIN):
            try:
                await _send(shop, "/api/order/update/", update_payload(order, shop))
            except SalesDriveError as exc:
                if order.crm_state != STATE_UNCERTAIN or exc.temporary:
                    raise
                # Заявки за externalId немає — створення тоді не дійшло.
                return await _create(repo, order, shop)
            await _mark(repo, order, STATE_SYNCED)
            return STATE_SYNCED
        return await _create(repo, order, shop)
    except SalesDriveError as exc:
        state = STATE_UNCERTAIN if exc.uncertain else STATE_FAILED
        await repo.update_order(order.id, {
            "crm_state": state,
            "crm_error": str(exc)[:500],
            "crm_attempts": (order.crm_attempts or 0) + 1,
        })
        log.warning("Замовлення %s не синхронізовано з SalesDrive: %s", order.id, exc,
                    extra={"event": "salesdrive.push.failed", "orderId": order.id,
                           "state": state, "attempt": (order.crm_attempts or 0) + 1})
        return state


async def _create(repo, order: Order, shop) -> str:
    # Позначка «створюється» до запиту: якщо процес упаде посеред нього,
    # планувальник побачить незавершене створення й не продублює заявку.
    await repo.update_order(order.id, {"crm_state": STATE_CREATING})
    body = await _send(shop, "/handler/", create_payload(order, shop))
    crm_id = _crm_id_from(body)
    manager_id = _created_manager_id(body)
    initial_status_id = mapping(shop.salesdrive_status_map).get(order.status.value)
    await _mark(repo, order, STATE_SYNCED, crm_id=crm_id, crm_status_id=initial_status_id)
    log.info("Замовлення %s створено в SalesDrive як %s", order.id, crm_id or "—",
             extra={"event": "salesdrive.order.created", "orderId": order.id,
                    "crmId": crm_id, "crmManagerId": manager_id or None})
    return STATE_SYNCED


async def _mark(repo, order: Order, state: str, crm_id: str | None = None, crm_status_id: str | None = None) -> None:
    patch = {"crm_state": state, "crm_error": None, "crm_attempts": 0,
             "crm_synced_at": datetime.now(timezone.utc)}
    if crm_id and not order.crm_id:
        patch["crm_id"] = crm_id
    if crm_status_id:
        patch["crm_status_id"] = str(crm_status_id)
    await repo.update_order(order.id, patch)


_inflight: set[int] = set()
_tasks: set[asyncio.Task] = set()


def push_soon(order_id: int) -> None:
    """Відправка у фоні одразу після зміни.

    Не в тому самому запиті: SalesDrive, що відповідає двадцять секунд, не
    має тримати менеджера перед кнопкою. Не більше однієї відправки на
    замовлення водночас — друга прочитала б застарілий стан і могла б
    створити дубль заявки.
    """
    # Вимкнена інтеграція — жодної фонової задачі. Інакше кожна зміна
    # статусу в будь-якому процесі (бот, службовий скрипт, набір перевірок)
    # відкривала б власне зʼєднання з базою поза життєвим циклом процесу:
    # саме так tests_repo зависав після «Пройдено 62 з 62» — задача
    # лишала незакритий потік драйвера бази. Позначка pending уже в базі;
    # увімкнете інтеграцію — планувальник відправить.
    #
    # Налаштування з кешу, без запиту: зміна статусу щойно читала їх
    # (create_order і панель), тож кеш теплий. Холодний кеш дає дефолти з
    # .env — у гіршому разі відправку дожене планувальник.
    from shop.services.shop_settings import current
    if not current().salesdrive_ready:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if order_id in _inflight:
        return
    _inflight.add(order_id)

    async def run():
        try:
            from shop.repo.factory import open_repo
            async with open_repo() as repo:
                await push_order(repo, order_id)
        except Exception:
            log.exception("Фонова синхронізація замовлення %s впала", order_id)
        finally:
            _inflight.discard(order_id)

    # Посилання на задачу тримаємо: asyncio зберігає лише слабке, і задачу
    # без посилань збирач сміття може прибрати посеред запиту.
    task = loop.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def sync_pending(repo, limit: int = 50) -> dict:
    """Прохід планувальника: усе, що в черзі, і незавершені створення."""
    from shop.services.shop_settings import get_shop_settings
    shop = await get_shop_settings(repo)
    if not shop.salesdrive_ready:
        return {"skipped": "disabled"}
    done = {"synced": 0, "failed": 0}
    for order in await repo.orders_for_crm_sync(RETRY_STATES + (STATE_CREATING,), limit=limit):
        if order.crm_attempts >= MAX_ATTEMPTS:
            continue
        if order.crm_state == STATE_CREATING:
            # Створення, яке не завершилось, — стан невідомий, як і після
            # таймауту. Репозиторій повертає лише старі такі записи.
            await repo.update_order(order.id, {"crm_state": STATE_UNCERTAIN})
        state = await push_order(repo, order.id, shop)
        done["synced" if state == STATE_SYNCED else "failed"] += 1
    return done


# ------------------------------------------------------------------ вебхук

def token_matches(shop, token: str) -> bool:
    """Порівняння сталого часу. Порожній токен у налаштуваннях — вимкнено."""
    expected = (shop.salesdrive_webhook_token or "").strip()
    return bool(expected) and hmac.compare_digest(expected.encode(), (token or "").encode())


def _tracking_from(data: dict) -> tuple[str, str | None, Decimal | None]:
    """Номер, ref та вартість накладної з документованих CRM-полів."""
    np_block = data.get("ord_novaposhta") if isinstance(data.get("ord_novaposhta"), dict) else {}
    number = str(np_block.get("EN") or "").strip()
    if number:
        cost = None
        try:
            if np_block.get("cost") not in (None, ""):
                cost = Decimal(str(np_block.get("cost")))
        except (ArithmeticError, ValueError):
            cost = None
        return number, (str(np_block.get("ENref") or "").strip() or None), cost

    up_block = data.get("ord_ukrposhta") if isinstance(data.get("ord_ukrposhta"), dict) else {}
    number = str(up_block.get("barcode") or "").strip()
    cost = None
    try:
        if up_block.get("cost") not in (None, ""):
            cost = Decimal(str(up_block.get("cost")))
    except (ArithmeticError, ValueError):
        cost = None
    return number, (str(up_block.get("barcodeUuid") or "").strip() or None), cost


def _tracking_explicitly_present(data: dict) -> bool:
    """Webhook справді передав поле ТТН, навіть якщо воно порожнє.

    Це відрізняє «CRM видалила ТТН» від часткового webhook, який блок
    доставки взагалі не надсилав. У другому випадку локальний номер не
    чіпаємо.
    """
    np_block = data.get("ord_novaposhta")
    if isinstance(np_block, dict) and "EN" in np_block:
        return True
    up_block = data.get("ord_ukrposhta")
    return isinstance(up_block, dict) and "barcode" in up_block


async def handle_webhook(repo, payload: dict, *, bot=None) -> dict:
    """Застосовує зміну з SalesDrive до замовлення Elfar."""
    from shop.services import order_workflow as flow
    from shop.services.shop_settings import get_shop_settings

    shop = await get_shop_settings(repo)
    if not source_matches(payload, shop):
        log.warning("Webhook SalesDrive відхилено: інша або невідома база заявок",
                    extra={"event": "salesdrive.webhook.wrong_source",
                           "expectedFormId": telegram_form_id(shop)})
        return {"result": "ignored", "reason": "інша база заявок SalesDrive"}
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    event = str(info.get("webhookEvent") or "")
    crm_id = str(data.get("id") or "").strip()

    order = await repo.find_order_by_crm_id(crm_id) if crm_id else None
    external = str(data.get("externalId") or "").strip()
    if not order and external.isdigit():
        candidate = await repo.get_order(int(external))
        # Не дозволяємо webhook прив'язати історичне замовлення лише через
        # збіг externalId. Воно має вже належати до CRM-черги (pending/
        # creating/failed/uncertain/synced) або мати crm_id.
        if candidate and (candidate.crm_id or candidate.crm_state):
            order = candidate
    if not order:
        # Заявки, створені в CRM руками, у магазин не переносимо: замовлення
        # Elfar завжди має клієнта в Telegram, а в такої заявки його немає.
        log.info("Вебхук SalesDrive для невідомої заявки %s", crm_id or "—",
                 extra={"event": "salesdrive.webhook.unknown", "crmId": crm_id,
                        "webhookEvent": event})
        return {"result": "ignored", "reason": "замовлення не знайдено"}

    if crm_id and order.crm_id != crm_id:
        await repo.update_order(order.id, {"crm_id": crm_id})
        order = await repo.get_order(order.id) or order

    applied: list[str] = []
    problems: list[str] = []

    number, ref, cost = _tracking_from(data)
    if number:
        # Викликаємо навіть коли номер той самий: пізніший webhook часто
        # довантажує ENref/вартість/джерело вже після створення ТТН.
        result = await flow.apply_tracking(
            repo, order, number, origin=flow.ORIGIN_SALESDRIVE, bot=bot,
            ref=ref or "", source=flow.SOURCE_SALESDRIVE, cost=cost,
        )
        order = result.order
        if result.changed:
            applied.append("tracking")
    elif (_tracking_explicitly_present(data)
          and order.waybill_source == flow.SOURCE_SALESDRIVE
          and order.tracking_number):
        # Порожній EN/barcode, який CRM передала явно, означає видалення
        # накладної. Частковий webhook без поля ТТН сюди не потрапляє.
        result = await flow.apply_tracking(
            repo, order, "", origin=flow.ORIGIN_SALESDRIVE, bot=None,
        )
        order = result.order
        if result.changed:
            applied.append("tracking")

    incoming_status_id = str(data.get("statusId") or "").strip()
    incoming_status_name = str(data.get("statusName") or data.get("status_name") or "").strip()

    # Webhook SalesDrive гарантовано дає нам statusId, а назва залежить від
    # конфігурації webhook. Тут навмисно НЕ робимо другий HTTP-запит у CRM:
    # webhook має швидко підтвердити приймання, інакше SalesDrive повторить
    # доставку. Актуальну назву панель бере з /api/statuses/, а картка заявки
    # — під час прямого refresh. Якщо ID змінився без назви, стару назву
    # очищаємо нижче, щоб UI ніколи не підписав новий ID старим текстом.
    status_names = ({incoming_status_id: incoming_status_name}
                    if incoming_status_id and incoming_status_name else {})

    cached_bundle = cached_dictionary_bundle(shop)
    webhook_snapshot = _snapshot(
        data, status_names, payments=cached_bundle.get("payments", []),
        deliveries=cached_bundle.get("deliveries", []), body=payload, source="webhook",
    )
    if incoming_status_name and not webhook_snapshot.get("statusName"):
        webhook_snapshot["statusName"] = incoming_status_name
    webhook_snapshot = _merge_webhook_snapshot(order.crm_snapshot, webhook_snapshot, data)
    await repo.update_order(order.id, {
        "crm_snapshot": webhook_snapshot, "crm_fetched_at": datetime.now(timezone.utc),
    })

    if incoming_status_id:
        patch = {
            "crm_status_id": incoming_status_id,
            # None важливий: не лишаємо назву попереднього statusId, якщо
            # webhook надіслав тільки новий ID.
            "crm_status_name": incoming_status_name or None,
        }
        await repo.update_order(order.id, patch)
        order = await repo.get_order(order.id) or order

    target = status_from_crm(shop, incoming_status_id)
    if target and target != order.status:
        try:
            await flow.apply_crm_status_progression(repo, order, target, bot=bot)
            applied.append("status")
        except flow.WorkflowError as exc:
            problems.append(str(exc))
            # Відмову видно в панелі біля замовлення: інакше CRM і магазин
            # мовчки розійшлися б, і ніхто б не знав чому.
            await repo.update_order(order.id, {
                "crm_error": f"Статус із SalesDrive не застосовано: {exc}"[:500],
            })
            log.warning("Статус із SalesDrive для замовлення %s не застосовано: %s",
                        order.id, exc,
                        extra={"event": "salesdrive.webhook.rejected", "orderId": order.id,
                               "target": target.value, "current": order.status.value})

    return {"result": "applied" if applied else ("rejected" if problems else "unchanged"),
            "orderId": order.id, "applied": applied, "problems": problems}


def _order_list_rows(body) -> list[dict]:
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if not isinstance(body, dict):
        return []
    for key in ("data", "items", "list", "results"):
        rows = body.get(key)
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []


def _snapshot(data: dict, statuses: dict[str, str] | None = None, *,
              payments: list[dict] | None = None, deliveries: list[dict] | None = None,
              body=None, source: str = "api") -> dict:
    """Повний безпечний read-model заявки CRM.

    Snapshot читає тільки документовані поля SalesDrive. Каталог ELFAR,
    локальні ціни й адреса замовлення з нього не перезаписуються. Сирі ID
    опцій зберігаємо поруч із людиночитаними назвами, щоб панель не показувала
    ``56``/``57`` замість способу оплати або доставки.
    """
    contacts = data.get("contacts") if isinstance(data.get("contacts"), list) else []
    contact = contacts[0] if contacts and isinstance(contacts[0], dict) else {}
    counterparty = contact.get("counterparty") if isinstance(contact.get("counterparty"), dict) else {}
    products = data.get("products") if isinstance(data.get("products"), list) else []
    np = data.get("ord_novaposhta") if isinstance(data.get("ord_novaposhta"), dict) else {}
    up = data.get("ord_ukrposhta") if isinstance(data.get("ord_ukrposhta"), dict) else {}
    delivery_data = data.get("ord_delivery_data") if isinstance(data.get("ord_delivery_data"), dict) else {}

    sid = str(data.get("statusId") or "").strip()
    status_name = str(data.get("statusName") or data.get("status_name") or "").strip()
    if not status_name and statuses:
        status_name = statuses.get(sid, "")
    if not status_name and sid:
        status_name = _meta_field_options(body, ("statusId", "status", "status_id")).get(sid, "")

    payment_raw = data.get("payment_method")
    shipping_raw = data.get("shipping_method")
    payment_id, payment_name = _resolve_option(payment_raw, payments or [])
    shipping_id, shipping_name = _resolve_option(shipping_raw, deliveries or [])

    # Якщо order-list віддав ID, а довідник недоступний, спробуємо
    # документований meta[fields] із тієї ж відповіді — без другого HTTP.
    if payment_name == str(payment_raw or "").strip() and str(payment_raw or "").strip().isdigit():
        meta = _meta_field_options(body, ("payment_method", "paymentMethod"))
        payment_name = meta.get(str(payment_raw).strip(), payment_name)
    if shipping_name == str(shipping_raw or "").strip() and str(shipping_raw or "").strip().isdigit():
        meta = _meta_field_options(body, ("shipping_method", "shippingMethod"))
        shipping_name = meta.get(str(shipping_raw).strip(), shipping_name)

    manager = _manager_name(data, body)

    product_rows = []
    for x in products:
        if not isinstance(x, dict):
            continue
        product_rows.append({
            "id": x.get("id"), "productId": x.get("productId"), "parameter": x.get("parameter"),
            "name": x.get("name") or "", "sku": x.get("sku") or "", "barcode": x.get("barcode") or "",
            "amount": x.get("amount"), "price": x.get("price"), "costPrice": x.get("costPrice"),
            "discount": x.get("discount"), "percentDiscount": x.get("percentDiscount"),
            "commission": x.get("commission"), "percentCommission": x.get("percentCommission"),
            "description": x.get("description") or "", "note": x.get("note") or "",
            "stockId": x.get("stockId"), "mass": x.get("mass"), "volume": x.get("volume"),
            "restCount": x.get("restCount"), "manufacturer": x.get("manufacturer") or "",
            # З 27.08.2026 SalesDrive використовує upsell; preSale лишаємо
            # лише як fallback для старих webhook payload.
            "upsell": x.get("upsell", x.get("preSale")), "isComplect": x.get("isComplect"),
            "categoryId": x.get("categoryId"), "categoryName": x.get("categoryName") or "",
            "href": x.get("href") or "", "defaultPriceData": x.get("defaultPriceData"),
            "priceTypes": x.get("priceTypes"), "complect": x.get("complect"),
        })

    return {
        "source": source,
        "id": str(data.get("id") or ""), "externalId": str(data.get("externalId") or ""),
        "version": data.get("version"), "formId": data.get("formId"), "typeId": data.get("typeId"),
        "statusId": sid, "statusName": status_name, "rejectionReason": data.get("rejectionReason") or "",
        "paymentMethodId": payment_id, "paymentMethod": payment_name,
        "paymentMethodRaw": str(payment_raw or ""),
        "shippingMethodId": shipping_id, "shippingMethod": shipping_name,
        "shippingMethodRaw": str(shipping_raw or ""),
        "paymentAmount": data.get("paymentAmount"), "commissionAmount": data.get("commissionAmount"),
        "costPriceAmount": data.get("costPriceAmount"), "expensesAmount": data.get("expensesAmount"),
        "profitAmount": data.get("profitAmount"), "payedAmount": data.get("payedAmount"),
        "restPay": data.get("restPay"), "paymentDate": data.get("paymentDate"),
        "managerId": data.get("userId"), "managerName": manager,
        "comment": data.get("comment") or "", "orderTime": data.get("orderTime"),
        "timeEntryOrder": data.get("timeEntryOrder"), "holderTime": data.get("holderTime"),
        "delivery": data.get("ord_delivery"),
        # У order-list з 2025 SalesDrive окремо повертає додаткові параметри
        # доставки. Зберігаємо тільки документовані поля; решта лишається у CRM.
        "deliveryData": {
            "paymentMethod": delivery_data.get("paymentMethod") or "",
            "postpayPayer": delivery_data.get("postpayPayer") or "",
            "cargoType": delivery_data.get("cargoType") or "",
        },
        "utm": {
            "page": data.get("utmPage") or "", "medium": data.get("utmMedium") or "",
            "campaignId": data.get("campaignId"), "sourceFull": data.get("utmSourceFull") or "",
            "source": data.get("utmSource") or "", "campaign": data.get("utmCampaign") or "",
        },
        "contact": {
            "id": contact.get("id"), "formId": contact.get("formId"), "version": contact.get("version"),
            "createTime": contact.get("createTime"), "fName": contact.get("fName") or "",
            "lName": contact.get("lName") or "", "mName": contact.get("mName") or "",
            "phone": contact.get("phone") or "", "email": contact.get("email") or "",
            "company": contact.get("company") or "", "comment": contact.get("comment") or "",
            "userId": contact.get("userId"), "leadsCount": contact.get("leadsCount"),
            "leadsSalesCount": contact.get("leadsSalesCount"), "leadsSalesAmount": contact.get("leadsSalesAmount"),
            "counterparty": {"id": counterparty.get("id"), "name": counterparty.get("name") or "",
                             "code": counterparty.get("code") or ""},
        },
        "products": product_rows,
        "novaposhta": {
            "delivery": np.get("delivery") or "", "settlementRef": np.get("settlementRef") or "",
            "city": np.get("city") or "", "branch": np.get("branch") or "", "branchNumber": np.get("branchNumber") or "",
            "street": np.get("street") or "", "house": np.get("house") or "", "flat": np.get("flat") or "",
            "note": np.get("note") or "", "cargoType": np.get("cargoType") or "", "payer": np.get("payer") or "",
            "paymentMethod": np.get("paymentMethod") or "", "ttn": np.get("EN") or "", "ref": np.get("ENref") or "",
            "backDelivery": np.get("backDelivery") or "", "postpayPayer": np.get("postpayPayer") or "",
            "postpaySum": np.get("postpaySum"), "status": np.get("status") or "", "statusCode": np.get("statusCode"),
            "dateStatusUpdate": np.get("dateStatusUpdate"), "deliveryDateAndTime": np.get("deliveryDateAndTime"),
            "recipientDateTime": np.get("recipientDateTime"), "manual": np.get("manual"), "idEntity": np.get("idEntity"),
            "cost": np.get("cost"), "legal": np.get("legal"), "companyName": np.get("companyName") or "",
            "egrpou": np.get("egrpou") or "", "ownershipFormId": np.get("ownershipFormId"), "packing": np.get("packing") or "",
        },
        "ukrposhta": {
            "delivery": up.get("delivery") or "", "region": up.get("region"), "district": up.get("district"),
            "city": up.get("city"), "branch": up.get("branch"), "street": up.get("street"), "house": up.get("house") or "",
            "flat": up.get("flat") or "", "payer": up.get("payer") or "", "typeUkrPoshta": up.get("typeUkrPoshta") or "",
            "ttn": up.get("barcode") or "", "ref": up.get("barcodeUuid") or "", "postpaySum": up.get("postpaySum"),
            "status": up.get("status") or "", "statusCode": up.get("statusCode"), "dateStatusUpdate": up.get("dateStatusUpdate"),
            "deliveryDateAndTime": up.get("deliveryDateAndTime"), "manual": up.get("manual"), "cost": up.get("cost"),
            "sum": up.get("sum"), "mass": up.get("mass"), "length": up.get("length"), "description": up.get("description") or "",
            "cityName": up.get("cityName") or "", "branchName": up.get("branchName") or "", "streetName": up.get("streetName") or "",
        },
    }


def _merge_webhook_snapshot(previous: dict | None, incoming: dict, raw: dict) -> dict:
    """Накладає webhook на останній повний read-side snapshot.

    Webhook SalesDrive може бути коротшим за ``/api/order/list/``. Повністю
    замінювати snapshot означало втрачати назву менеджера, розширені дані
    товарів та вже розв'язані опції після звичайної зміни статусу. Водночас
    не можна сліпо зберігати старе значення, якщо CRM явно надіслала порожнє.
    Тому оновлюємо лише ті групи, чиї сирі поля реально були у webhook.
    """
    if not isinstance(previous, dict):
        return incoming
    merged = dict(previous)
    merged["source"] = "webhook"

    scalar_sources = {
        "id": "id", "externalId": "externalId", "version": "version", "formId": "formId",
        "typeId": "typeId", "rejectionReason": "rejectionReason",
        "paymentAmount": "paymentAmount", "commissionAmount": "commissionAmount",
        "costPriceAmount": "costPriceAmount", "expensesAmount": "expensesAmount",
        "profitAmount": "profitAmount", "payedAmount": "payedAmount", "restPay": "restPay",
        "paymentDate": "paymentDate", "comment": "comment", "orderTime": "orderTime",
        "timeEntryOrder": "timeEntryOrder", "holderTime": "holderTime", "delivery": "ord_delivery",
    }
    for target, source_key in scalar_sources.items():
        if source_key in raw:
            merged[target] = incoming.get(target)

    if "statusId" in raw or "statusName" in raw or "status_name" in raw:
        merged["statusId"] = incoming.get("statusId", "")
        # Якщо прийшов новий ID без розв'язаної назви, стару назву прибираємо.
        merged["statusName"] = incoming.get("statusName", "")
    if "payment_method" in raw:
        for key in ("paymentMethodId", "paymentMethod", "paymentMethodRaw"):
            merged[key] = incoming.get(key, "")
    if "shipping_method" in raw:
        for key in ("shippingMethodId", "shippingMethod", "shippingMethodRaw"):
            merged[key] = incoming.get(key, "")
    if any(k in raw for k in ("userId", "userName", "managerName", "responsibleName", "user", "manager", "responsible")):
        merged["managerId"] = incoming.get("managerId")
        merged["managerName"] = incoming.get("managerName", "")
    if "contacts" in raw:
        merged["contact"] = incoming.get("contact", {})
    if "products" in raw:
        merged["products"] = incoming.get("products", [])
    if "ord_novaposhta" in raw:
        merged["novaposhta"] = incoming.get("novaposhta", {})
    if "ord_ukrposhta" in raw:
        merged["ukrposhta"] = incoming.get("ukrposhta", {})
    if "ord_delivery_data" in raw:
        merged["deliveryData"] = incoming.get("deliveryData", {})

    utm_sources = {
        "page": "utmPage", "medium": "utmMedium", "campaignId": "campaignId",
        "sourceFull": "utmSourceFull", "source": "utmSource", "campaign": "utmCampaign",
    }
    if any(source_key in raw for source_key in utm_sources.values()):
        current_utm = dict(merged.get("utm") or {})
        incoming_utm = incoming.get("utm") or {}
        for target, source_key in utm_sources.items():
            if source_key in raw:
                current_utm[target] = incoming_utm.get(target)
        merged["utm"] = current_utm
    return merged


def _snapshot_age_seconds(order: Order) -> float | None:
    value = getattr(order, "crm_fetched_at", None)
    if not value:
        return None
    now = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0.0, (now - value).total_seconds())


async def pull_order(repo, order_id: int, shop=None, *, force: bool = False, bot=None) -> Order:
    """Читає фактичний стан вже пов'язаної заявки SalesDrive.

    ``force=False`` захищає ліміт ``/api/order/list/`` від фонового polling:
    якщо snapshot щойно читав інший менеджер/вкладка, повертаємо його. Ручна
    кнопка «Оновити з CRM» передає ``force=True``. No-backfill: без crm_id —
    відмова.
    """
    from shop.services import order_workflow as flow
    from shop.services.shop_settings import get_shop_settings
    shop = shop or await get_shop_settings(repo)
    order = await repo.get_order(order_id)
    if not order:
        raise SalesDriveError("Замовлення не знайдено", temporary=False)
    if not order.crm_id:
        raise SalesDriveError("Legacy-замовлення не читається із SalesDrive", temporary=False)
    if not shop.salesdrive_api_connected:
        raise SalesDriveError("Не задано API-ключ SalesDrive", temporary=False)
    age = _snapshot_age_seconds(order)
    if not force and order.crm_snapshot and age is not None and age < ORDER_PULL_MIN_AGE_SECONDS:
        return order

    # У SalesDrive фільтр за ID задається діапазоном id[from]/id[to].
    # Ліміт 1 достатній: ми все одно перевіряємо точний ID після відповіді.
    params = {
        "page": 1, "limit": 1, "filter[statusId]": "__ALL__",
        "filter[id][from]": str(order.crm_id), "filter[id][to]": str(order.crm_id),
    }
    try:
        body = await _get_json(shop, "/api/order/list/", params=params)
    except SalesDriveError as exc:
        # Фоновий refresh у браузері тихий, тому причина має лишитися у
        # самій картці замовлення. Успішне наступне читання очистить її.
        await repo.update_order(order.id, {
            "crm_error": f"Не вдалося оновити дані SalesDrive: {exc}"[:500],
        })
        log.warning(
            "Не вдалося прочитати SalesDrive заявку %s: %s", order.crm_id, exc,
            extra={"event": "salesdrive.pull.failed", "orderId": order.id,
                   "crmId": order.crm_id, "temporary": exc.temporary},
        )
        raise
    rows = _order_list_rows(body)
    row = next((x for x in rows if str(x.get("id") or "") == str(order.crm_id)), None)
    if row is None:
        message = "Пов’язану заявку не знайдено у відповіді SalesDrive"
        await repo.update_order(order.id, {"crm_error": message[:500]})
        log.warning(
            "SalesDrive не повернув пов’язану заявку %s", order.crm_id,
            extra={"event": "salesdrive.pull.missing", "orderId": order.id, "crmId": order.crm_id},
        )
        raise SalesDriveError(message, temporary=False)
    expected_form = telegram_form_id(shop)
    try:
        row_form = int(row.get("formId")) if row.get("formId") not in (None, "") else 0
    except (TypeError, ValueError):
        row_form = 0
    if expected_form > 0 and row_form > 0 and row_form != expected_form:
        message = "Заявка належить іншій базі SalesDrive"
        await repo.update_order(order.id, {"crm_error": message[:500]})
        log.warning(
            "SalesDrive заявка %s має formId=%s замість очікуваного %s",
            order.crm_id, row_form, expected_form,
            extra={"event": "salesdrive.pull.form_mismatch", "orderId": order.id,
                   "crmId": order.crm_id, "formId": row_form, "expectedFormId": expected_form},
        )
        raise SalesDriveError(message, temporary=False)

    # Спочатку використовуємо вже прогріті довідники + meta[fields] із самої
    # відповіді order-list. Це часто дозволяє обійтися одним HTTP-запитом.
    # Повні довідники довантажуємо лише якщо числове значення/статус лишилися
    # нерозв'язаними. Так відкриття картки не породжує 4 запити до CRM.
    bundle = cached_dictionary_bundle(shop)
    status_names = _option_map(bundle.get("statuses", []))
    snap = _snapshot(row, status_names, payments=bundle.get("payments", []),
                     deliveries=bundle.get("deliveries", []), body=body, source="api")

    unresolved_payment = (str(snap.get("paymentMethodRaw") or "").isdigit() and
                          snap.get("paymentMethod") == snap.get("paymentMethodRaw"))
    unresolved_delivery = (str(snap.get("shippingMethodRaw") or "").isdigit() and
                           snap.get("shippingMethod") == snap.get("shippingMethodRaw"))
    unresolved_status = bool(snap.get("statusId") and not snap.get("statusName"))
    if unresolved_payment or unresolved_delivery or unresolved_status:
        try:
            bundle = await dictionary_bundle(shop)
            status_names = _option_map(bundle.get("statuses", []))
            snap = _snapshot(row, status_names, payments=bundle.get("payments", []),
                             deliveries=bundle.get("deliveries", []), body=body, source="api")
        except SalesDriveError:
            # Read-side заявки цінніший за підпис опції: при тимчасовій
            # недоступності довідників не втрачаємо сам snapshot.
            pass
    now = datetime.now(timezone.utc)
    patch = {"crm_snapshot": snap, "crm_fetched_at": now, "crm_synced_at": now, "crm_error": None}
    if snap.get("statusId"):
        patch["crm_status_id"] = snap["statusId"]
        # Якщо назву не вдалося розв'язати, очищаємо старий підпис, а не
        # показуємо його поруч із новим ID.
        patch["crm_status_name"] = snap.get("statusName") or None
    await repo.update_order(order.id, patch)
    order = await repo.get_order(order.id) or order

    # ТТН із SalesDrive — не декоративне поле snapshot. Вона має стати
    # єдиною накладною замовлення разом із ENref і вартістю доставки.
    # Якщо ТТН було видалено саме в CRM, прибираємо локальну копію тільки
    # коли її джерело теж SalesDrive: номер, створений у нашій панелі, не
    # можна стерти через тимчасово порожню відповідь CRM.
    np_snap = snap.get("novaposhta") or {}
    up_snap = snap.get("ukrposhta") or {}
    ttn = str(np_snap.get("ttn") or up_snap.get("ttn") or "").strip()
    ref = str(np_snap.get("ref") or up_snap.get("ref") or "").strip()
    crm_cost = np_snap.get("cost") if np_snap.get("cost") not in (None, "") else up_snap.get("cost")
    cost = None
    if crm_cost not in (None, ""):
        try:
            cost = Decimal(str(crm_cost))
        except (ArithmeticError, ValueError):
            cost = None

    if ttn:
        await flow.apply_tracking(
            repo, order, ttn, origin=flow.ORIGIN_SALESDRIVE, bot=None,
            ref=ref, source=flow.SOURCE_SALESDRIVE, cost=cost,
        )
        order = await repo.get_order(order.id) or order
    elif order.waybill_source == flow.SOURCE_SALESDRIVE and order.tracking_number:
        await flow.apply_tracking(repo, order, "", origin=flow.ORIGIN_SALESDRIVE, bot=None)
        order = await repo.get_order(order.id) or order

    # Якщо webhook загубився, пряме читання заявки все одно наздожене
    # локальний workflow. Пізніший CRM-статус означає, що попередні етапи
    # вже пройдені; проміжні кроки застосовуються послідовно.
    target = status_from_crm(shop, snap.get("statusId"))
    if target and target != order.status:
        try:
            await flow.apply_crm_status_progression(repo, order, target, bot=bot)
            order = await repo.get_order(order.id) or order
        except flow.WorkflowError as exc:
            await repo.update_order(order.id, {
                "crm_error": f"Статус із SalesDrive прочитано, але локальний workflow не наздогнано: {exc}"[:500],
            })
            order = await repo.get_order(order.id) or order
    return order

async def set_crm_status(repo, order: Order, status_id: str, status_name: str | None = None, shop=None, *, bot=None) -> Order:
    """Змінює авторитетний статус прямо в SalesDrive.

    ``status_name`` лишено тільки для сумісності зі старими клієнтами й
    навмисно НЕ довіряємо йому. ID перевіряється за актуальним довідником
    CRM, а назву сервер бере звідти ж. Так браузер не може записати
    неіснуючий/застарілий підпис статусу.
    """
    from shop.services import order_workflow as flow
    from shop.services.shop_settings import get_shop_settings
    shop = shop or await get_shop_settings(repo)
    if not order.crm_id:
        raise SalesDriveError("Замовлення не пов’язане із SalesDrive", temporary=False)
    sid = str(status_id or "").strip()
    if not sid:
        raise SalesDriveError("Некоректний статус SalesDrive", temporary=False)

    options = await status_options(shop)
    name = status_name_from_options(sid, options)
    if not name:
        raise SalesDriveError("Статус більше не існує в SalesDrive — оновіть список статусів", temporary=False)

    await _send(shop, "/api/order/update/", {
        "form": shop.salesdrive_form_key,
        "id": order.crm_id,
        "data": {"statusId": sid},
    })

    now = datetime.now(timezone.utc)
    patch = {
        "crm_status_id": sid, "crm_status_name": name,
        "crm_state": STATE_SYNCED, "crm_error": None, "crm_synced_at": now,
    }
    # Не залишаємо в read-model стару назву до наступного pull/webhook.
    if isinstance(order.crm_snapshot, dict):
        snapshot = dict(order.crm_snapshot)
        snapshot["statusId"] = sid
        snapshot["statusName"] = name
        patch["crm_snapshot"] = snapshot
        patch["crm_fetched_at"] = now
    await repo.update_order(order.id, patch)
    fresh = await repo.get_order(order.id) or order

    # Не чекаємо webhook, щоб локальні лічильники/бонуси/етапи одразу
    # відповідали статусу, який менеджер щойно встановив у CRM. Повторний
    # webhook ідемпотентний і вже нічого не дублює.
    target = status_from_crm(shop, sid)
    if target and target != fresh.status:
        try:
            await flow.apply_crm_status_progression(repo, fresh, target, bot=bot)
        except flow.WorkflowError as exc:
            await repo.update_order(order.id, {
                "crm_error": f"Статус у SalesDrive змінено, але локальний workflow не наздогнано: {exc}"[:500],
            })
    return await repo.get_order(order.id) or fresh
