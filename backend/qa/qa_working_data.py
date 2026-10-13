"""F08/F09: complete pages, filter counts, ownership and store calendar days."""
from qa_paths import qa_db_path, qa_db_url
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from httpx import ASGITransport, AsyncClient
from qa_common import Report, boot, init_data

app, Session, fake = boot(qa_db_path('shop_stage2_working_data_test.db'))
from api.auth import create_token
from shop.entities import OperatorRole, OrderStatus
from shop import models as m
from shop.services.shop_settings import ShopSettings, prime_cache
from shop.services.calendar import day_bounds
from shop.services.analytics import window

r = Report('WORKING DATA')
prime_cache(replace(ShopSettings.from_env(), timezone='Europe/Kyiv'))
UTC = timezone.utc

async def main():
    now = datetime(2026, 10, 12, 12, tzinfo=UTC)
    async with Session() as s:
        users = [m.User(tg_id=8100+i, first_name=f'Клієнт {i}', referral_code=f'T{i:07d}',
                        search_key=f'клієнт {i}' + (' 100%_точно' if i == 3 else ''),
                        created_at=now, age_confirmed=True) for i in range(135)]
        s.add_all(users)
        await s.flush()
        uid, other = users[0].id, users[1].id
        orders = [m.Order(user_id=uid, status=OrderStatus.ACCEPTED if i == 0 else OrderStatus.DONE,
                          search_key=f'тест {i}', contact_name='Тест', contact_phone='+380671234567',
                          created_at=now - timedelta(minutes=235-i), total=10) for i in range(235)]
        s.add_all(orders)
        s.add(m.Order(user_id=other, status=OrderStatus.NEW, contact_name='Інший', contact_phone='1',
                      created_at=now, search_key='чужий', total=1))
        await s.flush()
        oldest = orders[0].id
        # Boundary orders each have a distinct search token, UTC microseconds adjacent to local days.
        for day in ['2026-10-12', '2026-03-29', '2026-10-25', '2026-02-28', '2026-12-31']:
            start, end = day_bounds(day, ZoneInfo('Europe/Kyiv'))
            for moment in [start-timedelta(microseconds=1), start, start+timedelta(minutes=90), end-timedelta(microseconds=1), end]:
                s.add(m.Order(user_id=other, status=OrderStatus.DONE, search_key=day,
                              contact_name='Межа', contact_phone='1', created_at=moment, total=1))
        await s.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        auth = {'Authorization': 'Bearer '+create_token('admin', OperatorRole.SYSADMIN, 0, 'QA')}
        for endpoint, count in [('customers',135),('orders',261)]:
            found = []
            for offset in range(0,count,50):
                resp = await c.get('/api/'+endpoint, params={'paginated':'true','limit':50,'offset':offset}, headers=auth)
                r.check(resp.status_code == 200, f'{endpoint} offset={offset}: HTTP 200', resp.text[:180])
                data=resp.json()
                found.extend(x['id'] for x in data['items'])
                r.check(data['total'] == count and data['has_more'] == (offset+len(data['items']) < count),
                        f'{endpoint} offset={offset}: точний total та has_more')
            r.check(len(found) == count and len(set(found)) == count and found == sorted(found, reverse=True) if endpoint=='customers' else len(found)==count and len(set(found))==count,
                    f'{endpoint}: усі записи, без дублів на однакових датах')
            resp = await c.get('/api/'+endpoint,headers=auth)
            r.check(isinstance(resp.json(),list) and len(resp.json())==100, f'{endpoint}: сумісність старого array API')
            for params in [{'limit':0},{'limit':501},{'offset':-1}]:
                r.check((await c.get('/api/'+endpoint,params=params,headers=auth)).status_code==422,
                        f'{endpoint}: відхилено {params}')
        for token, expected in [('100%_',1), ('клієнт',135),('відсутній',0)]:
            data=(await c.get('/api/customers',params={'paginated':'true','search':token},headers=auth)).json()
            r.check(data['total']==expected, f'customers: literal search {token}: total={expected}')
        data=(await c.get('/api/customers',params={'paginated':'true','blocked':'true'},headers=auth)).json()
        r.check(data['total']==0, 'blocked count відповідає відбору')
        for params,expected in [({'status':'accepted'},1),({'status':'done'},259),({'legacy_only':'true'},261),({'crm_status_id':'9'},0)]:
            data=(await c.get('/api/orders',params={'paginated':'true',**params},headers=auth)).json()
            r.check(data['total']==expected and len(data['items'])==min(expected,100), f'orders: фільтр і total {params}')
        empty=(await c.get('/api/orders',params={'paginated':'true','offset':500},headers=auth)).json()
        r.check(empty['items']==[] and empty['total']==261 and not empty['has_more'],'сторінка поза історією має точну кількість і явний кінець')
        for day in ['2026-10-12','2026-03-29','2026-10-25','2026-02-28','2026-12-31']:
            data=(await c.get('/api/orders',params={'paginated':'true','search':day,'date_from':day,'date_to':day},headers=auth)).json()
            r.check(data['total']==3 and len(data['items'])==3, f'{day}: local start inclusive / next midnight exclusive')
        for params in [{'date_from':'2026-02-30'},{'date_to':'9999-12-31'},{'date_from':'2026-10-13','date_to':'2026-10-12'}]:
            r.check((await c.get('/api/orders',params=params,headers=auth)).status_code==422, f'некоректні дати: {params}')
        shop=init_data(8100)
        seen=[]
        for offset in range(0,235,20):
            data=(await c.get('/api/shop/orders',params={'paginated':'true','limit':20,'offset':offset},headers=shop)).json()
            seen.extend(x['id'] for x in data['items'])
            r.check(data['total']==235, f'вітрина offset={offset}: count лише свого клієнта')
        r.check(len(set(seen))==235 and oldest in seen, 'вітрина: історія понад 200 і найстаріше замовлення доступні')
        active=(await c.get('/api/shop/orders/active',headers=shop)).json()
        r.check([x['id'] for x in active]==[oldest], 'активне замовлення поза останніми 20 видиме; чужого немає')
        data=(await c.get(f'/api/customers/{uid}/orders',params={'paginated':'true','limit':50,'offset':200},headers=auth)).json()
        r.check(data['total']==235 and len(data['items'])==35, 'картка клієнта: замовлення після 200 доступні')
        for params in [{'offset':-1},{'limit':0},{'limit':101}]:
            r.check((await c.get('/api/shop/orders',params=params,headers=shop)).status_code==422, f'вітрина відхиляє {params}')
        r.check((await c.get('/api/shop/orders/active')).status_code in (401,403), 'активні замовлення потребують авторизації')
    for day,hours in [('2026-03-29',23),('2026-10-25',25),('2026-10-12',24)]:
        start,end=day_bounds(day,ZoneInfo('Europe/Kyiv'))
        r.check((end-start).total_seconds()==hours*3600, f'{day}: календарна доба {hours} годин')
        analytics=window(ZoneInfo('Europe/Kyiv'),period='custom',date_from=day,date_to=day,compare='none',now=datetime(2027,1,1,tzinfo=UTC))
        r.check(analytics['since']==start and analytics['until']==end, f'{day}: Orders / analytics мають однакові межі')
    # Runtime-configured zones, not a hard-coded Kyiv offset.
    prime_cache(replace(ShopSettings.from_env(),timezone='America/New_York'))
    async with Session() as s:
        from shop.repo.sql import SqlRepository
        repo=SqlRepository(s)
        rows=await repo.list_orders(search='2026-10-12',date_from='2026-10-12',date_to='2026-10-12')
        r.check(len(rows)==2,'фільтр враховує зміну timezone магазину')
asyncio.run(main())
raise SystemExit(bool(r.done()))
