"""Regression for the bug: CRM status refreshed only after opening OrderPage."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
def read(rel): return (ROOT / rel).read_text(encoding='utf-8')

main = read('backend/api/main.py')
reconciler = read('backend/shop/services/salesdrive_reconciler.py')
scheduler = read('backend/scheduler/tasks.py')
sales = read('backend/shop/services/salesdrive.py')
orders = read('dashboard/src/pages/Orders.jsx')
order_page = read('dashboard/src/pages/OrderPage.jsx')
mini = read('miniapp/src/App.jsx')
edge = read('deploy/nginx/app.conf.template')
dash_nginx = read('dashboard/nginx.conf')
mini_nginx = read('miniapp/nginx.conf')
env = read('.env.example')

checks = [
    ('API starts autonomous CRM watchdog', 'api_watchdog_loop' in main and 'salesdrive-api-watchdog' in main),
    ('watchdog uses shared batch reconciler', 'async def api_watchdog_loop' in reconciler and 'refresh_once(' in reconciler),
    ('scheduler uses exactly same reconciler', 'salesdrive_reconciler import refresh_once' in scheduler),
    ('API watchdog backs off without Redis to avoid duplicate scheduler traffic', 'allow_without_redis=False' in reconciler),
    ('scheduler remains fallback when Redis unavailable', 'allow_without_redis=True' in scheduler),
    ('cross-process Redis lease is atomic', 'nx=True' in reconciler and 'ex=LEASE_SECONDS' in reconciler),
    ('recovery cadence respects SalesDrive daily quota', 'ACTIVE_REFRESH_SECONDS = 120' in reconciler),
    ('known linked CRM order can accept partial webhook without formId', 'def webhook_source_matches' in sales and 'getattr(order, "crm_id"' in sales),
    ('wrong SalesDrive account still fails closed', '_webhook_account_matches' in sales and 'expected_account' in sales),
    ('webhook persists snapshot and CRM status in one patch/commit path', 'patch.update({' in sales and 'await repo.update_order(order.id, patch)' in sales),
    ('orders list has fast DB-only recovery poll', 'useVisiblePolling(load, 15000)' in orders),
    ('open card has fast DB-only recovery poll', 'useVisiblePolling(refreshLocalOrder, 15000)' in order_page),
    ('opening/keeping order card does not auto-pull SalesDrive', 'refreshCrm(true)' not in order_page and 'useVisiblePolling(() => refreshCrm' not in order_page),
    ('Mini App has fast DB-only recovery sync', 'delay = 20000' in mini),
    ('edge nginx explicitly disables buffering for staff SSE', 'location = /api/realtime/orders' in edge and 'proxy_buffering off;' in edge),
    ('edge nginx explicitly disables buffering for Mini App SSE', 'location = /api/shop/orders/stream' in edge and 'proxy_buffering off;' in edge),
    ('container nginx keeps staff SSE unbuffered', 'location = /api/realtime/orders' in dash_nginx and 'proxy_buffering off;' in dash_nginx),
    ('container nginx keeps Mini App SSE unbuffered', 'location = /api/shop/orders/stream' in mini_nginx and 'proxy_buffering off;' in mini_nginx),
    ('no new environment variable added by autonomy layer', 'STATUS_WATCH' not in env and 'CRM_WATCH' not in env and 'os.getenv' not in reconciler),
]

failed=[]
for name, ok in checks:
    print(('OK' if ok else 'FAIL'), name)
    if not ok: failed.append(name)
if failed:
    raise SystemExit('failed: ' + ', '.join(failed))
print(f'{len(checks)}/{len(checks)}')
