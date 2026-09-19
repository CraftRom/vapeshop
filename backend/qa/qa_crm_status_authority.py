"""Статус замовлення в робочому UI має походити з SalesDrive, не з local mirror."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sd = (root / 'backend/shop/services/salesdrive.py').read_text()
orders_api = (root / 'backend/api/routers/orders.py').read_text()
stats_api = (root / 'backend/api/routers/stats.py').read_text()
repo = (root / 'backend/shop/repo/sql.py').read_text()
client = (root / 'dashboard/src/api.js').read_text()
orders_ui = (root / 'dashboard/src/pages/Orders.jsx').read_text()
order_ui = (root / 'dashboard/src/pages/OrderPage.jsx').read_text()
status_ui = (root / 'dashboard/src/components/OrderStatus.jsx').read_text()
customers_ui = (root / 'dashboard/src/pages/Customers.jsx').read_text()
overview_ui = (root / 'dashboard/src/pages/Overview.jsx').read_text()

checks = {
    'status dictionary comes directly from CRM': 'await _get_json(shop, "/api/statuses/")' in sd,
    'order refresh filters exact CRM id range': '"filter[id][from]": str(order.crm_id)' in sd and '"filter[id][to]": str(order.crm_id)' in sd,
    'browser status name is not authoritative': 'навмисно НЕ довіряємо йому' in sd and 'status_name_from_options(sid, options)' in sd,
    'staff has a working CRM status endpoint': '@router.get("/salesdrive-statuses")' in orders_api and 'await salesdrive.status_options(shop)' in orders_api,
    'opening a CRM order cannot auto-change its status': 'order.status == OrderStatus.NEW and not order.crm_id' in orders_api,
    'list can filter by CRM status id': 'crm_status_id' in orders_api and 'm.Order.crm_status_id == str(crm_status_id)' in repo,
    'stats distinguish CRM and legacy statuses': 'display_status_breakdown' in stats_api and 'source' in repo,
    'frontend changes CRM status by id only': 'body: { status_id: String(statusId) }' in client and 'status_name: String' not in client,
    'one display model is shared by the panel': 'export function orderDisplayStatus' in status_ui,
    'orders page uses CRM badge and selector': 'OrderStatusBadge' in orders_ui and 'SalesDriveStatusSelect' in orders_ui,
    'order card uses direct CRM refresh': 'salesdriveRefresh' in order_ui and 'OrderStatusBadge' in order_ui,
    'customer history uses the same status badge': 'OrderStatusBadge' in customers_ui,
    'overview uses source-aware status badges': 'StatusBadge' in overview_ui and 'row.source' in overview_ui,
    'CRM dictionary is periodically refreshed': 'loadCrmStatuses, 300000' in orders_ui and 'loadCrmStatuses, 300000' in order_ui,
}

for label, ok in checks.items():
    print(('✓' if ok else '✗'), label)
assert all(checks.values())
print(f"✓ CRM status authority: {len(checks)}/{len(checks)}")
