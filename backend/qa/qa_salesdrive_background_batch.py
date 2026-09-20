"""Static regression for SalesDrive background quota discipline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sales = (ROOT / "backend/shop/services/salesdrive.py").read_text(encoding="utf-8")
tasks = (ROOT / "backend/scheduler/tasks.py").read_text(encoding="utf-8")
scheduler_main = (ROOT / "backend/scheduler/__main__.py").read_text(encoding="utf-8")
config = (ROOT / "backend/shop/config.py").read_text(encoding="utf-8")
env = (ROOT / ".env.example").read_text(encoding="utf-8")

checks = [
    ("batch helper exists", "async def pull_orders_batch" in sales),
    ("one order-list request for batch", 'body = await _get_json(shop, "/api/order/list/", params=params)' in sales),
    ("batch reuses prefetched body", "_prefetched_body=body" in sales),
    ("batch window capped to 100 ids", "high_limit = low + 99" in sales and '"limit": 100' in sales),
    ("scheduler no longer spawns per-order pulls", "asyncio.gather(*(one(order_id)" not in tasks),
    ("scheduler calls batch", "salesdrive.pull_orders_batch" in tasks),
    ("minimum background interval is 120s", "interval = max(120" in tasks),
    ("global scheduler gate is at least 120s", "SALESDRIVE_BACKGROUND_READ_SECONDS = max(" in scheduler_main and "120, int(settings.salesdrive_background_refresh_seconds)" in scheduler_main),
    ("global gate is reserved before background read", "state[\"salesdrive_background_read_at\"] = now_mono" in scheduler_main and scheduler_main.index("state[\"salesdrive_background_read_at\"] = now_mono") < scheduler_main.index("await refresh_salesdrive_orders()")),
    ("default background interval is 120s", "salesdrive_background_refresh_seconds: int = 120" in config),
    ("env example is 120s", "SALESDRIVE_BACKGROUND_REFRESH_SECONDS=120" in env),
    ("4xx response reason is preserved", "error_body = response.json()" in sales and "reason = _reason(error_body)" in sales),
]
failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(("OK" if ok else "FAIL"), name)
if failed:
    raise SystemExit("failed: " + ", ".join(failed))
print(f"{len(checks)}/{len(checks)}")
