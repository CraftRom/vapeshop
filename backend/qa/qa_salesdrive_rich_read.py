"""Regression: rich SalesDrive read model and safe API compatibility."""
import asyncio
import time
from types import SimpleNamespace

from shop.entities import Order
from shop.services import salesdrive

body = {
    "meta": {
        "fields": {
            "statusId": {"options": [{"id": 2, "name": "Підтверджено"}]},
            "payment_method": {"options": [{"id": 56, "name": "Накладений платіж"}]},
            "shipping_method": {"options": [{"id": 57, "name": "Нова Пошта"}]},
            "userId": {"options": [{"id": 8, "name": "Олена Менеджер"}]},
        }
    }
}
row = {
    "id": 6343, "externalId": "53", "version": 7, "formId": 4242,
    "statusId": 2, "payment_method": 56, "shipping_method": 57, "userId": 8,
    "paymentAmount": "880", "payedAmount": "200", "restPay": "680",
    "products": [{
        "id": 1, "productId": 9, "name": "Товар", "sku": "SKU-1", "amount": 1,
        "price": "880", "costPrice": "400", "upsell": 1,
        "defaultPriceData": {"price": 900}, "priceTypes": [{"id": 1}],
        "complect": [{"productId": 99}],
    }],
    "contacts": [{
        "id": 4, "fName": "Ганна", "lName": "Слюсар", "phone": "380997243892",
        "leadsCount": 3, "leadsSalesCount": 2, "leadsSalesAmount": "1760",
        "counterparty": {"id": 3, "name": "Ганна", "code": ""},
    }],
    "ord_novaposhta": {
        "delivery": "WarehouseWarehouse", "branchNumber": "5", "EN": "20450000123456",
        "status": "Відправлення у відділенні", "postpaySum": "680", "cargoType": "Parcel",
        "cost": "85",
    },
    "ord_delivery_data": {"paymentMethod": "Cash", "postpayPayer": "Recipient", "cargoType": "Parcel"},
    "utmSource": "telegram", "utmCampaign": "autumn",
}

snap = salesdrive._snapshot(row, body=body)
checks = {
    "status name from meta": snap["statusName"] == "Підтверджено",
    "payment ID resolved": snap["paymentMethodId"] == "56" and snap["paymentMethod"] == "Накладений платіж",
    "delivery ID resolved": snap["shippingMethodId"] == "57" and snap["shippingMethod"] == "Нова Пошта",
    "manager from meta": snap["managerId"] == 8 and snap["managerName"] == "Олена Менеджер",
    "financials preserved": snap["paymentAmount"] == "880" and snap["restPay"] == "680",
    "contact history preserved": snap["contact"]["leadsSalesAmount"] == "1760",
    "new product fields": snap["products"][0]["upsell"] == 1 and snap["products"][0]["defaultPriceData"]["price"] == 900,
    "nova poshta details": snap["novaposhta"]["ttn"] == "20450000123456" and snap["novaposhta"]["postpaySum"] == "680",
    "delivery data fields": snap["deliveryData"]["paymentMethod"] == "Cash" and snap["deliveryData"]["cargoType"] == "Parcel",
    "utm preserved": snap["utm"]["source"] == "telegram" and snap["utm"]["campaign"] == "autumn",
}

previous = {**snap, "managerName": "Олена Менеджер", "products": [{"name": "Повний товар", "defaultPriceData": {"price": 900}}]}
partial = salesdrive._snapshot({"id": 6343, "statusId": 3}, {"3": "Відправлений"}, source="webhook")
merged = salesdrive._merge_webhook_snapshot(previous, partial, {"id": 6343, "statusId": 3})
checks.update({
    "partial webhook keeps rich products": merged["products"][0]["name"] == "Повний товар",
    "partial webhook updates status": merged["statusId"] == "3" and merged["statusName"] == "Відправлений",
    "partial webhook keeps manager": merged["managerName"] == "Олена Менеджер",
    "webhook source visible": merged["source"] == "webhook",
})

shop = SimpleNamespace(
    salesdrive_api_connected=True, salesdrive_api_key="api-key", salesdrive_domain="elfar",
)
headers = salesdrive._headers(shop)
warehouse_order = Order(id=1, user_id=1, delivery_method="warehouse", delivery_city_ref="city-ref", delivery_warehouse_ref="wh-ref")
courier_order = Order(id=2, user_id=1, delivery_method="courier", delivery_city_ref="city-ref", delivery_address="вул. Тестова, 1")
warehouse_np = salesdrive._novaposhta_block(warehouse_order)
courier_np = salesdrive._novaposhta_block(courier_order)
checks.update({
    "current API auth header": headers.get("X-Api-Key") == "api-key",
    "legacy auth header retained": headers.get("Form-Api-Key") == "api-key",
    "SalesDrive warehouse service type": warehouse_np.get("ServiceType") == "Warehouse" and warehouse_np.get("WarehouseNumber") == "wh-ref",
    "courier route remains explicit": courier_np.get("ServiceType") == "WarehouseDoors" and "WarehouseNumber" not in courier_np,
})

# force-refresh/health checks must never be satisfied by a stale cache.
async def force_cache_check():
    key = salesdrive._cache_key(shop)
    salesdrive._status_cache[key] = {"stored": time.monotonic() - 99999, "value": [{"id": "1", "name": "Old"}]}
    original = salesdrive._get_json
    async def fail(*args, **kwargs):
        raise salesdrive.SalesDriveError("offline")
    salesdrive._get_json = fail
    try:
        try:
            await salesdrive.status_options(shop, force=True)
        except salesdrive.SalesDriveError:
            return True
        return False
    finally:
        salesdrive._get_json = original

checks["force refresh does not hide outage behind stale cache"] = asyncio.run(force_cache_check())

for label, ok in checks.items():
    print(("✓" if ok else "✗"), label)
assert all(checks.values())
print(f"✓ SalesDrive rich read: {len(checks)}/{len(checks)}")
