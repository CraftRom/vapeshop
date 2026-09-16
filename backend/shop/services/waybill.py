"""Формування ТТН Нової пошти з панелі.

Накладна — одна на замовлення, і живе вона в тих самих полях, що й номер,
вписаний руками чи отриманий із SalesDrive (tracking_number, waybill_ref,
waybill_source). Після створення номер проходить order_workflow.apply_tracking
— тим самим шляхом, що й будь-яка інша зміна накладної: клієнт отримує
повідомлення за тими ж правилами, а SalesDrive — оновлення заявки.

HTTP-клієнт Нової пошти спільний із довідником (novaposhta._call): ключ,
тайм-аути, розбір помилок і журнал однакові для підказок у вітрині й для
накладних.

Що свідомо не робимо:
  - курʼєрську ТТН. Для неї перевізнику потрібні коди вулиці й будинку, а
    покупець вписує адресу текстом. Вгадувати вулицю за рядком — значить
    рано чи пізно відправити посилку не туди. Таку ТТН менеджер створює в
    кабінеті перевізника або в SalesDrive і вписує номер;
  - друк через посилання з ключем у адресі. Кабінет Нової пошти віддає
    PDF за URL із apiKey, і відкрити його в браузері означало б показати
    ключ кожному, хто подивиться історію чи мережеві запити. PDF тягне сервер.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from shop.entities import Order, OrderStatus
from shop.services import novaposhta, shipment

log = logging.getLogger(__name__)

PRINT_URL = "https://my.novaposhta.ua/orders/printMarking100x100/orders[]/{number}/type/pdf/apiKey/{key}"

# Статуси, у яких ТТН ще доречно створювати. Для скасованого чи виконаного
# замовлення нова накладна — майже напевно помилковий клік.
CREATABLE_FROM = (OrderStatus.CONFIRMED, OrderStatus.ACCEPTED, OrderStatus.PAID)


class WaybillError(Exception):
    """ТТН неможливо створити чи видалити. Текст — для менеджера."""


@dataclass
class Sender:
    counterparty_ref: str
    contact_ref: str
    phone: str
    city_ref: str
    warehouse_ref: str


@dataclass
class Created:
    number: str
    ref: str
    cost: Decimal | None
    estimated_delivery: str


_sender_cache: dict[str, Sender] = {}


def reset_sender_cache() -> None:
    """Скидається зі зміною ключа: інший ключ — інший кабінет і відправник."""
    _sender_cache.clear()


def readiness(order: Order, shop) -> str | None:
    """Чому ТТН створити не можна. None — можна.

    Перевіряється до першого звернення до перевізника: відмова з поясненням
    «що саме заповнити» корисніша за «Нова пошта відмовила: ...».
    """
    if not shop.novaposhta_connected:
        return "Не задано ключ API Нової пошти (Налаштування → Доставка)"
    missing = [label for label, value in (
        ("місто відправлення", shop.novaposhta_sender_city),
        ("відділення відправлення", shop.novaposhta_sender_warehouse_ref),
        ("телефон відправника", shop.novaposhta_sender_phone),
    ) if not (value or "").strip()]
    if missing:
        return "У налаштуваннях доставки не заповнено: " + ", ".join(missing)
    if order.tracking_number:
        return "У замовлення вже є накладна. Щоб створити нову, спершу приберіть поточну"
    if order.status not in CREATABLE_FROM:
        return "Накладну створюють для підтвердженого, прийнятого чи оплаченого замовлення"
    where = shipment.destination(order)
    if where.to_door:
        return ("Курʼєрську накладну створіть у кабінеті Нової пошти чи в SalesDrive "
                "і впишіть номер: адресу покупець указав текстом, без кодів вулиці")
    if not where.city_ref or not where.warehouse_ref:
        return ("Відділення вписане руками, без коду довідника. Створіть накладну в "
                "кабінеті перевізника й впишіть номер")
    person = shipment.recipient(order)
    if not person.last_name or not person.first_name:
        return "Для накладної потрібні прізвище та імʼя отримувача"
    if len(person.phone) != 12:
        return "Телефон отримувача має бути у форматі +380XXXXXXXXX"
    return None


async def _sender(shop) -> Sender:
    key = shop.novaposhta_api_key
    cached = _sender_cache.get(key)
    if cached and cached.warehouse_ref == shop.novaposhta_sender_warehouse_ref:
        return cached
    rows = await novaposhta._call(key, "Counterparty", "getCounterparties",
                                  {"CounterpartyProperty": "Sender", "Page": "1"})
    if not rows:
        raise WaybillError("У кабінеті Нової пошти не знайдено відправника для цього ключа")
    counterparty = (rows[0].get("Ref") or "").strip()
    contacts = await novaposhta._call(key, "Counterparty", "getCounterpartyContactPersons",
                                      {"Ref": counterparty, "Page": "1"})
    if not contacts:
        raise WaybillError("У відправника в кабінеті Нової пошти немає контактної особи")
    city_ref = await novaposhta.city_ref_by_name(key, shop.novaposhta_sender_city)
    if not city_ref:
        raise WaybillError(f"Місто відправлення «{shop.novaposhta_sender_city}» не знайдено в довіднику")
    found = Sender(
        counterparty_ref=counterparty,
        contact_ref=(contacts[0].get("Ref") or "").strip(),
        phone=shipment.phone_digits(shop.novaposhta_sender_phone),
        city_ref=city_ref,
        warehouse_ref=shop.novaposhta_sender_warehouse_ref.strip(),
    )
    _sender_cache[key] = found
    return found


def document_properties(order: Order, shop, sender: Sender, recipient_ref: str,
                        contact_ref: str, today: datetime | None = None) -> dict:
    """Тіло InternetDocument.save. Окремою функцією — щоб перевіряти без мережі."""
    person = shipment.recipient(order)
    where = shipment.destination(order)
    box = shipment.parcel(order, shop)
    props = {
        "PayerType": "Recipient",
        "PaymentMethod": "Cash",
        "DateTime": (today or datetime.now()).strftime("%d.%m.%Y"),
        "CargoType": "Parcel",
        "Weight": shipment.money(box.weight_kg),
        "ServiceType": "WarehouseWarehouse",
        "SeatsAmount": str(box.seats),
        "Description": box.description,
        "Cost": shipment.money(box.declared_cost),
        "CitySender": sender.city_ref,
        "Sender": sender.counterparty_ref,
        "SenderAddress": sender.warehouse_ref,
        "ContactSender": sender.contact_ref,
        "SendersPhone": sender.phone,
        "CityRecipient": where.city_ref,
        "Recipient": recipient_ref,
        "RecipientAddress": where.warehouse_ref,
        "ContactRecipient": contact_ref,
        "RecipientsPhone": person.phone,
        "InfoRegClientBarcodes": str(order.id),
    }
    if box.is_cod:
        # Накладений платіж: гроші повертаються відправнику, доставку
        # грошей оплачує отримувач — так само, як обіцяє вітрина.
        props["BackwardDeliveryData"] = [{
            "PayerType": "Recipient",
            "CargoType": "Money",
            "RedeliveryString": shipment.money(box.cod_amount),
        }]
    return props


async def create(repo, order: Order, shop, *, bot=None) -> Created:
    """Створює ТТН і записує її в замовлення спільним шляхом."""
    problem = readiness(order, shop)
    if problem:
        raise WaybillError(problem)
    key = shop.novaposhta_api_key
    person = shipment.recipient(order)
    try:
        sender = await _sender(shop)
        saved = await novaposhta._call(key, "Counterparty", "save", {
            "FirstName": person.first_name,
            "MiddleName": person.middle_name,
            "LastName": person.last_name,
            "Phone": person.phone,
            "Email": "",
            "CounterpartyType": "PrivatePerson",
            "CounterpartyProperty": "Recipient",
        })
        if not saved:
            raise WaybillError("Нова пошта не зберегла отримувача")
        recipient_ref = (saved[0].get("Ref") or "").strip()
        contact_rows = ((saved[0].get("ContactPerson") or {}).get("data") or [])
        contact_ref = (contact_rows[0].get("Ref") or "").strip() if contact_rows else ""
        if not recipient_ref or not contact_ref:
            raise WaybillError("Нова пошта не повернула коди отримувача")

        rows = await novaposhta._call(key, "InternetDocument", "save", document_properties(
            order, shop, sender, recipient_ref, contact_ref))
    except novaposhta.NovaPoshtaError as exc:
        raise WaybillError(str(exc)) from exc
    if not rows:
        raise WaybillError("Нова пошта не повернула накладну")
    row = rows[0]
    number = (row.get("IntDocNumber") or "").strip()
    ref = (row.get("Ref") or "").strip()
    if not number:
        raise WaybillError("Нова пошта не повернула номер накладної")
    try:
        cost = Decimal(str(row.get("CostOnSite"))) if row.get("CostOnSite") not in (None, "") else None
    except ArithmeticError:
        cost = None

    from shop.services import order_workflow as flow
    await flow.apply_tracking(repo, order, number, origin=flow.ORIGIN_WAYBILL, bot=bot,
                              ref=ref, source=flow.SOURCE_NOVAPOSHTA, cost=cost)
    log.info("Створено ТТН %s для замовлення %s", number, order.id,
             extra={"event": "waybill.created", "orderId": order.id, "number": number})
    return Created(number=number, ref=ref, cost=cost,
                   estimated_delivery=(row.get("EstimatedDeliveryDate") or "").strip())


async def delete(repo, order: Order, shop, *, bot=None) -> None:
    """Видаляє ТТН у Новій пошті й прибирає її із замовлення.

    Лише створену звідси: номер, вписаний руками чи прийнятий із CRM, ми не
    видавали — і стирати його в перевізника не маємо права.
    """
    from shop.services import order_workflow as flow
    if not order.tracking_number:
        raise WaybillError("У замовлення немає накладної")
    if order.waybill_source != flow.SOURCE_NOVAPOSHTA or not order.waybill_ref:
        raise WaybillError("Цю накладну створено не з панелі. Видаліть її там, де створили, "
                           "і приберіть номер із замовлення")
    if order.status in (OrderStatus.SHIPPED, OrderStatus.DONE):
        raise WaybillError("Замовлення вже відправлене — накладну не видаляють")
    try:
        await novaposhta._call(shop.novaposhta_api_key, "InternetDocument", "delete",
                               {"DocumentRefs": order.waybill_ref})
    except novaposhta.NovaPoshtaError as exc:
        raise WaybillError(str(exc)) from exc
    await flow.apply_tracking(repo, order, "", origin=flow.ORIGIN_WAYBILL, bot=bot)
    log.info("Видалено ТТН %s замовлення %s", order.tracking_number, order.id,
             extra={"event": "waybill.deleted", "orderId": order.id})


async def label_pdf(order: Order, shop) -> bytes:
    """Маркування 100×100 у PDF. Ключ лишається на сервері."""
    import httpx
    if not order.tracking_number or order.waybill_source != "novaposhta":
        raise WaybillError("Друк доступний для накладної, створеної з панелі")
    url = PRINT_URL.format(number=order.tracking_number, key=shop.novaposhta_api_key)
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        # Адресу не пишемо в журнал: у ній ключ.
        log.warning("waybill.print.failed order=%s: %s", order.id, type(exc).__name__)
        raise WaybillError("Нова пошта не віддала маркування") from exc
    if not response.content.startswith(b"%PDF"):
        raise WaybillError("Нова пошта повернула не PDF — перевірте ключ і номер накладної")
    return response.content
