"""Static guards for live updates, new-order detection and global status truth."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
notifications = (ROOT / "backend/shop/services/notifications.py").read_text(encoding="utf-8")
shop_router = (ROOT / "backend/api/routers/shop.py").read_text(encoding="utf-8")
stats = (ROOT / "backend/api/routers/stats.py").read_text(encoding="utf-8")
repo = (ROOT / "backend/shop/repo/sql.py").read_text(encoding="utf-8")
center = (ROOT / "dashboard/src/components/NotificationCenter.jsx").read_text(encoding="utf-8")
orders = (ROOT / "dashboard/src/pages/Orders.jsx").read_text(encoding="utf-8")
miniapp = (ROOT / "miniapp/src/App.jsx").read_text(encoding="utf-8")
chat = (ROOT / "miniapp/src/screens/Chat.jsx").read_text(encoding="utf-8")
tasks = (ROOT / "backend/scheduler/tasks.py").read_text(encoding="utf-8")

checks = [
    ("panel new-order event is published before Telegram dependency", notifications.index("await safe_publish(") < notifications.index("if bot is None:")),
    ("API checkout notifies even when bot is unavailable", "if not replayed:\n        try:\n            await notify_new_order(bot, repo, order, user)" in shop_router),
    ("global new-order count has CRM-aware repository path", "async def count_display_new_orders" in repo and "crm_status_id == crm_new_id" in repo),
    ("badges use display new-order count", '"orders_new": await _display_new_count(repo)' in stats),
    ("summary uses the same display new-order count", "result.orders_new = await _display_new_count(repo)" in stats),
    ("notification polling stops while hidden/offline", "document.hidden || navigator.onLine === false" in center and "setInterval(poll, POLL_MS)" not in center),
    ("fresh notifications invalidate Orders immediately", "elfar:notifications:fresh" in center and "elfar:notifications:fresh" in orders),
    ("miniapp background sync no longer uses permanent interval", "setInterval(sync, 15000)" not in miniapp and "setTimeout(sync, delay)" in miniapp),
    ("chat polling no longer wakes hidden tabs every 5s", "setInterval(poll, 5000)" not in chat and "setTimeout(poll, 5000)" in chat),
    ("log retention is independent of successful backup", "async def run_housekeeping" in tasks and "prune_logs(settings.log_retention_days)" in tasks),
]
failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(("OK" if ok else "FAIL"), name)
if failed:
    raise SystemExit("failed: " + ", ".join(failed))
print(f"{len(checks)}/{len(checks)}")
