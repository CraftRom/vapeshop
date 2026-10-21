"""Saved financial reports: real authenticated FastAPI/SQLite and migrations."""
import asyncio
from datetime import datetime, date, timezone
from decimal import Decimal
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from sqlalchemy import select, delete, func
from qa_common import boot, Report, seed_operators
from qa_paths import qa_db_path

app, Session, fake = boot(qa_db_path('financial_periods.db'))
from shop import models as m
from shop.entities import OperatorRole
from shop.repo.sql import SqlRepository
from shop.services.financial_periods import digest
from api.auth import create_token

r = Report('FINANCIAL PERIODS')
client = TestClient(app)
admin = {'Authorization': 'Bearer ' + create_token('admin', OperatorRole.SYSADMIN)}
manager = {'Authorization': 'Bearer ' + create_token('manager', OperatorRole.MANAGER, 11)}
dt = lambda value: datetime.fromisoformat(value).replace(tzinfo=timezone.utc)

async def seed():
    async with Session() as s:
        await seed_operators(SqlRepository(s), {11: ('manager', 'Manager', OperatorRole.MANAGER)})
        s.add(m.User(id=24001,tg_id=24001,referral_code='finance_qa',created_at=dt('2024-01-01')))
        await s.flush()
        s.add(m.Order(id=24001,user_id=24001,status=m.OrderStatus.DONE,business_state='sale',
            business_state_at=dt('2024-03-31T20:59:59'),created_at=dt('2024-03-31T20:59:59'),
            total=Decimal('199.90'),payment_method='card',attribution={'source':'google'}))
        s.add(m.MarketingSpend(day=date(2024,3,31),source='google',campaign='',amount=Decimal('17.23'),
            updated_by='admin',updated_at=dt('2024-03-31T20:00:00')))
        await s.commit()
asyncio.run(seed())
URL='/api/stats/closed-periods'
r.check(client.get(URL).status_code==401,'anonymous list rejected')
r.check(client.post(URL,json={'month':'2024-03'}).status_code==401,'anonymous close rejected')
r.check(client.post(URL,headers=manager,json={'month':'2024-03'}).status_code==403,'manager cannot close month')
r.check(client.get(URL,headers=manager).json()=={'items':[]},'staff may read empty list')
for value in ('2024-13','0000-01','1969-12','9999-12',datetime.now(timezone.utc).strftime('%Y-%m'),'2024-3'):
    r.check(client.post(URL,headers=admin,json={'month':value}).status_code==422,'invalid or unfinished month rejected: '+value)
r.check(client.post(URL,headers=admin,json={'month':'2024-03','payload':{}}).status_code==422,'client cannot supply report content')
r.check(client.get(URL+'/2024-03',headers=admin).status_code==404,'missing snapshot is explicit, no live fallback')
response=client.post(URL,headers=admin,json={'month':'2024-03'})
r.check(response.status_code==200,'admin saves completed month: '+response.text[:100])
saved=response.json()
r.check(Decimal(str(saved['analytics']['metrics']['sales']))==Decimal('199.90'),'sale cents preserved')
r.check(Decimal(str(saved['analytics']['metrics']['spend']))==Decimal('17.23'),'spend cents preserved')
r.check(saved['window']['from']=='2024-02-29T22:00:00+00:00' and saved['window']['to']=='2024-03-31T21:00:00+00:00','DST month uses exact local calendar boundaries')
r.check(saved['previous'] is None and not saved['window']['partial'],'saved report is complete and has no live comparison')
r.check(saved['snapshot']['closed_by']=='admin' and saved['snapshot']['timezone'] in ('Europe/Kyiv','Europe/Kiev'),'author and original timezone stored')
r.check(saved['snapshot']['checksum']==digest({k:v for k,v in saved.items() if k!='snapshot'}),'checksum matches serialized content')
listing=client.get(URL,headers=manager).json()['items']
r.check(len(listing)==1 and 'payload' not in listing[0] and listing[0]['closed_at'].endswith('+00:00'),'list returns metadata with UTC timestamp')
r.check(client.get(URL+'/2024-03',headers=manager).json()==saved,'staff reads identical saved report')

async def mutate():
    async with Session() as s:
        row=await s.get(m.Order,24001);row.business_state='refusal';row.total=Decimal('999.99')
        spend=await s.scalar(select(m.MarketingSpend));spend.amount=Decimal('88.88')
        await s.commit()
asyncio.run(mutate())
live=client.get('/api/stats/report?month=2024-03&compare=none',headers=admin).json()
r.check(Decimal(str(live['analytics']['metrics']['sales']))==0 and Decimal(str(live['analytics']['metrics']['spend']))==Decimal('88.88'),'live analytics still follows CRM/spend edits')
r.check(client.get(URL+'/2024-03',headers=admin).json()==saved,'saved report unchanged after CRM and spend edits')
r.check(client.post(URL,headers=admin,json={'month':'2024-03'}).json()==saved,'repeat close returns original without recalculation')
r.check(client.delete(URL+'/2024-03',headers=admin).status_code==405,'API exposes no delete')
r.check(client.put(URL+'/2024-03',headers=admin,json={}).status_code==405,'API exposes no overwrite')

# Actual concurrent requests: only one record, with idempotent explicit retry.
def close_april(_):
    other = TestClient(app)
    try:
        return other.post(URL,headers=admin,json={'month':'2024-04'})
    finally:
        other.close()
with ThreadPoolExecutor(max_workers=2) as pool:
    concurrent=list(pool.map(close_april,range(2)))
r.check(all(x.status_code in (200,409) for x in concurrent) and any(x.status_code==200 for x in concurrent),'concurrent closes succeed or report retryable conflict')
april=client.post(URL,headers=admin,json={'month':'2024-04'})
r.check(april.status_code==200 and all(x.status_code!=200 or x.json()==april.json() for x in concurrent),'explicit retry returns winning snapshot')
async def count():
    async with Session() as s:
        return await s.scalar(select(func.count()).select_from(m.FinancialPeriod))
r.check(asyncio.run(count())==2,'exactly one row per month')

async def corrupt():
    async with Session() as s:
        row=await s.get(m.FinancialPeriod,'2024-03');row.payload={**row.payload,'changes':{'sales':123}}
        await s.commit()
asyncio.run(corrupt())
r.check(client.get(URL+'/2024-03',headers=admin).status_code==409,'corrupt stored report rejected')
r.check(client.post(URL,headers=admin,json={'month':'2024-03'}).status_code==409,'repeat does not silently replace corrupt report')

async def migrations():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import inspect
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    import importlib.util, io
    path=Path(__file__).resolve().parents[1]/'alembic/versions/f9b6d4e20c83_financial_periods.py'
    spec=importlib.util.spec_from_file_location('period_migration',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        def cycle(connection):
            connection.exec_driver_sql('CREATE TABLE sentinel (id INTEGER PRIMARY KEY)')
            with Operations.context(MigrationContext.configure(connection)):
                mod.upgrade()
                r.check('financial_periods' in inspect(connection).get_table_names(),'migration creates snapshot table')
                connection.exec_driver_sql("INSERT INTO financial_periods VALUES ('2024-01','UTC','2024-02-01','qa',1,'checksum','{}')")
                mod.downgrade()
                r.check(inspect(connection).get_table_names()==['sentinel'],'downgrade preserves unrelated data')
                mod.upgrade()
                r.check(inspect(connection).get_pk_constraint('financial_periods')['constrained_columns']==['month'],'roundtrip preserves unique month key')
        await conn.run_sync(cycle)
    buf=io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':buf})):
        mod.upgrade();mod.downgrade()
    r.check('JSONB' in buf.getvalue() and 'TIMESTAMP WITH TIME ZONE' in buf.getvalue(),'PostgreSQL DDL uses JSONB and aware dates')
    await engine.dispose()
asyncio.run(migrations())
client.close()
raise SystemExit(bool(r.done()))
