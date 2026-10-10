"""Behavioral analytics, calendar boundaries, API roles and migration checks."""
import os
os.environ.update(BOT_TOKEN="1:test", JWT_SECRET="a" * 48, DASHBOARD_PASSWORD="Test-password-123", TRUSTED_HOSTS="testserver,t,localhost", DATABASE_URL="sqlite+aiosqlite:///:memory:")
import asyncio
from datetime import datetime, date, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, func
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from shop import models as m
from shop.entities import User, OperatorRole
from shop.services import analytics as a
from shop.repo.sql import SqlRepository
from api.auth import require_staff, require_admin, Principal
from api.webapp_auth import require_webapp_user
from shop.repo.factory import get_repo
from api.routers import stats, shop
UTC=timezone.utc
passed=0
def check(name, ok):
    global passed
    assert ok, name
    passed += 1
    print(f"✓ {name}")
def dt(value): return datetime.fromisoformat(value).replace(tzinfo=UTC)

async def main():
    tz=ZoneInfo('Europe/Kyiv')
    w=a.window(tz, month='2024-02', now=dt('2024-04-10T09:00:00'))
    check('leap February full calendar month', (w['until']-w['since']).days == 29)
    check('previous full month is January', w['previous_since'].astimezone(tz).date()==date(2024,1,1) and w['previous_until'].astimezone(tz).date()==date(2024,2,1))
    w=a.window(tz, now=dt('2024-03-10T09:00:00'))
    check('MTD same elapsed calendar portion', w['previous_until'].astimezone(tz).day==10)
    w=a.window(tz, month='2024-03', now=dt('2024-05-01T09:00:00'))
    check('DST month preserves local boundaries', w['since'].hour==22 and w['until'].hour==21)
    w=a.window(tz, period='custom', date_from='2024-02-01', date_to='2024-02-01', now=dt('2024-04-10T09:00:00'))
    check('custom end date inclusive', (w['until']-w['since']).days==1)
    for args in ({'month':'2024-13'}, {'month':'2025-01'}, {'period':'custom','date_from':'2024-04-02','date_to':'2024-04-01'}, {'compare':'month'}):
        try: a.window(tz, now=dt('2024-04-10T09:00:00'), **args)
        except Exception as e: check(f'invalid calendar rejected {args}', getattr(e,'status_code',None)==422)
        else: raise AssertionError(args)
    from urllib.parse import urlsplit, parse_qs
    target = a.attributed_button_url('https://t.me/elfarshop_bot/elfar', {'utm_source':'google','utm_campaign':'Осінь','utm_medium':'cpc'})
    payload = parse_qs(urlsplit(target).query)['startapp'][0]
    import json, base64
    decoded = json.loads(base64.urlsafe_b64decode(payload[4:]+'='*(-len(payload[4:])%4)))
    check('promo UTM survives Telegram boundary incl unicode', decoded['source']=='google' and decoded['campaign']=='Осінь' and len(payload)<=512)
    chat=a.attributed_button_url('https://t.me/elfarshop_bot/elfar?startapp=chat_7', {'utm_source':'google'})
    check('promo attribution preserves chat destination', parse_qs(urlsplit(chat).query)['startapp']==['chat_7'])
    check('actual historical CRM UTM reused without inventing metadata', a.order_attribution(None, {'utm':{'source':'Google Ads','campaign':'old'}})['source']=='google_ads')
    check('checkout attribution wins over later CRM metadata', a.order_attribution({'source':'facebook'},{'utm':{'source':'google'}})['source']=='facebook')
    check('zero denominators are unavailable', a.ratio(0,0) is None and a.delta(10,0) is None)
    engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(m.Base.metadata.create_all)
        def migration_roundtrip(connection):
            import importlib.util
            from pathlib import Path
            from alembic.migration import MigrationContext
            from alembic.operations import Operations
            from sqlalchemy import inspect
            path=Path(__file__).resolve().parents[1] / 'alembic/versions/f2c8a1d96b40_acquisition_analytics.py'
            spec=importlib.util.spec_from_file_location('analytics_migration',path)
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            with Operations.context(MigrationContext.configure(connection)):
                module.downgrade()
                check('migration downgrade removes only analytics additions', 'attribution' not in {c['name'] for c in inspect(connection).get_columns('orders')})
                module.upgrade()
                check('migration upgrade restores attribution and visit/spend tables', 'attribution' in {c['name'] for c in inspect(connection).get_columns('orders')} and 'marketing_spend' in inspect(connection).get_table_names())
        await conn.run_sync(migration_roundtrip)
    maker=async_sessionmaker(engine,expire_on_commit=False)
    async with maker() as s:
        s.add_all([m.User(id=i,tg_id=100+i,referral_code=f'ref{i}',created_at=dt('2024-01-01T00:00:00')) for i in (1,2,3)])
        await s.commit()
        def order(id,user,when,source, state='sale', created=None, session=None):
            return m.Order(id=id,user_id=user,status=m.OrderStatus.DONE,business_state=state,business_state_at=dt(when),created_at=dt(created or when),total=Decimal(100),payment_method='card',attribution={'source':source, 'session_id':session} if source else None)
        s.add_all([order(1,1,'2024-01-10T10:00:00','google'), order(2,1,'2024-02-10T10:00:00','google',session='session_test_0001'),
          order(3,2,'2024-02-10T10:00:00','facebook',session='session_test_0002'), order(4,2,'2024-02-10T10:00:00','google'),
          order(5,3,'2024-02-12T10:00:00',None), order(6,3,'2024-02-12T10:00:00','direct',state='refusal',created='2024-02-12T09:00:00',session='session_test_0003')])
        s.add(m.MarketingSpend(day=date(2024,2,10),source='google',campaign='',amount=Decimal(50),updated_by='admin',updated_at=dt('2024-02-10T11:00:00')))
        await s.commit()
        for uid in (1,2,3): await a.record_session(s,uid,f'session_test_000{uid}',{'source':('google','facebook','direct')[uid-1]})
        # Replace server-current visit date only in the fixture.
        for visit in (await s.scalars(select(m.AnalyticsSession))).all(): visit.started_at=dt('2024-02-10T08:00:00')
        await s.commit()
        await a.record_session(s,1,'session_test_0001',{'source':'evil'})
        check('visits deduplicated and source immutable', (await s.scalar(select(func.count(m.AnalyticsSession.id))))==3)
        check('cannot link another user visit', 'session_id' not in await a.checkout_attribution(s,3,'session_test_0001',{'source':'direct'}))
        check('owned session links at checkout', (await a.checkout_attribution(s,1,'session_test_0001',{'source':'google'}))['session_id']=='session_test_0001')
        w=a.window(tz,month='2024-02',now=dt('2024-04-01T00:00:00'))
        report=await a.aggregate(s,w)
        metrics=report['metrics']
        check('sale finance excludes refused order', metrics['sales']==Decimal(400) and metrics['revenue']==Decimal(400))
        check('first purchase unique despite identical timestamps', metrics['new_customers']==2)
        check('blended CAC uses first paying customers', metrics['cac']==25)
        check('ROAS excludes organic and unbudgeted channels', metrics['roas']==4 and metrics['ad_sales']==200)
        check('conversion deduplicates checkout sessions incl cancellations', metrics['conversion']==100 and metrics['converted_sessions']==3)
        check('zero calendar days filled with 0', len(report['series'])==29 and report['series'][0]['sales']==0)
        check('unknown historical sources preserved', next(r for r in report['sources'] if r['source']=='unknown')['orders']==1)
        check('coverage calculated from actual attribution', report['attribution_coverage']==75)
        monthly=await a.aggregate(s,w,'month')
        check('monthly totals reconcile with daily', len(monthly['series'])==1 and monthly['series'][0]['sales']==sum(r['sales'] for r in report['series']))
        check('source totals reconcile', sum(r['sales'] for r in report['sources'])==metrics['sales'])
        unknown=await a.order_sources(s,w,'unknown')
        check('unknown filter includes legacy NULL attribution', unknown['total']==1)
        listing=await a.order_sources(s,w,limit=2)
        check('order sources paginated incl non-sales', listing['total']==5 and len(listing['items'])==2)
        async def repo(): yield SqlRepository(s)
        admin=Principal(login='admin', name='Admin', role=OperatorRole.SYSADMIN,operator_id=0)
        app=FastAPI(); app.include_router(stats.router,prefix='/stats'); app.include_router(shop.router,prefix='/shop')
        app.dependency_overrides[get_repo]=repo
        app.dependency_overrides[require_staff]=lambda:admin
        app.dependency_overrides[require_admin]=lambda:admin
        app.dependency_overrides[require_webapp_user]=lambda:User(id=1,tg_id=101,referral_code='ref1')
        # Keep this HTTP test offline: do not instantiate a Telegram sender.
        from api.routers import orders, telegram
        from unittest.mock import AsyncMock
        fake_bot = AsyncMock()
        orders._bot = lambda: fake_bot
        telegram._instances = lambda: (fake_bot, None)
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://testserver') as client:
            resp=await client.get('/stats/report',params={'month':'2024-02','compare':'month','compare_month':'2024-01'})
            from pathlib import Path
            Path('/tmp/analytics-fixture.json').write_text(resp.text)
            check('consolidated API report serializes finance and selected comparison',resp.status_code==200 and Decimal(str(resp.json()['previous']['metrics']['sales']))==100)
            resp=await client.get('/stats/months')
            check('all historical months available',resp.status_code==200 and '2024-01' in resp.json()['months'])
            resp=await client.put('/stats/spend',json={'day':'2024-02-10','source':'Google','amount':'75.25'})
            check('spend upsert normalizes source',resp.status_code==200)
            resp=await client.put('/stats/spend',json={'day':'2024-02-10','source':'google','amount':'100.00'})
            check('spend repeated save replaces rather than duplicates',resp.status_code==200 and (await s.scalar(select(func.count(m.MarketingSpend.id))))==1)
            resp=await client.put('/stats/spend',json={'day':'2024-02-10','source':'google','amount':'-1'})
            check('negative spend rejected',resp.status_code==422)
            resp=await client.post('/shop/analytics/visit',json={'session_id':'session_test_0001','attribution':{'source':'other'}})
            check('visit API replay returns no content',resp.status_code==204)
            s.add(m.Product(id=77,name='QA product',name_lower='qa product',sku='QA777',price=Decimal(100),stock=10))
            s.add(m.CartItem(user_id=1,product_id=77,qty=1))
            await s.commit()
            app.dependency_overrides[require_webapp_user]=lambda:User(id=1,tg_id=101,referral_code='ref1',age_confirmed=True)
            checkout={'checkout_key':'acquisition_checkout_01','contact_surname':'Тест','contact_name':'Покупець',
                      'contact_phone':'+380501234567','city':'Київ','address':'Відділення 1','payment_method':'card',
                      'attribution':{'source':'google','campaign':'original','session_id':'session_test_0001'}}
            resp=await client.post('/shop/checkout',json=checkout)
            check('checkout succeeds with attribution in atomic order transaction',resp.status_code==200)
            order_id=resp.json()['order_id']
            saved=await SqlRepository(s).get_order(order_id)
            check('checkout stores source and owned visit id',saved.attribution['campaign']=='original' and saved.attribution['session_id']=='session_test_0001')
            checkout['attribution']['campaign']='changed'
            resp=await client.post('/shop/checkout',json=checkout)
            saved=await SqlRepository(s).get_order(order_id)
            check('idempotent checkout does not replace original attribution',resp.status_code==200 and resp.json()['order_id']==order_id and saved.attribution['campaign']=='original')
            app.dependency_overrides.pop(require_admin)
            resp=await client.put('/stats/spend',json={'day':'2024-02-10','source':'google','amount':'1'})
            check('spend writes require privileged auth',resp.status_code in (401,403))
        spend = await s.scalar(select(m.MarketingSpend))
        spend.campaign = 'paid'
        for r in (await s.scalars(select(m.Order).where(m.Order.id.in_([2,4])))).all():
            r.attribution = {**r.attribution, 'campaign':'paid'}
        organic = order(77,1,'2024-02-15T10:00:00','google')
        organic.attribution = {'source':'google', 'campaign':'organic'}
        s.add(organic); await s.commit()
        narrowed=await a.aggregate(s,w,'month')
        check('ROAS only funded campaigns in channel and time buckets', narrowed['metrics']['roas']==2 and narrowed['series'][0]['roas']==2 and next(r for r in narrowed['sources'] if r['source']=='google')['roas']==2)
        legacy=await s.get(m.Order,5)
        legacy.crm_snapshot={'utm':{'source':'TikTok Ads','campaign':'historical'}}
        await s.commit()
        legacy_sources=await a.order_sources(s,w,'tiktok_ads')
        check('historical CRM source filter uses display normalization',legacy_sources['total']==1 and legacy_sources['items'][0]['attribution']['campaign']=='historical')
        fallback=await a.aggregate(s,w)
        check('historical CRM UTM included in channel revenue',next(r for r in fallback['sources'] if r['source']=='tiktok_ads')['sales']==100)
        check('legacy without metadata remains unknown', a.order_attribution(None, {})['source']=='unknown')
    await engine.dispose()
    print(f'ACQUISITION ANALYTICS: {passed}/{passed}')

if __name__=='__main__': asyncio.run(main())
