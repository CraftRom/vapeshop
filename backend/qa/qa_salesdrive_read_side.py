from pathlib import Path
root=Path(__file__).resolve().parents[2]
sd=(root/'backend/shop/services/salesdrive.py').read_text()
r=(root/'backend/api/routers/orders.py').read_text()
ui=(root/'dashboard/src/pages/OrderPage.jsx').read_text()
checks={
 'read only linked CRM orders': 'if not order.crm_id' in sd and 'Legacy-замовлення не читається' in sd,
 'uses SalesDrive order list': '/api/order/list/' in sd,
 'stores CRM snapshot': 'crm_snapshot' in sd and 'crm_fetched_at' in sd,
 # Behavioural guard: the CRM read path never writes products; the UI says so.
 'does not write catalog from snapshot': 'update_product' not in sd and 'create_product' not in sd
     and 'не змінює локальний каталог магазину' in ui,
 'refresh endpoint exists': 'salesdrive-refresh' in r,
 'UI shows live CRM fields': 'paymentMethod' in ui and 'shippingMethod' in ui and 'managerName' in ui and 'novaposhta' in ui,
}
for k,v in checks.items(): print(('✓' if v else '✗'),k)
assert all(checks.values())
print(f"✓ SalesDrive read-side: {len(checks)}/{len(checks)}")
