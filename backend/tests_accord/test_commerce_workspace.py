"""Cross-channel operational queues and complete server-paginated catalog."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from api.auth import Principal,require_staff
from api.routers import orders,catalog
from shop.entities import OperatorRole as Role,OrderStatus as Status
from shop import models as m
from shop.repo.factory import get_repo
from shop.repo.sql import SqlRepository

@pytest_asyncio.fixture
async def api():
    engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as connection:await connection.run_sync(m.Base.metadata.create_all)
    async with async_sessionmaker(engine,expire_on_commit=False)() as session:
        repo=SqlRepository(session);who=[Principal(login='owner',name='Адміністратор',role=Role.SYSADMIN,operator_id=0)]
        app=FastAPI();app.include_router(orders.router,prefix='/api/orders');app.include_router(catalog.router,prefix='/api/catalog')
        app.dependency_overrides[get_repo]=lambda:repo
        app.dependency_overrides[require_staff]=lambda:who[0]
        session.add(m.User(id=1,tg_id=-123,referral_code='COMMERCE-USER'))
        await session.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://dashboard.example.test') as client:
            yield client,session,who,app
    await engine.dispose()


async def seed_orders(session):
    now=datetime.now(timezone.utc)
    rows=[
        m.Order(id=1,user_id=1,status=Status.NEW,attribution={'source':'google','channel':'telegram_bot'},payment_method='cod',delivery_method='warehouse',search_key='покупець +380671234567',contact_name='Покупець',contact_phone='+380671234567',created_at=now-timedelta(days=2)),
        m.Order(id=2,user_id=1,status=Status.NEW,attribution={'source':'instagram','session_id':'miniapp-session'},payment_method='card',delivery_method='courier',created_at=now-timedelta(days=1)),
        m.Order(id=3,user_id=1,status=Status.ACCEPTED,attribution={'source':'telegram_bot'},payment_method='cod',tracking_number='20450000123456'),
        m.Order(id=4,user_id=1,status=Status.SHIPPED,attribution=None),
        m.Order(id=5,user_id=1,status=Status.CANCELLED,attribution={'source':'telegram_bot'}),
        m.Order(id=6,user_id=1,status=Status.NEW,business_state='refusal',attribution={'source':'telegram_bot'},crm_id='refused-in-crm'),
    ]
    session.add_all(rows);await session.commit()


@pytest.mark.asyncio
async def test_workspace_counts_match_actionable_queue_and_channels(api):
    client,session,_,_=api;await seed_orders(session)
    result=await client.get('/api/orders/operations')
    assert result.status_code==200,result.text
    data=result.json()
    assert data['orders']=={'new':2,'open':4,'without_tracking':2}
    assert data['channels']=={'miniapp':1,'bot':2,'unknown':1}
    assert [row['id'] for row in data['queue']]==[1,2]
    assert 'crm_snapshot' not in result.text and 'token' not in result.text
    for queue in ['new','open','without_tracking']:
        page=await client.get('/api/orders',params={'queue':queue,'paginated':True})
        assert page.status_code==200,page.text
        assert page.json()['total']==data['orders'][queue]
    for channel,total in data['channels'].items():
        page=(await client.get('/api/orders',params={'queue':'open','channel':channel,'paginated':True})).json()
        assert page['total']==total
        if channel=='bot':
            assert {row['attribution'].get('channel','') for row in page['items']}=={'telegram_bot',''}


@pytest.mark.asyncio
async def test_order_filters_search_and_count_use_same_predicates(api):
    client,session,_,_=api;await seed_orders(session)
    for filters,ids in [({'channel':'bot','queue':'new','payment_method':'cod','delivery_method':'warehouse'},[1]),
                       ({'payment_method':'unknown'},[6,5,4]),({'search':'#1'},[1]),
                       ({'search':'+38 (067) 123-45-67'},[1]),({'search':'20450000123456'},[3])]:
        response=await client.get('/api/orders',params={**filters,'paginated':True})
        assert response.status_code==200,response.text
        assert sorted(row['id'] for row in response.json()['items'])==sorted(ids)
        assert response.json()['total']==len(ids)
    for filters in [{'channel':'invented'},{'queue':'bad'},{'delivery_method':'bad'},{'payment_method':'bad'}]:
        assert (await client.get('/api/orders',params=filters)).status_code==422


@pytest.mark.asyncio
async def test_explicit_channel_takes_precedence_over_campaign_source(api):
    client,session,_,_=api
    session.add(m.Order(id=20,user_id=1,attribution={'source':'telegram_bot','channel':'telegram_miniapp'}))
    await session.commit()
    assert (await client.get('/api/orders/operations')).json()['channels']['miniapp']==1
    assert (await client.get('/api/orders?paginated=true&channel=miniapp')).json()['total']==1
    assert (await client.get('/api/orders?paginated=true&channel=bot')).json()['total']==0
    item=(await client.get('/api/orders?paginated=true&channel=miniapp')).json()['items'][0]
    assert item['attribution']['channel']=='telegram_miniapp'
    session.add(m.Order(id=21,user_id=1,crm_snapshot={'utm':{'source':'telegram_bot'}}))
    await session.commit()
    legacy=(await client.get('/api/orders?paginated=true&channel=bot')).json()
    assert legacy['total']==1 and legacy['items'][0]['attribution']['source']=='telegram_bot'


@pytest.mark.asyncio
async def test_stock_attention_counts_and_catalog_links_agree(api):
    client,session,_,_=api
    session.add_all([
        m.Product(id=1,sku='LOW',name='Залишок',price=100,stock=2),
        m.Product(id=2,sku='ZERO',name='Немає',price=200,stock=0),
        m.Product(id=3,sku='UNPRICED',name='Без ціни',price=0,stock=10),
        m.Product(id=4,sku='HIDDEN',name='Прихований',price=100,stock=1,is_active=False),
        m.Product(id=5,sku='IMAGE',name='З фото',price=300,stock=10,photo_url='/media/photo.jpg'),
    ]);await session.commit()
    data=(await client.get('/api/orders/operations')).json()
    assert data['stock']=={'available':2,'low':1,'out':1,'unpriced':1,'missing_photos':2}
    for inventory,expected in [('available',2),('low',1),('out',1),('unpriced',1),('missing_photos',2),('hidden',1)]:
        page=await client.get('/api/catalog/products',params={'paginated':True,'inventory':inventory})
        assert page.status_code==200,page.text
        assert page.json()['total']==expected


@pytest.mark.asyncio
async def test_catalog_pagination_reaches_products_after_500_and_sorts_all_rows(api):
    client,session,_,_=api
    session.add_all([m.Product(id=index,sku='CAT-'+str(index),name='Товар '+str(index),price=Decimal(index),stock=10) for index in range(1,522)])
    await session.commit()
    page=await client.get('/api/catalog/products?paginated=true&sort=price-desc&limit=20&offset=500')
    assert page.status_code==200,page.text
    data=page.json();assert data['total']==521 and len(data['items'])==20
    assert [row['id'] for row in data['items']]==list(range(21,1,-1))
    last=(await client.get('/api/catalog/products?paginated=true&sort=price-desc&limit=20&offset=520')).json()
    assert [row['id'] for row in last['items']]==[1]
    assert isinstance((await client.get('/api/catalog/products')).json(),list)


@pytest.mark.asyncio
async def test_manager_has_operational_access_and_anonymous_is_denied(api):
    client,session,who,app=api
    who[0]=Principal(login='sales',name='Менеджер',role=Role.MANAGER,operator_id=2)
    manager=await client.get('/api/orders/operations')
    assert manager.status_code==200 and 'pending_comments' not in manager.json()
    del app.dependency_overrides[require_staff]
    assert (await client.get('/api/orders/operations')).status_code==401
    assert (await client.get('/api/catalog/products?paginated=true')).status_code==401
