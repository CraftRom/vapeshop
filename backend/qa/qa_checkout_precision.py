"""F01–F03: real SQL quotes, stale confirmation, HTTP replay and bot double tap.
All Telegram delivery is intercepted; no CRM or carrier calls are made.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from qa_common import Report, boot, init_data

app, Session, fake = boot('/tmp/checkout_precision_stage1.db')
from httpx import ASGITransport, AsyncClient
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import Message, Chat, Update
from bot.factory import build_dispatcher
from bot.states import Checkout
from shop.entities import User, Order
from shop.formatting import money
from shop.repo.sql import SqlRepository
from shop.services import shop_service as svc
from shop.services.notifications import build_order_text
from shop.services.status_messages import compose
from shop.services.shop_settings import ShopSettings, prime_cache
from shop.entities import OrderStatus

report = Report('CHECKOUT PRECISION')
BASE = replace(ShopSettings.from_env(), salesdrive_enabled=False,
               volume_discount_enabled=True, volume_discount_min=Decimal('100'),
               volume_discount_percent=Decimal('10'), bonus_enabled=True,
               bonus_max_percent=Decimal('30'))

class Recorder(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.fail_confirmation = False
    async def close(self): pass
    async def stream_content(self, *args, **kwargs):
        yield b''
    async def make_request(self, bot, method, timeout=None):
        data = method.model_dump(exclude_none=True)
        self.calls.append((type(method).__name__, data))
        if self.fail_confirmation and data.get('chat_id') == 8001 and type(method).__name__ in ('SendMessage', 'EditMessageText'):
            raise RuntimeError('simulated buyer confirmation delivery failure')
        if method.__returning__ is bool:
            return True
        return Message(message_id=len(self.calls), date=datetime.now(timezone.utc),
                       chat=Chat(id=int(data.get('chat_id', 1)), type='private'),
                       text=data.get('text'))
    def button(self, prefix):
        return next(b['callback_data'] for _, data in reversed(self.calls)
                    for row in data.get('reply_markup', {}).get('inline_keyboard', [])
                    for b in row if b.get('callback_data', '').startswith(prefix))
    def texts(self):
        return '\n'.join(data.get('text', '') for _, data in self.calls)

seq = 0

def update(bot, value, callback=False, user_id=8001):
    global seq
    seq += 1
    person = {'id': user_id, 'is_bot': False, 'first_name': 'Тест'}
    msg = {'message_id': seq, 'date': int(datetime.now(timezone.utc).timestamp()),
           'chat': {'id': user_id, 'type': 'private'}, 'from': person, 'text': value}
    data = {'update_id': seq}
    if callback:
        data['callback_query'] = {'id': str(seq), 'from': person, 'chat_instance': 'qa',
                                  'data': value, 'message': msg}
    else:
        data['message'] = msg
    return Update.model_validate(data, context={'bot': bot})

async def run():
    prime_cache(BASE)
    async with Session() as session:
        repo = SqlRepository(session)
        category = await repo.create_category({'name': 'QA'})
        product = await repo.create_product({'category_id': category.id, 'name': 'Товар <X>',
                                             'price': Decimal('199.90'), 'stock': 30})
        user = await repo.create_user(8001, None, 'Тест', None)
        await repo.confirm_age(user)
        await repo.add_bonus(user.id, Decimal('100'), 'manual')
        await repo.set_cart_qty(user.id, product.id, 1)
        await repo.create_promo({'code': 'P5', 'value': Decimal('5'), 'per_user_limit': 5})
        await repo.create_promo({'code': 'P20', 'value': Decimal('20'), 'per_user_limit': 5})
        await repo.create_promo({'code': 'P10', 'value': Decimal('10'), 'per_user_limit': 5})
        for code, discount, source, bonus, total in [
            (None, '19.99', 'volume', '0', '179.91'),
            ('P5', '19.99', 'volume', '0', '179.91'),
            ('P20', '39.98', 'promo', '0', '159.92'),
            ('P10', '19.99', 'promo', '0', '179.91'),
        ]:
            q = await svc.checkout_quote(repo, user, promo_code=code)
            report.check((q.discount, q.discount_source, q.bonus_used, q.total) ==
                         (Decimal(discount), source, Decimal(bonus), Decimal(total)),
                         f'знижки не додаються, код {code or "без коду"}')
        q = await svc.checkout_quote(repo, user, use_bonus=True)
        report.check(q.bonus_available == Decimal('53.97') and q.total == Decimal('125.94'),
                     'ліміт бонусів після автоматичної знижки, точні копійки')
        prime_cache(replace(BASE, volume_discount_enabled=False))
        q = await svc.checkout_quote(repo, user, promo_code='P20')
        report.check(q.total == Decimal('159.92') and q.discount_source == 'promo', 'промокод без знижки за суму')
        prime_cache(BASE)
        quote = await svc.checkout_quote(repo, user, use_bonus=True)
        args = dict(contact_name='Тест', contact_phone='+380671234567', city='Київ',
                    address='1', payment_method='card', checkout_key='qa_precision_8001',
                    expected_quote=quote.token, use_bonus=True)
        await repo.set_cart_qty(user.id, product.id, 2)
        bad, err = await svc.create_order(repo, user, **args)
        report.check(bad is None and err == svc.CHECKOUT_CHANGED and await repo.count_orders() == 0,
                     'змінений кошик не оформлюється за старим підсумком')
        await repo.set_cart_qty(user.id, product.id, 1)
        await repo.update_product(product.id, {'price': Decimal('209.90')})
        bad, err = await svc.create_order(repo, user, **args)
        report.check(bad is None and err == svc.CHECKOUT_CHANGED, 'зміна ціни вимагає нового підтвердження')
        await repo.update_product(product.id, {'price': Decimal('199.90')})
        prime_cache(replace(BASE, volume_discount_percent=Decimal('15')))
        bad, err = await svc.create_order(repo, user, **args)
        report.check(bad is None and err == svc.CHECKOUT_CHANGED, 'зміна правил знижки вимагає підтвердження')
        prime_cache(BASE)
        order, err = await svc.create_order(repo, user, **args)
        report.check(err is None and order.total == quote.total == Decimal('125.94'), 'quote дорівнює фінальному SQL замовленню')
        stock = (await repo.get_product(product.id)).stock
        balance = (await repo.get_user(user.id)).bonus_balance
        replay, err = await svc.create_order(repo, user, **args)
        report.check(err is None and replay.id == order.id and replay.checkout_replayed,
                     'повтор у спільному сервісі успішний після очищення кошика')
        report.check((await repo.get_product(product.id)).stock == stock and
                     (await repo.get_user(user.id)).bonus_balance == balance and
                     await repo.count_orders() == 1, 'повтор не списує товар/бонуси вдруге')
        other = await repo.create_user(8002, None, 'Інший', None)
        got, err = await svc.create_order(repo, other, **args)
        report.check(got is None and err == 'Ключ оформлення вже використано', 'ключ чужого покупця не розкриває замовлення')
        text = await build_order_text(repo, order, user)
        report.check('125,94' in text and '199,90' in text and '19,99' in text and '53,97' in text,
                     'повідомлення менеджеру зберігає всі копійки')
        for amount, shown in [('199.90', '199,90'), ('0.01', '0,01'), ('179.91', '179,91'), ('200', '200,00')]:
            report.check(money(Decimal(amount)) == shown, f'формат грошей {amount}')
        status_text = compose(order, OrderStatus.PAID, BASE)
        report.check('125,94' in status_text, 'сповіщення про статус без округлення')
        await repo.set_cart_qty(user.id, product.id, 1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver',
                           headers=init_data(8001)) as client:
        response = await client.post('/api/shop/checkout/quote', json={'use_bonus': False})
        report.check(response.status_code == 200 and response.json()['total'] == '179.91', 'HTTP preview повертає точні Decimal strings')
        q = response.json()
        payload = dict(contact_surname='Тест', contact_name='Тест', contact_phone='0671234567',
                       city='Київ', address='1', payment_method='card',
                       checkout_key='qa_http_precision_8001', quote_token=q['quote_token'])
        async with Session() as session:
            await SqlRepository(session).set_cart_qty(user.id, product.id, 2)
        failed = await client.post('/api/shop/checkout', json=payload)
        report.check(failed.status_code == 409, 'HTTP 409 замість покупки за зміненою сумою')
        async with Session() as session:
            await SqlRepository(session).set_cart_qty(user.id, product.id, 1)
        first = await client.post('/api/shop/checkout', json=payload)
        sent = len(fake.sent)
        second = await client.post('/api/shop/checkout', json=payload)
        report.check(first.status_code == second.status_code == 200 and first.json() == second.json(), 'HTTP replay повертає те саме замовлення')
        report.check(len(fake.sent) == sent, 'HTTP replay без повторних сповіщень')
        report.check(any('179,91' in text for _, text in fake.sent), 'підтвердження в Telegram із вітрини з копійками')

    # Full aiogram dispatcher, actual FSM filters and actual event isolation.
    async with Session() as session:
        await SqlRepository(session).set_cart_qty(user.id, product.id, 1)
    recorder = Recorder()
    bot = Bot(token='777001:TESTTOKEN', session=recorder)
    dp = build_dispatcher()
    async def feed(value, callback=False):
        await dp.feed_update(bot, update(bot, value, callback))
    await feed('checkout', True)
    await feed('Тест Покупець')
    await feed('0671234567')
    await feed('Київ')
    await feed('Відділення 1')
    await feed('skip', True)
    report.check('Ліміт уже враховує знижку' in recorder.texts(), 'бот пропонує бонуси після знижки')
    await feed('bonus:no', True)
    await feed('pay:card', True)
    await feed('skip', True)
    report.check('До сплати: 179,91' in recorder.texts() and 'Знижка за суму' in recorder.texts(), 'бот показує автоматичну знижку до покупки')
    first_button = recorder.button('order:confirm:')
    async with Session() as session:
        repo = SqlRepository(session)
        before_count = await repo.count_orders()
        await repo.set_cart_qty(user.id, product.id, 2)
    await feed(first_button, True)
    async with Session() as session:
        report.check(await SqlRepository(session).count_orders() == before_count, 'бот не купує змінений кошик по старому підсумку')
    button = recorder.button('order:confirm:')
    await feed(first_button, True)
    report.check(any('застаріла' in data.get('text', '') for name, data in recorder.calls
                     if name == 'AnswerCallbackQuery'), 'стара кнопка не підтверджує новий підсумок')
    await asyncio.gather(feed(button, True), feed(button, True))
    async with Session() as session:
        repo = SqlRepository(session)
        report.check(await repo.count_orders() == before_count + 1, 'два конкурентні callbacks створили одне замовлення')
    ctx = dp.fsm.get_context(bot=bot, chat_id=8001, user_id=8001)
    report.check(await ctx.get_state() == Checkout.receipt.state, 'double tap зберігає очікування квитанції')
    data = await ctx.get_data()
    done_id = data['order_id']
    manager_messages = sum(name == 'SendMessage' and payload.get('chat_id') == BASE.admin_chat_id
                           and 'Замовлення №' in payload.get('text', '') for name, payload in recorder.calls)
    report.check(manager_messages == 1, 'менеджер отримує одне сповіщення від бота')
    await feed(button, True)
    report.check((await ctx.get_data()).get('order_id') == done_id and await ctx.get_state() == Checkout.receipt.state,
                 'старий callback не руйнує receipt стан')
    async with Session() as session:
        await SqlRepository(session).set_cart_qty(user.id, product.id, 1)
    await feed('checkout', True)
    await feed('Інший Покупець')
    await feed('0671234567')
    await feed('Київ')
    await feed('1')
    await feed('skip', True)
    await feed('bonus:no', True)
    await feed('pay:card', True)
    await feed('skip', True)
    next_button = recorder.button('order:confirm:')
    await feed(button, True)
    async with Session() as session:
        report.check(await SqlRepository(session).count_orders() == before_count + 1
                     and await ctx.get_state() == Checkout.confirm.state,
                     'стара кнопка попередньої покупки не оформлює наступну')
    recorder.fail_confirmation = True
    await feed(next_button, True)
    async with Session() as session:
        report.check(await SqlRepository(session).count_orders() == before_count + 2
                     and await ctx.get_state() == Checkout.receipt.state,
                     'збій підтвердження клієнту не втрачає замовлення або receipt FSM')
    report.check(sum(name == 'SendMessage' and payload.get('chat_id') == BASE.admin_chat_id
                     and 'Замовлення №' in payload.get('text', '') for name, payload in recorder.calls) == 2,
                 'збій повідомлення клієнту не перериває сповіщення менеджеру')
    await dp.fsm.close()
    await bot.session.close()

    # Force the first request to commit after the initial lookup but before
    # the second cart read: the late replay path must also succeed.
    class LateReplay:
        def __init__(self): self.lookups = 0
        async def get_order_by_checkout_key(self, key):
            self.lookups += 1
            return None if self.lookups == 1 else Order(id=888, user_id=7, total=Decimal('0.01'))
        async def get_cart(self, user_id): return []
    prime_cache(BASE)
    got, err = await svc.create_order(LateReplay(), User(id=7, tg_id=7, referral_code='x'),
                                     contact_name='Тест', contact_phone='+380671234567',
                                     city='Київ', address='1', payment_method='card', checkout_key='late_replay_test')
    report.check(err is None and got.id == 888 and got.checkout_replayed, 'commit між lookup і читанням кошика теж повертає успіх')

asyncio.run(run())
raise SystemExit(bool(report.done()))
