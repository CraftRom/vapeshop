from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check(cond, message):
    if not cond:
        raise AssertionError(message)
    print(f"✓ {message}")

repo = (ROOT / 'shop/repo/sql.py').read_text(encoding='utf-8')
base = (ROOT / 'shop/repo/base.py').read_text(encoding='utf-8')
models = (ROOT / 'shop/models.py').read_text(encoding='utf-8')
entities = (ROOT / 'shop/entities.py').read_text(encoding='utf-8')
orders = (ROOT / 'api/routers/orders.py').read_text(encoding='utf-8')
shop = (ROOT / 'api/routers/shop.py').read_text(encoding='utf-8')
chat = (ROOT / 'shop/services/order_chat.py').read_text(encoding='utf-8')
handler = (ROOT / 'bot/handlers/chat.py').read_text(encoding='utf-8')
migration = (ROOT / 'alembic/versions/f4c91a7d2b60_order_chat_history_delivery.py').read_text(encoding='utf-8')

check('before_id: int | None = None' in base and 'before_id: int | None = None' in repo, 'repository supports paging backward through full chat history')
check('m.OrderMessage.id < int(before_id)' in repo, 'older history is selected before the first loaded message')
check('order_by(m.OrderMessage.id.desc())' in repo and 'rows.reverse()' in repo, 'history pages stay chronological')
check('before_id: int | None = Query(None, ge=1)' in orders, 'staff chat endpoint exposes before_id')
check('before_id: int | None = Query(None, ge=1)' in shop, 'Mini App chat endpoint exposes before_id')
check('delivered: Mapped[bool | None]' in models and 'delivery_error' in models, 'delivery result is persisted with the message')
check('delivered: bool | None = None' in entities, 'domain entity carries persisted delivery result')
check('"is_read": False, "delivered": False' in orders, 'failed delivery is saved as failed, not read')
check('"delivered": True' in chat, 'successful Telegram sends persist delivery success')
check('tg_message_id=tg_message_id' in handler and 'tg_message_id: int | None = None' in chat, 'incoming Telegram message id is retained in history')
check('op.add_column("order_messages", sa.Column("delivered"' in migration, 'database migration adds persistent delivery state')
check("WHERE direction = 'out' AND tg_message_id IS NOT NULL" in migration, 'migration safely backfills known historical sends')

print('order chat history QA: OK')
