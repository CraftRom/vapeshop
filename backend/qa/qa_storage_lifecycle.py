from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def text(path):
    return (ROOT / path).read_text(encoding='utf-8')

def check(ok, label):
    if not ok:
        raise AssertionError(label)
    print('✓', label)

models = text('shop/models.py')
sql = text('shop/repo/sql.py')
base = text('shop/repo/base.py')
tasks = text('scheduler/tasks.py')
db = text('shop/db.py')
backups = text('api/routers/backups.py')
chat = text('shop/services/order_chat.py')
migration = text('alembic/versions/b8f2c6d4a910_storage_lifecycle.py')

check('class MessageArchive(Base)' in models and 'LargeBinary' in models,
      'cold-tier is a compressed binary archive, not another hot message table')
check('gzip.compress' in sql and 'gzip.decompress' in sql,
      'archive payload is compressed and transparently readable')
check('archive_cold_messages' in base and 'archive_cold_messages' in sql,
      'repository exposes automatic message lifecycle')
check('MESSAGE_HOT_RETENTION_DAYS = 180' in tasks and 'batch=200' in tasks,
      'scheduler archives cold conversations in bounded batches')
check('m.Order.status.in_((m.OrderStatus.DONE, m.OrderStatus.CANCELLED))' in sql,
      'only terminal orders are eligible for cold archival')
check('m.Order.business_state_at.is_not(None)' in sql and 'terminal_at = case(' in sql,
      'CRM background refresh cannot keep terminal chats hot forever')
check('~unread_order' in sql and '~unread_support' in sql,
      'unread conversations never disappear from hot counters')
check('file_id": None' in sql,
      'cold archive does not retain long-lived Telegram attachment tokens')
check('class ArchivedMessageRef(Base)' in models and 'user_id' in models,
      'reply routing keeps a compact per-user Telegram reference index')
check('find_order_by_tg_message(reply_to.message_id, user.id)' in chat,
      'Telegram reply lookup is scoped to the actual customer chat')
check('class PanelNotificationCursor(Base)' in models,
      'panel read-all state uses one cursor per viewer')
check('O(1) read-all via cursor' in sql and 'm.PanelNotificationCursor' in sql,
      'read-all no longer inserts one read row per notification')
check('prune_panel_notifications' in tasks and 'PANEL_NOTIFICATION_RETENTION_DAYS = 90' in tasks,
      'ephemeral notifications have scheduled retention outside request hot-path')
check('async def storage_report' in db and 'pg_total_relation_size' in db,
      'sysadmin can inspect database and index size without COUNT scans')
check('"database": await storage_report()' in backups,
      'backup/storage endpoint exposes database footprint')
check('revision = "b8f2c6d4a910"' in migration and 'down_revision = "f4c91a7d2b60"' in migration,
      'storage lifecycle schema has a linear Alembic migration')
check('ix_order_messages_order_id_id' in migration and 'ix_support_messages_thread_id_id' in migration,
      'history pagination gets indexes aligned with id cursors')

print('storage lifecycle QA: OK')
