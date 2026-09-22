from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
def read(rel): return (ROOT / rel).read_text(encoding='utf-8')

main = read('backend/api/main.py')
rt = read('backend/shop/services/realtime.py')
rt_router = read('backend/api/routers/realtime.py')
repo = read('backend/shop/repo/sql.py')
base = read('backend/shop/repo/base.py')
sales = read('backend/shop/services/salesdrive.py')
shop = read('backend/api/routers/shop.py')
business = read('backend/shop/services/order_business.py')
dash_app = read('dashboard/src/App.jsx')
dash_rt = read('dashboard/src/components/RealtimeOrders.jsx')
dash_api = read('dashboard/src/api.js')
orders = read('dashboard/src/pages/Orders.jsx')
order_page = read('dashboard/src/pages/OrderPage.jsx')
overview = read('dashboard/src/pages/Overview.jsx')
customers = read('dashboard/src/pages/Customers.jsx')
mini_app = read('miniapp/src/App.jsx')
mini_api = read('miniapp/src/api.js')
mini_profile = read('miniapp/src/screens/Profile.jsx')
mini_chat = read('miniapp/src/screens/Chat.jsx')

tests = [
    ('realtime uses existing Redis settings, no new status env', 'redis_url' in rt and 'redis_password' in rt and 'os.getenv' not in rt),
    ('staff realtime route is mounted and authorized', 'realtime.router' in main and 'require_staff' in rt_router),
    ('live events contain only invalidation metadata', 'contact_phone' not in rt and 'total' not in rt and 'fields' in rt),
    ('SQL emits live event only around committed order mutations', '_emit_order_changed' in repo and 'await self.s.commit()' in repo),
    ('generic status transition has CAS repository contract', 'transition_order_status_atomic' in base and 'with_for_update()' in repo),
    ('SalesDrive stale webhook is rejected before mutation', 'salesdrive.webhook.stale_ignored' in sales and '_snapshot_is_older(order.crm_snapshot, incoming_revision)' in sales),
    ('SalesDrive stale pull snapshot is rejected', 'salesdrive.pull.stale_ignored' in sales and '_snapshot_is_older(latest.crm_snapshot, snap)' in sales),
    ('dashboard SSE raw fetch stays inside transport module', 'consumeOrderEvents' in dash_api and 'fetch(' not in dash_rt),
    ('dashboard shell runs realtime bridge', '<RealtimeOrders />' in dash_app),
    ('orders list reacts to live order invalidation', "elfar:orders:changed" in orders and 'useVisiblePolling(load, 60000)' in orders),
    ('open order card reacts to its live event', "elfar:orders:changed" in order_page and 'useVisiblePolling(refreshLocalOrder, 60000)' in order_page),
    ('overview and customers react without reload', "elfar:orders:changed" in overview and "elfar:orders:changed" in customers),
    ('Mini App stream verifies Telegram initData before subscribing', '/orders/stream' in shop and 'parse_init_data' in shop and 'get_user_by_tg' in shop),
    ('Mini App stream closes DB session before long-lived generator', 'async with open_repo() as repo:' in shop and 'from shop.services.realtime import subscribe_order_events' in shop),
    ('Mini App consumes SSE and keeps fallback sync', 'consumeOrderEvents' in mini_api and 'consumeOrderEvents' in mini_app and 'delay = 60000' in mini_app),
    ('Mini App uses CRM-authoritative status label', 'status_label' in shop and 'display_status_label' in business and 'o.status_label' in mini_profile and 'order.status_label' in mini_chat),
    ('open Mini App chat object is refreshed from canonical orders', 'setChatOrder(fresh)' in mini_app),
]

failed = 0
for name, ok in tests:
    print(('OK ' if ok else 'FAIL ') + name)
    failed += 0 if ok else 1
print(f'{len(tests)-failed}/{len(tests)}')
raise SystemExit(1 if failed else 0)
