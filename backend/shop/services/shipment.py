"""Отримувач і посилка — один опис для SalesDrive і Нової пошти.

Заявка в CRM і накладна перевізника описують те саме: хто отримує, куди
везти, що в посилці, скільки коштує й чи є накладений платіж. Якщо кожна
інтеграція збирає це по-своєму, розбіжності неминучі: CRM показує одне
імʼя, ТТН — інше; в одній сума з урахуванням бонусів, у другій без.

Тому з замовлення ці дані складаються один раз, тут, а інтеграції лише
перекладають готову структуру у формат свого API.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from shop.entities import Order

METHOD_WAREHOUSE = "warehouse"
METHOD_COURIER = "courier"
PAYMENT_CARD = "card"
PAYMENT_COD = "cod"

# Нижня межа ваги для Нової пошти. Нуль перевізник не приймає, а
# позиція без ваги в каталозі — звичайна справа.
MIN_WEIGHT_KG = Decimal("0.1")


@dataclass(frozen=True)
class Recipient:
    last_name: str
    first_name: str
    middle_name: str
    phone: str
    full_name: str


@dataclass(frozen=True)
class Destination:
    method: str            # warehouse | courier
    city: str              # текст, як бачив покупець
    address: str           # відділення або адреса текстом
    city_ref: str          # код довідника Нової пошти (може бути порожнім)
    warehouse_ref: str     # код відділення (порожньо для курʼєра)

    @property
    def to_door(self) -> bool:
        return self.method == METHOD_COURIER

    @property
    def text(self) -> str:
        return ", ".join(p for p in (self.city, self.address) if p)


@dataclass(frozen=True)
class Parcel:
    description: str
    weight_kg: Decimal
    declared_cost: Decimal     # оголошена вартість = сума до сплати
    cod_amount: Decimal        # 0 — без накладеного платежу
    seats: int = 1

    @property
    def is_cod(self) -> bool:
        return self.cod_amount > 0


def phone_digits(value: str | None) -> str:
    """Телефон у форматі 380XXXXXXXXX, як його чекають обидва API."""
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) == 10 and digits.startswith("0"):
        digits = "38" + digits
    return digits


def recipient(order: Order) -> Recipient:
    """ПІБ складовими.

    Складові зберігаються окремо з появою трьох полів у формі. Імʼя окремо
    не зберігалось ніколи: contact_name — повний ПІБ одним рядком. Тому
    імʼя дістаємо відніманням прізвища й по батькові з повного рядка, а для
    старих замовлень без складових — розбором «Прізвище Імʼя По батькові».
    """
    full = " ".join((order.contact_name or "").split())
    surname = (order.contact_surname or "").strip()
    patronymic = (order.contact_patronymic or "").strip()
    if surname or patronymic:
        rest = full
        if surname and rest.startswith(surname):
            rest = rest[len(surname):].strip()
        if patronymic and rest.endswith(patronymic):
            rest = rest[: len(rest) - len(patronymic)].strip()
        first = rest
    else:
        parts = full.split(" ")
        surname = parts[0] if len(parts) > 1 else ""
        first = parts[1] if len(parts) > 1 else (parts[0] if parts else "")
        patronymic = " ".join(parts[2:]) if len(parts) > 2 else ""
    return Recipient(
        last_name=surname, first_name=first, middle_name=patronymic,
        phone=phone_digits(order.contact_phone), full_name=full,
    )


def destination(order: Order) -> Destination:
    return Destination(
        method=order.delivery_method or METHOD_WAREHOUSE,
        city=(order.delivery_city or "").strip(),
        address=(order.delivery_address or "").strip(),
        city_ref=(order.delivery_city_ref or "").strip(),
        warehouse_ref=(order.delivery_warehouse_ref or "").strip(),
    )


def parcel(order: Order, shop) -> Parcel:
    """Посилка за замовленням і налаштуваннями магазину.

    Вага — припущена (кількість позицій × вага позиції з налаштувань):
    точної ваги в каталозі немає, а перевізник однаково переважить на
    відділенні. Оголошена вартість — сума до сплати, а не сума кошика:
    саме її покупець віддає, і саме на неї має бути страховка.
    """
    items = sum(line.qty for line in order.items) or 1
    per_item = Decimal(str(getattr(shop, "delivery_weight_per_item", 0) or 0))
    weight = max(MIN_WEIGHT_KG, (per_item * items).quantize(Decimal("0.01"), ROUND_HALF_UP))
    total = Decimal(order.total or 0).quantize(Decimal("0.01"))
    return Parcel(
        description=(getattr(shop, "novaposhta_cargo_description", "") or "Товари").strip()[:100],
        weight_kg=weight,
        declared_cost=total,
        cod_amount=total if order.payment_method == PAYMENT_COD else Decimal(0),
    )


def money(value: Decimal | int | float | str | None) -> str:
    """Сума рядком без зайвих нулів: «349», «349.5»."""
    amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    text = format(amount.normalize(), "f")
    return text
