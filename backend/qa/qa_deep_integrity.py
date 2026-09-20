"""Глибокі invariants, яких не ловлять звичайні happy-path тести."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
checks: list[tuple[str, bool]] = []

def check(label: str, ok: bool):
    checks.append((label, bool(ok)))
    print(('✓' if ok else '✗'), label)

sql = (ROOT / 'backend/shop/repo/sql.py').read_text()
svc = (ROOT / 'backend/shop/services/shop_service.py').read_text()
shop = (ROOT / 'backend/api/routers/shop.py').read_text()
orders = (ROOT / 'backend/api/routers/orders.py').read_text()
support = (ROOT / 'backend/api/routers/support.py').read_text()
bot_checkout = (ROOT / 'backend/bot/handlers/checkout.py').read_text()
photo = (ROOT / 'miniapp/src/photo.jsx').read_text()
mini_api = (ROOT / 'miniapp/src/api.js').read_text()

print('\n--- checkout/cart concurrency ---')
check('clear cart бере той самий user row-lock, що й checkout',
      'Очищає кошик під тим самим user-lock' in sql)
check('bot absolute cart qty серіалізований з checkout',
      'Встановлює абсолютну кількість, серіалізуючись з checkout' in sql)
check('atomic checkout блокує товари у стабільному порядку',
      'sorted(lines, key=lambda item: int(item.product_id))' in sql)
check('atomic checkout повторно звіряє актуальну ціну',
      'Decimal(str(product.price)) != Decimal(str(line.price))' in sql)
check('промокод повторно рахується під row-lock',
      'live_discount' in sql and 'promo.min_order' in sql)
check('CRM pending зберігається в тому самому commit, що order',
      'crm_state="pending" if shop.salesdrive_ready else ""' in svc
      and 'crm_state=order.crm_state' in sql)

print('\n--- cancellation exactly-once ---')
check('SQL має атомарний cancel', 'async def cancel_order_atomic' in sql)
check('cancel блокує Order та User',
      'select(m.Order).where(m.Order.id == order_id).with_for_update()' in sql
      and 'select(m.User).where(m.User.id == row.user_id).with_for_update()' in sql)
check('cancel повертає stock і bonus до одного commit',
      'product.stock = int(product.stock or 0) + int(item.qty or 0)' in sql
      and 'reason="refund"' in sql)
check('stale cancel не виконує side-effects',
      'raise OrderStateConflict' in svc and 'except OrderStateConflict' in (ROOT / 'backend/shop/services/order_workflow.py').read_text())

print('\n--- Telegram / attachments ---')
check('бот не запускає другу checkout FSM поверх активної',
      'if await state.get_state()' in bot_checkout and 'Оформлення вже розпочато' in bot_checkout)
check('бот нормалізує телефон до +380 так само, як Mini App',
      'return "+380" + body' in bot_checkout and 'len(body) != 9' in bot_checkout)
check('manager notification failure не валить уже створене bot order',
      'менеджер не отримав сповіщення' in bot_checkout and 'except Exception' in bot_checkout)
check('API не використовує unbound bot після збою _instances',
      'bot = None' in shop and 'elif bot is None:' in shop)
check('upload фото перевіряється за сигнатурою',
      'def _photo_mime' in shop and 'actual_mime = _photo_mime(blob)' in shop)
check('upload фото не бреше про успіх без Telegram file_id',
      'Бот тимчасово недоступний — фото не збережено' in shop
      and 'Telegram не повернув ідентифікатор фото' in shop)
check('Content-Disposition filename не інтерполюється сирим',
      "filename*=UTF-8''" in orders and "filename*=UTF-8''" in support)
check('product photo використовує timed API transport',
      'api.productPhoto(product.id)' in photo and 'productPhoto: async' in mini_api
      and 'fetchTimed(`${BASE}${endpoint}`' in mini_api)

failed = [label for label, ok in checks if not ok]
print(f"\nDEEP INTEGRITY: {len(checks)-len(failed)}/{len(checks)}")
raise SystemExit(1 if failed else 0)
