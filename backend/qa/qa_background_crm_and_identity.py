"""Regression: global CRM pull + safe Telegram names."""
from pathlib import Path

from shop.services.identity import contains_telegram_handle, safe_telegram_first_name

ROOT = Path(__file__).resolve().parents[2]
tasks = (ROOT / "backend/scheduler/tasks.py").read_text(encoding="utf-8")
reconciler = (ROOT / "backend/shop/services/salesdrive_reconciler.py").read_text(encoding="utf-8")
main = (ROOT / "backend/scheduler/__main__.py").read_text(encoding="utf-8")
repo = (ROOT / "backend/shop/repo/sql.py").read_text(encoding="utf-8")
sales = (ROOT / "backend/shop/services/salesdrive.py").read_text(encoding="utf-8")
np_status = (ROOT / "backend/shop/services/nova_poshta_statuses.py").read_text(encoding="utf-8")
api = (ROOT / "backend/api/routers/shop.py").read_text(encoding="utf-8")
mini_chat = (ROOT / "miniapp/src/screens/Chat.jsx").read_text(encoding="utf-8")
mini_app = (ROOT / "miniapp/src/App.jsx").read_text(encoding="utf-8")

checks = [
    ("9 -> Продаж", '"9": "Продаж"' in np_status),
    ("102 -> Відмова", '"102": "Відмова"' in np_status),
    ("103 -> Відмова", '"103": "Відмова"' in np_status),
    ("scheduler has read-side refresh", "async def refresh_salesdrive_orders" in tasks),
    ("scheduler calls read-side refresh", "await refresh_salesdrive_orders()" in main),
    ("SQL selects stale CRM candidates", "list_crm_refresh_candidates" in repo and "crm_fetched_at" in repo),
    ("background pull uses one SalesDrive batch", "salesdrive.pull_orders_batch" in reconciler and "await salesdrive.pull_order(" not in reconciler),
    ("manual-only duplicate business commits removed", "set_order_business_state(" not in sales),
    ("storefront chat uses delta polling", "afterId" in mini_chat and "5000" in mini_chat),
    ("storefront silently refreshes orders/profile", "backgroundSyncRef" in mini_app and "api.orders()" in mini_app and "api.profile()" in mini_app),
    ("chat API accepts after_id", "after_id: int | None = Query" in api),
    ("checkout blocks Telegram handle as name", "contains_telegram_handle" in api),
]

checks += [
    ("@handle is rejected as Telegram first name", safe_telegram_first_name("@_antonyakymenko_", "_antonyakymenko_") is None),
    ("normal first name survives", safe_telegram_first_name("Антон", "_antonyakymenko_") == "Антон"),
    ("handle embedded in PІБ is detected", contains_telegram_handle("Якименко @_antonyakymenko_ Русланович")),
]

failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(("OK" if ok else "FAIL"), name)
if failed:
    raise SystemExit("failed: " + ", ".join(failed))
print(f"{len(checks)}/{len(checks)}")
