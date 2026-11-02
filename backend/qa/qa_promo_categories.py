"""Category restrictions through SQL, storefront API and locked checkout."""
import asyncio
from dataclasses import replace
from decimal import Decimal
from httpx import ASGITransport, AsyncClient
from qa_common import Report, boot, init_data
from qa_paths import qa_db_path
app, Session, _ = boot(qa_db_path('promo_categories.db'))
from shop.entities import Order, OrderLine
from shop import models
from shop.repo.sql import SqlRepository
from shop.services import promo as legacy_promo, shop_service as svc
from shop.services.shop_settings import ShopSettings, prime_cache
r = Report('Promo categories')

async def run():
    prime_cache(replace(ShopSettings.from_env(), volume_discount_enabled=False, salesdrive_enabled=False, bonus_enabled=False))
    async with Session() as session, AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        repo = SqlRepository(session)
        a = await repo.create_category({'name': 'Категорія A'})
        b = await repo.create_category({'name': 'Категорія B'})
        sub = await repo.create_subcategory({'name': 'Дочірня A', 'category_id': a.id})
        specs = [dict(name='A', price=Decimal('199.90'), category_id=a.id), dict(name='Child A', price=Decimal('50.10'), subcategory_id=sub.id), dict(name='B', price=Decimal('400'), category_id=b.id), dict(name='Ungrouped', price=Decimal('100'))]
        products = [await repo.create_product({**data, 'stock': 20}) for data in specs]
        user = await repo.create_user(779101, None, 'Покупець', None)
        await repo.confirm_age(user)
        for product, qty in zip(products, [2, 1, 1, 1]):
            await repo.set_cart_qty(user.id, product.id, qty)
        login = await client.post('/api/auth/login', json={'login': 'admin', 'password': 'secret'})
        admin = {'Authorization': 'Bearer ' + login.json()['access_token']}
        body = dict(code='ONLYA', value='25', category_ids=[a.id, a.id], per_user_limit=10)
        response = await client.post('/api/promos', headers=admin, json=body)
        r.check(response.status_code == 201 and response.json()['category_ids'] == [a.id], 'API saves deduplicated scope', response.text)
        promo_id = response.json()['id']
        for bad in [[0], [-1], [True], ['1'], [1.5], [999999], None]:
            response = await client.post('/api/promos', headers=admin, json={**body, 'code': 'BAD', 'category_ids': bad})
            r.check(response.status_code == 422, f'invalid category scope rejected: {bad}')
        response = await client.get(f'/api/promos/{promo_id}', headers=admin)
        r.check(response.json()['category_ids'] == [a.id], 'scope survives API readback')
        subtotal = await svc.cart_subtotal(repo, user.id)
        r.check(subtotal == Decimal('949.90'), 'mixed basket includes quantities and ungrouped items')
        result = await svc.check_promo(repo, 'onlya', user.id, subtotal)
        r.check(result.ok and result.discount == Decimal('112.48'), 'percent includes direct and subcategory-only products, with cents')
        legacy = await legacy_promo.apply(session, 'onlya', user.id, subtotal)
        r.check(legacy.ok and legacy.discount == result.discount, 'legacy SQL path has identical restrictions')
        response = await client.post('/api/shop/promo/check', headers=init_data(779101), json={'code': 'ONLYA'})
        r.check(response.status_code == 200 and Decimal(response.json()['discount']) == result.discount, 'storefront check returns scoped discount', response.text)
        await repo.create_promo(dict(code='CAP', type='fixed', value=Decimal('500'), category_ids=[a.id]))
        fixed = await svc.check_promo(repo, 'CAP', user.id, subtotal)
        r.check(fixed.ok and fixed.discount == Decimal('449.90'), 'fixed discount cannot spill onto other categories')
        await repo.create_promo(dict(code='MIN', value=Decimal('10'), category_ids=[a.id], min_order=Decimal('900')))
        r.check((await svc.check_promo(repo, 'MIN', user.id, subtotal)).ok, 'minimum amount uses the entire order')
        await repo.create_promo(dict(code='ALL', value=Decimal('10')))
        r.check((await svc.check_promo(repo, 'ALL', user.id, subtotal)).discount == Decimal('94.99'), 'unrestricted promo retains full-cart behavior')
        await repo.create_promo(dict(code='BOTH', value=Decimal('10'), category_ids=[a.id, b.id]))
        r.check((await svc.check_promo(repo, 'BOTH', user.id, subtotal)).discount == Decimal('84.99'), 'multiple categories combine, ungrouped product excluded')
        q = await svc.checkout_quote(repo, user, promo_code='ONLYA')
        r.check(q.discount == Decimal('112.48') and q.total == Decimal('837.42'), 'authoritative quote matches category rules')
        args = dict(contact_name='QA', contact_phone='+380671234567', city='Київ', address='1', payment_method='card', promo_code='ONLYA', checkout_key='qa-scoped-order')
        order, error = await svc.create_order(repo, user, expected_quote=q.token, **args)
        r.check(order is not None and error is None and order.discount == q.discount and order.total == q.total, 'atomic checkout accepts scoped discount', error or '')
        r.check(await repo.promo_uses_by_user(promo_id, user.id) == 1, 'checkout records one usage')
        replay, error = await svc.create_order(repo, user, **args)
        r.check(replay.id == order.id and await repo.promo_uses_by_user(promo_id, user.id) == 1, 'replay does not consume usage again')
        await repo.set_cart_qty(user.id, products[2].id, 1)
        no_match = await svc.check_promo(repo, 'ONLYA', user.id, Decimal('400'))
        r.check(not no_match.ok and 'категорій' in no_match.error, 'nonmatching basket rejects code')
        response = await client.post('/api/shop/promo/check', headers=init_data(779101), json={'code': 'ONLYA'})
        r.check(response.status_code == 200 and response.json()['ok'] is False, 'public check explains nonmatching basket')
        r.check(await repo.promo_uses_by_user(promo_id, user.id) == 1, 'failed check consumes no usage')
        await repo.set_cart_qty(user.id, products[0].id, 2)
        q = await svc.checkout_quote(repo, user, promo_code='ONLYA')
        lines = await repo.get_cart(user.id)
        draft = Order(id=0, user_id=user.id, subtotal=q.subtotal, discount=q.discount, total=q.total, promo_code_id=promo_id, contact_name='QA', contact_phone='+380671234567', payment_method='card')
        order_lines = [OrderLine(product_id=line.product_id, name=line.product.name, price=line.product.price, qty=line.qty) for line in lines]
        before = (await repo.get_product(products[0].id)).stock
        held_promo = await session.get(models.PromoCode, promo_id)
        async with Session() as other_session:
            await SqlRepository(other_session).update_promo(promo_id, {'category_ids': [b.id]})
        r.check(held_promo.category_ids == [a.id], 'test retains stale ORM promotion before locked refresh')
        rejected, status = await repo.create_checkout_order_atomic(draft, order_lines, promo_id=promo_id)
        r.check(rejected is None and status == 'promo', 'promo category change before commit rejects stale discount')
        r.check((await repo.get_product(products[0].id)).stock == before and len(await repo.get_cart(user.id)) == 2, 'rollback restores stock and retains cart')
        await repo.update_promo(promo_id, {'category_ids': [a.id]})
        held_product = await session.get(models.Product, products[0].id)
        async with Session() as other_session:
            await SqlRepository(other_session).update_product(products[0].id, {'category_id': b.id})
        r.check(held_product.category_id == a.id, 'test retains stale ORM product before locked refresh')
        rejected, status = await repo.create_checkout_order_atomic(draft, order_lines, promo_id=promo_id)
        r.check(rejected is None and status == 'promo', 'product category change before commit rejects stale discount')
        await repo.update_promo(promo_id, {'category_ids': [999999]})
        r.check(not (await svc.check_promo(repo, 'ONLYA', user.id, draft.subtotal)).ok, 'deleted category never broadens the code to all products')
        response = await client.put(f'/api/promos/{promo_id}', headers=admin, json={**body, 'category_ids': []})
        r.check(response.status_code == 200 and response.json()['category_ids'] == [], 'explicit all-products selection removes scope')
    await Session.kw['bind'].dispose()
asyncio.run(run())
raise SystemExit(bool(r.done()))
