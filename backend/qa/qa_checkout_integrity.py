"""Глибокі гарантії checkout без HTTP/aiogram залежностей.

Цей набір навмисно не дублює e2e: він ловить класи помилок, які звичайний
послідовний тест не бачить — double submit, TOCTOU залишків, втрату полів ПІБ,
відсутній rollback після unique conflict.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from shop.entities import CartLine, Order, Product, User
from shop.services import shop_service
from shop.services.shop_settings import ShopSettings, prime_cache

ROOT = Path(__file__).resolve().parents[2]

passed = failed = 0

def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}")


class FakeRepo:
    def __init__(self, stock=3, fail_create=False, existing=None):
        self.product = Product(id=7, category_id=1, name="Тест", price=Decimal("100"), stock=stock)
        self.cart = [CartLine(product_id=7, qty=1, product=self.product)]
        self.orders: dict[str, Order] = {}
        self.created = 0
        self.fail_create = fail_create
        self.existing = existing
        self.cleared = False

    async def get_cart(self, user_id):
        return list(self.cart)

    async def adjust_stock(self, product_id, delta):
        if self.product.stock + delta < 0:
            return None
        self.product.stock += delta
        return self.product

    async def create_order(self, order, lines):
        if self.fail_create:
            raise RuntimeError("simulated unique conflict")
        self.created += 1
        order.id = self.created
        order.items = list(lines)
        if order.checkout_key:
            self.orders[order.checkout_key] = order
        return order

    async def get_order_by_checkout_key(self, key):
        return self.existing or self.orders.get(key)

    async def update_order(self, *args, **kwargs):
        return None

    async def register_promo_use(self, *args, **kwargs):
        return None

    async def add_bonus(self, *args, **kwargs):
        return None

    async def clear_cart(self, user_id):
        self.cart = []
        self.cleared = True

    async def get_settings_map(self):
        return {}

    async def get_promo_by_code(self, code):
        return None

    async def promo_uses_by_user(self, promo_id, user_id):
        return 0


async def runtime_checks():
    # Не залежимо від .env конкретного сервера: ці сценарії не тестують CRM,
    # бонуси чи автоматичну знижку.
    cfg = replace(
        ShopSettings.from_env(),
        salesdrive_enabled=False,
        volume_discount_enabled=False,
        bonus_enabled=False,
    )
    prime_cache(cfg)
    user = User(id=1, tg_id=100, referral_code="abc", age_confirmed=True)

    repo = FakeRepo(stock=2)
    order, error = await shop_service.create_order(
        repo, user,
        contact_name="Наталія", contact_surname="Сосновенко",
        contact_patronymic="Петрівна", contact_phone="+380671533088",
        city="Київ", address="Відділення 71", payment_method="card",
        checkout_key="checkout_runtime_123456",
    )
    check(error is None and order is not None, "звичайний checkout створює замовлення")
    check(repo.product.stock == 1, "товар резервується рівно один раз")
    check(repo.cleared, "після успіху кошик очищається")
    check(order.contact_surname == "Сосновенко" and order.contact_patronymic == "Петрівна", "компоненти ПІБ не губляться")
    check(order.checkout_key == "checkout_runtime_123456", "idempotency key доходить до доменного замовлення")

    # validate_cart може бачити старий stock, а умовний reserve — уже новий.
    class RaceRepo(FakeRepo):
        async def adjust_stock(self, product_id, delta):
            if delta < 0:
                return None
            return await super().adjust_stock(product_id, delta)
    race = RaceRepo(stock=2)
    order2, error2 = await shop_service.create_order(
        race, user, contact_name="А", contact_phone="+380501112233",
        city="Київ", address="1", payment_method="card",
        checkout_key="checkout_race_12345678",
    )
    check(order2 is None and error2 and "наяв" in error2.lower(), "TOCTOU залишку не створює замовлення")
    check(race.created == 0, "при провалі резерву insert замовлення не виконується")

    # Конкурентний другий POST уже зарезервував одиницю, але програв unique
    # checkout_key. Сервіс мусить повернути резерв і віддати перше замовлення.
    existing = Order(id=44, user_id=1, total=Decimal("100"), checkout_key="checkout_dupe_12345678")
    dupe = FakeRepo(stock=3, fail_create=True, existing=existing)
    before = dupe.product.stock
    got, err = await shop_service.create_order(
        dupe, user, contact_name="А", contact_phone="+380501112233",
        city="Київ", address="1", payment_method="card",
        checkout_key=existing.checkout_key,
    )
    check(err is None and got and got.id == 44, "одночасний duplicate повертає вже створене замовлення")
    check(dupe.product.stock == before, "резерв другого duplicate повертається на склад")
    check(bool(getattr(got, "checkout_replayed", False)), "duplicate позначається replay для недубльованих side-effects")


asyncio.run(runtime_checks())

print("\n--- статичні гарантії SQL/API/UI ---")
sql = (ROOT / "backend/shop/repo/sql.py").read_text()
service = (ROOT / "backend/shop/services/shop_service.py").read_text()
router = (ROOT / "backend/api/routers/shop.py").read_text()
bot = (ROOT / "backend/bot/handlers/checkout.py").read_text()
model = (ROOT / "backend/shop/models.py").read_text()
migration = (ROOT / "backend/alembic/versions/7a1f4c9e2b63_checkout_idempotency.py").read_text()

check("m.Product.stock >= -delta" in sql, "SQL reserve має умову stock >= qty")
check("await self.s.rollback()" in sql[sql.index("async def create_order"):sql.index("async def get_order", sql.index("async def create_order"))], "create_order робить rollback після DB помилки")
check("contact_surname=order.contact_surname" in sql and "contact_patronymic=order.contact_patronymic" in sql, "SQL зберігає прізвище й по батькові")
check("Index(\"ux_orders_checkout_key\"" in model and "unique=True" in model, "checkout_key захищений unique index")
check("op.create_index(\"ux_orders_checkout_key\"" in migration, "є міграція idempotency index")
check("get_order_by_checkout_key" in router and "Ключ оформлення вже використано" in router, "API перевіряє повтор checkout до кошика")
check("checkout_key=data.checkout_key" in router, "API передає ключ у бізнес-логіку")
check("secrets.token_urlsafe" in bot and "checkout_key=data.get(\"checkout_key\")" in bot, "бот теж ідемпотентний при double-confirm")
check("phone = normalize_phone(message.contact.phone_number)" in bot, "Telegram contact проходить ту саму нормалізацію телефону")
check("@field_validator(\"contact_phone\")" in router and 'return "+380" + body' in router, "API нормалізує телефон незалежно від frontend")
check("reserved:" in service and service.index("reserved:") < service.index("repo.create_order(draft, order_lines)"), "stock резервується до insert замовлення")
check("async def create_checkout_order_atomic" in sql, "SQL має атомарний checkout path")
atomic_body = sql[sql.index("async def create_checkout_order_atomic"):sql.index("async def get_order", sql.index("async def create_checkout_order_atomic"))]
check(atomic_body.index("m.Order.checkout_key == order.checkout_key") < atomic_body.index("current_cart != expected_cart"), "конкурентний replay перевіряється до спорожнілого кошика")
check('return None, "duplicate_conflict"' in atomic_body, "чужий idempotency key не повертає чуже замовлення")
check("sorted(lines, key=lambda item: int(item.product_id))" in sql and "Decimal(str(product.price)) != Decimal(str(line.price))" in sql, "checkout повторно звіряє active/stock/price і блокує товари в стабільному порядку")
check('crm_state=order.crm_state' in sql and 'crm_state="pending" if shop.salesdrive_ready else ""' in service, "CRM pending входить у той самий commit, що й нове замовлення")
check("with_for_update()" in sql and "current_cart != expected_cart" in sql, "checkout серіалізований з cart і звіряє snapshot")
check("m.PromoUsage" in sql[sql.index("async def create_checkout_order_atomic"):sql.index("async def get_order", sql.index("async def create_checkout_order_atomic"))], "promo usage входить у checkout transaction")
check("m.BonusTx" in sql[sql.index("async def create_checkout_order_atomic"):sql.index("async def get_order", sql.index("async def create_checkout_order_atomic"))], "bonus spend входить у checkout transaction")
check("delete(m.CartItem)" in sql[sql.index("async def create_checkout_order_atomic"):sql.index("async def get_order", sql.index("async def create_checkout_order_atomic"))], "clear cart входить у checkout transaction")
check("create_checkout_order_atomic" in service, "сервіс використовує атомарний SQL checkout коли доступний")
check('if not replayed:' in router and 'checkout_replayed' in router, "API не дублює Telegram/panel side-effects на конкурентному replay")
check('if getattr(order, "checkout_replayed", False):' in bot, "бот не дублює side-effects на double-confirm")
check("async def change_cart_qty_atomic" in sql and "select(m.User).where(m.User.id == user_id).with_for_update()" in sql, "cart +/- серіалізований між вкладками")
check("async def set_cart_qty" in sql and "Встановлює абсолютну кількість, серіалізуючись з checkout" in sql, "bot absolute cart qty серіалізований з checkout")
check("async def clear_cart" in sql and "Очищає кошик під тим самим user-lock" in sql, "clear cart серіалізований з checkout")

print(f"\nCHECKOUT INTEGRITY: {passed}/{passed + failed}")
raise SystemExit(1 if failed else 0)
