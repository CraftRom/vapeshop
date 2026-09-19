from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from api.schemas import SalesDriveOrderPatch
from shop.services import salesdrive


class Order:
    id = 54
    crm_id = "6387"


order = Order()

payload = salesdrive.crm_update_payload(order, {"statusId": 5})
assert payload == {"id": 6387, "data": {"statusId": 5}}, payload
print("✓ order-update uses id + data only")
assert "form" not in payload
print("✓ /api/order/update does not leak /handler form")

external = SimpleNamespace(id=54, crm_id=None)
payload = salesdrive.crm_update_payload(external, {"comment": "ok"})
assert payload == {"externalId": "54", "data": {"comment": "ok"}}, payload
print("✓ externalId fallback is supported")

changes = {
    "manager_id": 3,
    "payment_date": "25.08.2025",
    "rejection_reason_id": 393,
    "comment": "коментар",
    "payment_method": "card",
    "shipping_method": "novaposhta",
    "l_name": "Шевчук", "f_name": "Петро", "m_name": "Іванович",
    "phone": "0501112233", "email": "user@example.com", "company": "Компанія",
    "counterparty_name": 'ТОВ "Компанія"', "counterparty_code": "12345678",
    "date_of_birth": "28.02.1986",
    "carrier": "novaposhta", "tracking_number": "20451540075558",
    "products": [{
        "id": "123", "name": "Ноутбук Lenovo", "cost_per_item": Decimal("500"),
        "amount": Decimal("2"), "discount": "10%", "sku": "ABC-123",
        "commission": "10%", "stock_id": 1, "upsell": 1,
    }],
    "products_mode": "replace",
}
data = salesdrive.explicit_update_data(changes)
assert data["salesdrive_manager"] == 3
assert data["paymentDate"] == "25.08.2025"
assert data["rejectionReasonId"] == 393
assert data["counterparty"] == {"name": 'ТОВ "Компанія"', "code": "12345678"}
assert data["novaposhta"] == {"ttn": "20451540075558"}
assert data["productsMode"] == "replace"
assert data["products"][0]["costPerItem"] == 500 and data["products"][0]["amount"] == 2
print("✓ documented editable fields map to exact SalesDrive names")

assert not any(k in data for k in ("shipping_address", "city", "branch", "warehouse", "address"))
print("✓ forbidden carrier address fields are not writable")

snapshot = {
    "managerId": 3, "paymentDate": "2025-08-25", "comment": "коментар",
    "paymentMethodRaw": "card", "shippingMethodRaw": "novaposhta",
    "rejectionReasonId": 393,
    "contact": {"lName": "Шевчук", "fName": "Петро", "mName": "Іванович",
                "phone": "0501112233", "email": "user@example.com", "company": "Компанія",
                "dateOfBirth": "1986-02-28",
                "counterparty": {"name": 'ТОВ "Компанія"', "code": "12345678"}},
    "novaposhta": {"ttn": "20451540075558"},
}
without_products = {k: v for k, v in changes.items() if k not in {"products", "products_mode"}}
assert salesdrive._snapshot_confirms_update(snapshot, without_products)
print("✓ timed-out partial write can be verified by authoritative GET")
assert not salesdrive._snapshot_confirms_update(snapshot, changes)
print("✓ product replace is never assumed successful after timeout")

schema = SalesDriveOrderPatch(comment="x")
assert schema.comment == "x"
print("✓ partial update accepts one field")

try:
    SalesDriveOrderPatch(payment_date="2025-08-25")
except Exception:
    print("✓ SalesDrive dates require DD.MM.YYYY")
else:
    raise AssertionError("invalid date accepted")

try:
    SalesDriveOrderPatch(carrier="novaposhta")
except Exception:
    print("✓ carrier and TTN must be sent together")
else:
    raise AssertionError("carrier without TTN accepted")

try:
    SalesDriveOrderPatch(tracking_number="123")
except Exception:
    print("✓ TTN and carrier must be sent together")
else:
    raise AssertionError("TTN without carrier accepted")

source = Path("shop/services/salesdrive.py").read_text()
router = Path("api/routers/orders.py").read_text()
ui = Path("../dashboard/src/pages/OrderPage.jsx").read_text()
api = Path("../dashboard/src/api.js").read_text()
assert 'path == "/handler/" and telegram_form_id(shop) <= 0' in source
assert 'path.startswith("/api/") and not getattr(shop, "salesdrive_api_connected", False)' in source
print("✓ write auth distinguishes /handler from API update")
assert '@router.patch("/{order_id}/salesdrive"' in router and "update_crm_order" in router
print("✓ staff partial CRM update endpoint exists")
assert "salesdriveUpdate" in api and "Редагувати дані SalesDrive" in ui
print("✓ dashboard has direct CRM editor")
assert "Місто, відділення та адресу" in ui
print("✓ UI explains carrier address restriction")

print("SalesDrive order-update QA: 15/15")
