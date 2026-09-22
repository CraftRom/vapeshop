"""Static regression for SalesDrive background quota + scheduler discipline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sales = (ROOT / "backend/shop/services/salesdrive.py").read_text(encoding="utf-8")
tasks = (ROOT / "backend/scheduler/tasks.py").read_text(encoding="utf-8")
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
    ("scheduler calls batch", "salesdrive.pull_orders_batch" in tasks),
    ("minimum background interval is 180s", "interval = max(180" in tasks),
    ("global scheduler CRM gate is at least 180s", "SALESDRIVE_BACKGROUND_READ_SECONDS = max(" in scheduler_main and "180, int(settings.salesdrive_background_refresh_seconds)" in scheduler_main),
    ("scheduler has independent per-task gates", 'def _due(state: dict' in scheduler_main and 'salesdrive_write_retry_next_at' in scheduler_main and 'backup_check_next_at' in scheduler_main),
    ("failed CRM reads back off", 'result.get("failed")' in scheduler_main and "1800" in scheduler_main),
    ("terminal CRM orders use slower freshness window", "terminal_stale_before" in tasks and "6 * 3600" in tasks and "terminal_stale_before" in repo),
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
