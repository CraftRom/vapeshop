"""Static regression for SalesDrive background quota + scheduler discipline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sales = (ROOT / "backend/shop/services/salesdrive.py").read_text(encoding="utf-8")
tasks = (ROOT / "backend/scheduler/tasks.py").read_text(encoding="utf-8")
reconciler = (ROOT / "backend/shop/services/salesdrive_reconciler.py").read_text(encoding="utf-8")
scheduler_main = (ROOT / "backend/scheduler/__main__.py").read_text(encoding="utf-8")
config = (ROOT / "backend/shop/config.py").read_text(encoding="utf-8")
env = (ROOT / ".env.example").read_text(encoding="utf-8")
repo = (ROOT / "backend/shop/repo/sql.py").read_text(encoding="utf-8")
compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

checks = [
    ("batch helper exists", "async def pull_orders_batch" in sales),
    ("one order-list request for batch", 'body = await _get_json(shop, "/api/order/list/", params=params)' in sales),
    ("batch reuses prefetched body", "_prefetched_body=body" in sales),
    ("batch window capped to 100 ids", "high_limit = low + 99" in sales and '"limit": 100' in sales),
    ("scheduler no longer spawns per-order pulls", "asyncio.gather(*(one(order_id)" not in tasks),
    ("scheduler delegates to shared reconciler", "salesdrive_reconciler import refresh_once" in tasks),
    ("shared reconciler calls batch", "salesdrive.pull_orders_batch" in reconciler),
    ("shared CRM recovery cadence is 120s", "ACTIVE_REFRESH_SECONDS = 120" in reconciler),
    ("global scheduler CRM gate uses shared cadence", "SALESDRIVE_BACKGROUND_READ_SECONDS = ACTIVE_REFRESH_SECONDS" in scheduler_main),
    ("shared Redis lease prevents API/scheduler duplicate reads", "LEASE_KEY" in reconciler and "nx=True" in reconciler and "ex=LEASE_SECONDS" in reconciler),
    ("scheduler has independent per-task gates", 'def _due(state: dict' in scheduler_main and 'salesdrive_write_retry_next_at' in scheduler_main and 'backup_check_next_at' in scheduler_main),
    ("failed CRM reads back off", 'result.get("failed")' in scheduler_main and "1800" in scheduler_main),
    ("terminal CRM orders use slower freshness window", "terminal_stale_before" in reconciler and "6 * 3600" in reconciler and "terminal_stale_before" in repo),
    ("default background interval is 180s", "salesdrive_background_refresh_seconds: int = 180" in config),
    ("env example is 180s", "SALESDRIVE_BACKGROUND_REFRESH_SECONDS=180" in env),
    ("base compose actually runs scheduler", "  scheduler:\n" in compose and "command: python -m scheduler" in compose),
    ("4xx response reason is preserved", "error_body = response.json()" in sales and "reason = _reason(error_body)" in sales),
]
failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(("OK" if ok else "FAIL"), name)
if failed:
    raise SystemExit("failed: " + ", ".join(failed))
print(f"{len(checks)}/{len(checks)}")
