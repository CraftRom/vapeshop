"""Статичні контракти центру сповіщень.

Не піднімає FastAPI/aiogram: набір має ловити розриви wiring навіть у
мінімальному CI-середовищі, де Telegram runtime не встановлений.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


checks = []

def check(ok: bool, label: str) -> None:
    checks.append(bool(ok))
    print(f"{'✓' if ok else '✗'} {label}")

models = text("shop/models.py")
base = text("shop/repo/base.py")
sql = text("shop/repo/sql.py")
router = text("api/routers/notifications.py")
main = text("api/main.py")
catalog = text("api/routers/catalog.py")
order_chat = text("shop/services/order_chat.py")
support_chat = text("shop/services/support_chat.py")
orders = text("shop/services/notifications.py")
migration = text("alembic/versions/9d2e6f41a7bc_panel_notifications.py")

check('class PanelNotification(Base)' in models and 'class PanelNotificationRead(Base)' in models,
      'є журнал подій і персональний стан прочитання')
check('UniqueConstraint("notification_id", "viewer_key"' in models,
      'одне сповіщення не може двічі позначитися прочитаним одним менеджером')
check('create_panel_notification' in base and 'mark_all_panel_notifications_read' in base,
      'контракт Repository містить повний notification API')
check('panel_notification_unread_count' in sql and 'after_id' in sql,
      'SQL repo підтримує unread та incremental polling')
check('_prune_orphan_panel_notifications' in sql and '_delete_panel_notifications_for_entity' in sql,
      'видалені товари, замовлення і support-сесії не лишають сиріт у центрі')
check('m.PanelNotification.kind.in_(("order.created", "order.message"))' in sql
      and '("support.message",)' in sql and '("product.created",)' in sql,
      'cleanup охоплює всі entity-backed типи сповіщень')
check('viewer_key' in router and '@router.get("/poll"' in router,
      'API poll ізольовує read-state кожного працівника')
check('notifications.router' in main and 'prefix="/api/notifications"' in main,
      'router підключений до FastAPI')
check('"product.created"' in catalog and 'safe_publish' in catalog,
      'створення товару породжує подію')
check('"order.message"' in order_chat and 'safe_publish' in order_chat,
      'вхідне повідомлення замовлення породжує подію')
check('"support.message"' in support_chat and 'safe_publish' in support_chat,
      'вхідне повідомлення підтримки породжує подію')
check('"order.created"' in orders and 'safe_publish' in orders,
      'нове замовлення породжує подію')
check('revision: str = "9d2e6f41a7bc"' in migration and 'down_revision' in migration,
      'є послідовна Alembic-міграція')
check('ondelete="CASCADE"' in migration and 'uq_panel_notification_read' in migration,
      'міграція зберігає цілісність read-міток')

passed = sum(checks)
print(f"PANEL NOTIFICATIONS: {passed}/{len(checks)}")
raise SystemExit(0 if passed == len(checks) else 1)
