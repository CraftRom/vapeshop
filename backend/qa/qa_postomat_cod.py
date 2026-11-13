"""Regression: постомат/поштомат + COD remains a valid shipment.

PYTHONPATH=backend python3 backend/qa/qa_postomat_cod.py
"""
from decimal import Decimal
from types import SimpleNamespace

from shop.services.shipment import destination, parcel

shop = SimpleNamespace(delivery_weight_per_item=1, novaposhta_cargo_description="Товари")
count = 0
for address, payment_method, expected in (
    ("Поштомат №26", "cod", Decimal("199.90")),
    ("Поштомат №26", "card", Decimal("0")),
    ("Відділення №1", "cod", Decimal("199.90")),
):
    order = SimpleNamespace(
        delivery_method="warehouse", delivery_city="Рівне",
        delivery_address=address, delivery_city_ref="city-ref",
        delivery_warehouse_ref="warehouse-ref", payment_method=payment_method,
        total=Decimal("199.90"), items=[SimpleNamespace(qty=1)],
    )
    place = destination(order)
    pack = parcel(order, shop)
    assert place.method == "warehouse"
    assert place.address == address
    assert place.warehouse_ref == "warehouse-ref"
    assert pack.cod_amount == expected
    assert pack.declared_cost == Decimal("199.90")
    count += 1
    print(f"PASS {address}, {payment_method}: cod_amount={pack.cod_amount}")
print(f"POSTOMAT COD SHIPMENT: {count}/{count}")
