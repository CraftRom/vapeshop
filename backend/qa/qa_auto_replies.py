"""Master switch: settings API, real private/support routing and public mentions."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
import httpx
from qa_common import boot, Report, seed_operators
app, Session, bot = boot('/tmp/qa_auto_replies.db')
from api.auth import create_token
from shop.entities import OperatorRole, Order, OrderLine
from shop.repo.sql import SqlRepository
from shop.services.shop_settings import save_shop_settings, get_shop_settings, invalidate_cache, prime_cache
from shop.services import support_chat
from bot import faq, middlewares
from bot.handlers import chat
from decimal import Decimal

report = Report('AUTO REPLIES')
class Message:
    def __init__(self, text):
        self.text = text; self.caption = None; self.message_id = 99
        self.reply_to_message = None; self.replies = []; self.bot = bot
    async def answer(self, text, **kwargs):
        self.replies.append(text); return SimpleNamespace(message_id=100)
class State:
    async def get_state(self): return None

async def main():
    async with Session() as session:
        repo = SqlRepository(session)
        await seed_operators(repo, {5: ('adminshop', 'A', OperatorRole.ADMIN), 7: ('manager', 'M', OperatorRole.MANAGER)})
        user = await repo.create_user(tg_id=721, username='qa', first_name='QA', referrer_id=None)
        category = await repo.create_category({'name': 'QA', 'is_active': True})
        product = await repo.create_product({'category_id': category.id, 'name': 'QA', 'price': Decimal(10), 'stock': 5, 'is_active': True})
        order = await repo.create_order(Order(id=0, user_id=user.id, subtotal=Decimal(10), total=Decimal(10), discount=Decimal(0), bonus_used=Decimal(0), promo_code_id=None, payment_method='cod', contact_name='QA', contact_phone='+380671234567'), [OrderLine(product_id=product.id, name='QA', price=Decimal(10), qty=1)])
        shop = await save_shop_settings(repo, {'auto_replies_enabled': False})
        for public in (False, True):
            for text in ('Як оплатити?', 'Привіт', '@elfar1_bot яка доставка?'):
                report.check(faq.decide(text, shop=shop, public=public).rule is None, f'master off: {public=} {text}')
        message = Message('Як оплатити?')
        await chat.incoming(message, repo=repo, user=user, state=State())
        report.check(any('Передали менеджеру' in text for text in message.replies), 'disabled private FAQ routes to the order manager')
        report.check(any(item.text == message.text for item in await repo.list_order_messages(order.id)), 'original order message is preserved')
        thread, _ = await support_chat.start(repo, user.id)
        saved = await support_chat.save_incoming(repo, user, 'Яка доставка?')
        message = Message('Яка доставка?')
        report.check(not await chat._support_auto_reply(message, repo, user, saved, message.text), 'disabled support does not send an FAQ')
        report.check(not message.replies, 'disabled support has no outgoing FAQ')
        # Public middleware bypasses private handlers; explicit mentions and fallback must stay silent.
        @asynccontextmanager
        async def open_fake(): yield repo
        original = middlewares.open_repo; middlewares.open_repo = open_fake
        try:
            from aiogram.types import Message as TgMessage
            for text in ('@elfar1_bot як оплатити?', '@elfar1_bot незрозуміле питання', 'яка доставка?'):
                event = TgMessage.model_validate({'message_id': 1, 'date': 1, 'chat': {'id': -100333, 'type': 'supergroup'}, 'from': {'id': 721, 'is_bot': False, 'first_name': 'QA'}, 'text': text})
                async def forbidden(event, data): raise AssertionError('Public update reached private handler')
                result = await middlewares.PrivateOnlyMiddleware()(forbidden, event, {})
                report.check(result is None, f'public master off: {text}')
        finally: middlewares.open_repo = original
        await save_shop_settings(repo, {'auto_replies_enabled': True, 'faq_private_enabled': False, 'faq_support_enabled': True})
        report.check(await chat._support_auto_reply(message, repo, user, saved, 'Яка доставка?'), 'support remains independent of the private-message scope')
        await save_shop_settings(repo, {'faq_support_enabled': False})
        message = Message('Як оплатити?')
        report.check(not await chat._support_auto_reply(message, repo, user, saved, message.text), 'support scope can be disabled independently')
        # Simulate a second worker editing settings while this worker has an old cache.
        await save_shop_settings(repo, {'shop_name': 'Old'})
        await repo.save_settings_map({'shop_name': 'Fresh from another worker'})
        await save_shop_settings(repo, {'auto_replies_enabled': False})
        report.check((await repo.get_settings_map())['shop_name'] == 'Fresh from another worker', 'partial save preserves a concurrent update')
        import shop.services.shop_settings as module
        module._cache = (0, await get_shop_settings(repo))
        class Unavailable:
            async def get_settings_map(self): raise RuntimeError('offline')
        report.check(not (await get_shop_settings(Unavailable())).auto_replies_enabled, 'database outage does not reenable a cached disabled master')
        invalidate_cache()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://qa') as client:
        admin = {'Authorization': f'Bearer {create_token("adminshop", OperatorRole.ADMIN, 5, "A")}'}
        manager = {'Authorization': f'Bearer {create_token("manager", OperatorRole.MANAGER, 7, "M")}'}
        response = await client.put('/api/settings', json={'auto_replies_enabled': False}, headers=admin)
        report.check(response.status_code == 200 and response.json()['auto_replies_enabled'] is False, 'administrator can save the master switch through API')
        response = await client.get('/api/settings', headers=admin)
        report.check(response.json()['auto_replies_enabled'] is False, 'master switch survives an API read')
        response = await client.put('/api/settings', json={'auto_replies_enabled': True}, headers=manager)
        report.check(response.status_code == 403, 'manager cannot change automation policy')

asyncio.run(main())
raise SystemExit(bool(report.done()))
