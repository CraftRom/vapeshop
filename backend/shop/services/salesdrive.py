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
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from shop.entities import Order, OrderStatus
from shop.services import shipment
from shop.config import settings

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20.0
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



def telegram_source_id() -> int:
    """Єдина дозволена база заявок SalesDrive для Telegram-магазину.

    ID навмисно береться тільки з ENV, а не з панелі/локальної БД: оператор
    не може випадково перемкнути інтеграцію на іншу базу під час роботи.
    Значення 0 означає fail-closed — жодних записів у SalesDrive.
    """
    return int(settings.salesdrive_telegram_source_id or 0)


def source_matches(payload: dict, shop) -> bool:
    """Webhook належить саме нашому акаунту і базі «ELFAR — Telegram Bot»."""
    expected = telegram_source_id()
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
    """Дані Нової пошти в заявці. Коди — ті самі, що зберігає вітрина."""
    where = shipment.destination(order)
    block = {
        "ServiceType": "WarehouseDoors" if where.to_door else "WarehouseWarehouse",
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
    if order.payment_method and payments.get(order.payment_method):
        payload["payment_method"] = payments[order.payment_method]
    if shippings.get(where.method):
        payload["shipping_method"] = shippings[where.method]
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
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if shop.salesdrive_api_connected:
        headers["Form-Api-Key"] = shop.salesdrive_api_key
    return headers


async def _send(shop, path: str, payload: dict) -> dict:
    if telegram_source_id() <= 0:
        raise SalesDriveError("SALESDRIVE_TELEGRAM_SOURCE_ID не задано; запис у SalesDrive заблоковано", temporary=False)
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
    """Номер заявки з відповіді на створення. Формат відповіді в базі
    знань не описаний, тож шукаємо в очевидних місцях і не вгадуємо далі."""
    for container in (body.get("data") if isinstance(body.get("data"), dict) else {}, body):
        for key in ("orderId", "id", "order_id"):
            value = container.get(key)
            if value not in (None, "", 0):
                return str(value)
    return None


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
    await _mark(repo, order, STATE_SYNCED, crm_id=crm_id)
    log.info("Замовлення %s створено в SalesDrive як %s", order.id, crm_id or "—",
             extra={"event": "salesdrive.order.created", "orderId": order.id,
                    "crmId": crm_id})
    return STATE_SYNCED


async def _mark(repo, order: Order, state: str, crm_id: str | None = None) -> None:
    patch = {"crm_state": state, "crm_error": None, "crm_attempts": 0,
             "crm_synced_at": datetime.now(timezone.utc)}
    if crm_id and not order.crm_id:
        patch["crm_id"] = crm_id
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
    np_block = data.get("ord_novaposhta") if isinstance(data.get("ord_novaposhta"), dict) else {}
    number = str(np_block.get("EN") or "").strip()
    if number:
        cost = None
        try:
            if np_block.get("cost") not in (None, ""):
                cost = Decimal(str(np_block.get("cost")))
        except ArithmeticError:
            cost = None
        return number, (str(np_block.get("ENref") or "").strip() or None), cost
    up_block = data.get("ord_ukrposhta") if isinstance(data.get("ord_ukrposhta"), dict) else {}
    return str(up_block.get("barcode") or "").strip(), None, None


async def handle_webhook(repo, payload: dict, *, bot=None) -> dict:
    """Застосовує зміну з SalesDrive до замовлення Elfar."""
    from shop.services import order_workflow as flow
    from shop.services.shop_settings import get_shop_settings

    shop = await get_shop_settings(repo)
    if not source_matches(payload, shop):
        log.warning("Webhook SalesDrive відхилено: інша або невідома база заявок",
                    extra={"event": "salesdrive.webhook.wrong_source",
                           "expectedFormId": telegram_source_id()})
        return {"result": "ignored", "reason": "інша база заявок SalesDrive"}
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    event = str(info.get("webhookEvent") or "")
    crm_id = str(data.get("id") or "").strip()

    order = await repo.find_order_by_crm_id(crm_id) if crm_id else None
    external = str(data.get("externalId") or "").strip()
    if not order and external.isdigit():
        order = await repo.get_order(int(external))
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
    if number and number != (order.tracking_number or ""):
        await flow.apply_tracking(repo, order, number, origin=flow.ORIGIN_SALESDRIVE, bot=bot,
                                  ref=ref or "", source=flow.SOURCE_SALESDRIVE, cost=cost)
        order = await repo.get_order(order.id) or order
        applied.append("tracking")

    target = status_from_crm(shop, data.get("statusId"))
    if target and target != order.status:
        try:
            await flow.apply_status(repo, order, target, origin=flow.ORIGIN_SALESDRIVE, bot=bot)
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
