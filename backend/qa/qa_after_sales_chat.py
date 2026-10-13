"""F10/F13/F14: real SQL policy/history/ACK. No real deliveries."""
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
DB_DIR=TemporaryDirectory(prefix='elfar-after-sales-')
DB='sqlite+aiosqlite:///'+DB_DIR.name+'/chat.db'
os.environ.update(BOT_TOKEN='777001:TESTTOKEN',JWT_SECRET='t'*32,DATABASE_URL=DB)
os.environ.setdefault('TRUSTED_HOSTS','testserver,localhost,127.0.0.1')
from sqlalchemy import delete
from shop import models as m
from shop.entities import Order, OrderStatus as S
from shop.db import engine
from shop.repo.factory import open_repo
from shop.services import order_chat as chat
from shop.services.chat_access import can_chat,chat_until
from api.routers import shop,orders
from api.schemas import MessageReadIn,OrderOut
from fastapi import HTTPException
from pydantic import ValidationError
from bot.handlers.chat import _deliver
NOW=datetime.now(timezone.utc)
class PolicyTests(unittest.TestCase):
 def test_old_order_recent_completion(self):
  o=Order(1,1,status=S.DONE,created_at=NOW-timedelta(days=90),completed_at=NOW)
  self.assertTrue(can_chat(o,NOW));self.assertEqual(chat_until(o),NOW+timedelta(days=7))
 def test_exact_expiry_boundary(self):
  o=Order(1,1,status=S.CANCELLED,completed_at=NOW-timedelta(days=7))
  self.assertTrue(can_chat(o,NOW-timedelta(microseconds=1)));self.assertFalse(can_chat(o,NOW))
 def test_naive_sqlite_dates_are_utc(self):
  o=Order(1,1,status=S.DONE,completed_at=NOW.replace(tzinfo=None))
  self.assertTrue(can_chat(o,NOW));self.assertEqual(chat_until(o).tzinfo,timezone.utc)
 def test_unknown_completion_is_closed(self):
  self.assertFalse(can_chat(Order(1,1,status=S.DONE,created_at=NOW),NOW))
 def test_open_has_no_deadline(self):
  o=Order(1,1,status=S.SHIPPED,created_at=NOW-timedelta(days=90))
  self.assertTrue(can_chat(o,NOW));self.assertIsNone(chat_until(o))
 def test_crm_authority(self):
  o=Order(1,1,status=S.ACCEPTED,crm_id='1',business_state='sale',completed_at=NOW-timedelta(days=8))
  self.assertFalse(can_chat(o,NOW));o.status=S.DONE;o.business_state='pending';self.assertTrue(can_chat(o,NOW))
 def test_ack_validation(self):
  self.assertEqual(MessageReadIn(message_ids=[1,1,2]).message_ids,[1,2])
  for ids in ([0],[-1],list(range(1,502))):
   with self.assertRaises(ValidationError):MessageReadIn(message_ids=ids)
 def test_telegram_order_selection_has_all_pages(self):
  items=[Order(i,1) for i in range(1,27)]
  ids=[]
  for offset in [0,8,16,24]:
   keyboard=chat.pick_order_keyboard(items,offset)
   ids += [int(b.callback_data.split(':')[1]) for row in keyboard.inline_keyboard for b in row if b.callback_data and b.callback_data.startswith('chat:')]
  self.assertEqual(ids,list(range(1,27)))
  self.assertTrue(any(b.callback_data=='chatpage:8' for row in chat.pick_order_keyboard(items).inline_keyboard for b in row))

class SQLTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  async with engine.begin() as c:
   await c.run_sync(m.Base.metadata.create_all)
   for table in reversed(m.Base.metadata.sorted_tables):await c.execute(delete(table))
  async with open_repo() as r:
   self.user=await r.create_user(1001,None,'QA',None);await r.confirm_age(self.user);self.user=await r.get_user(self.user.id)
   self.other=await r.create_user(1002,None,'Other',None)
 async def asyncTearDown(self):await engine.dispose()
 async def create(self,**data):
  async with open_repo() as r:
   row=m.Order(user_id=self.user.id,total=Decimal('19.90'))
   for k,v in data.items():setattr(row,k,v)
   r.s.add(row);await r.s.commit();return await r.get_order(row.id)
 async def message(self,o,direction='out',**values):
  async with open_repo() as r:return await r.add_order_message({'order_id':o.id,'user_id':o.user_id,'direction':direction,'text':'QA','author':'QA','is_read':False,**values})
 async def expire(self,r,o):
  row=await r.s.get(m.Order,o.id);row.status=m.OrderStatus.DONE;row.completed_at=NOW-timedelta(days=8);await r.s.commit()
 async def test_local_completion_stable_reopen(self):
  o=await self.create(status=S.SHIPPED,created_at=NOW-timedelta(days=20))
  async with open_repo() as r:
   done,_,changed=await r.transition_order_status_atomic(o.id,S.SHIPPED,S.DONE,{'business_state':'sale'})
   self.assertTrue(changed);self.assertIsNotNone(done.completed_at);self.assertTrue(done.can_chat)
   edited=await r.update_order(o.id,{'admin_note':'edited'});self.assertEqual(edited.completed_at,done.completed_at)
   replay,_,changed=await r.transition_order_status_atomic(o.id,S.DONE,S.DONE)
   self.assertFalse(changed);self.assertEqual(replay.completed_at,done.completed_at)
   reopened=await r.update_order(o.id,{'status':S.ACCEPTED,'business_state':'pending'})
   self.assertIsNone(reopened.completed_at);self.assertTrue(reopened.can_chat)
 async def test_crm_completion_refresh_reopen(self):
  o=await self.create(status=S.SHIPPED,crm_id='CRM1')
  async with open_repo() as r:
   done=await r.update_order(o.id,{'crm_status_id':'2','crm_status_name':'Продаж'});self.assertIsNotNone(done.completed_at)
   again=await r.update_order(o.id,{'crm_status_id':'2','crm_status_name':'Продаж','crm_fetched_at':NOW})
   self.assertEqual(done.completed_at,again.completed_at)
   reopened=await r.update_order(o.id,{'crm_status_id':'1','crm_status_name':'Новий'});self.assertIsNone(reopened.completed_at)
   closed=await r.set_order_business_state(o.id,'refusal',changed_at=NOW)
   self.assertEqual(closed.completed_at.replace(tzinfo=timezone.utc),NOW)
 async def test_explicit_crm_completion_timestamp_is_preserved(self):
  o=await self.create(crm_id='CRM1')
  moment=NOW-timedelta(days=3)
  async with open_repo() as r:
   closed=await r.update_order(o.id,{'crm_status_name':'Продаж','business_state_at':moment})
   self.assertEqual(closed.completed_at,moment)
   again=await r.update_order(o.id,{'crm_fetched_at':NOW})
   self.assertEqual(again.completed_at,moment)
 async def test_cancel_stamps_once(self):
  o=await self.create()
  async with open_repo() as r:
   closed,_,changed=await r.cancel_order_atomic(o.id,S.NEW);self.assertTrue(changed);self.assertIsNotNone(closed.completed_at)
   replay,_,changed=await r.cancel_order_atomic(o.id,S.CANCELLED)
   self.assertFalse(changed);self.assertEqual(closed.completed_at,replay.completed_at)
 async def test_chat_list_beyond_20(self):
  o=await self.create(created_at=NOW-timedelta(days=50))
  async with open_repo() as r:await r.update_order(o.id,{'status':S.DONE,'business_state':'sale'})
  for _ in range(25):await self.create()
  async with open_repo() as r:
   self.assertIn(o.id,[x.id for x in await chat.open_orders_for(r,self.user.id)])
   payload=await shop.chattable_orders(user=self.user,repo=r);row=next(x for x in payload if x['id']==o.id)
   self.assertTrue(row['can_chat']);self.assertIsNotNone(row['chat_until'])
   schema=OrderOut.model_validate(await r.get_order(o.id));self.assertTrue(schema.can_chat)
 async def test_get_has_no_ack(self):
  o=await self.create();await self.message(o)
  async with open_repo() as r:
   await shop.order_chat_log(o.id,None,None,200,self.user,r)
   self.assertFalse((await r.list_order_messages(o.id))[0].is_read)
 async def test_exact_ack_excludes_old_new_incoming_foreign(self):
  o=await self.create();other=await self.create(user_id=self.other.id)
  old=await self.message(o);seen=await self.message(o);incoming=await self.message(o,'in');foreign=await self.message(other)
  async with open_repo() as r:await r.list_order_messages(o.id,limit=2)
  late=await self.message(o)
  async with open_repo() as r:
   ack=await shop.order_chat_read(o.id,MessageReadIn(message_ids=[seen.id,incoming.id,foreign.id]),self.user,r)
   self.assertEqual(ack['marked'],1);self.assertEqual(await r.mark_client_read(o.id,[seen.id]),0)
   flags={x.id:x.is_read for x in await r.list_order_messages(o.id)}
   self.assertFalse(flags[old.id]);self.assertTrue(flags[seen.id]);self.assertFalse(flags[incoming.id]);self.assertFalse(flags[late.id])
   self.assertFalse((await r.list_order_messages(other.id))[0].is_read)
 async def test_staff_exact_ack_empty_noop(self):
  o=await self.create();a=await self.message(o,'in');await self.message(o,'in')
  async with open_repo() as r:
   self.assertEqual((await orders.mark_order_messages_read(o.id,repo=r))['marked'],0)
   self.assertEqual((await orders.mark_order_messages_read(o.id,MessageReadIn(message_ids=[a.id]),r))['marked'],1)
   self.assertFalse((await r.list_order_messages(o.id))[-1].is_read)
 async def test_history_and_delta_pages_no_gaps(self):
  o=await self.create()
  async with open_repo() as r:
   r.s.add_all([m.OrderMessage(order_id=o.id,user_id=o.user_id,direction='out',author='QA',text=str(i),is_read=False) for i in range(451)])
   await r.s.commit();history=[];before=None
   while True:
    page=await r.list_order_messages(o.id,limit=200,before_id=before)
    if not page:break
    history=page+history;before=page[0].id
   self.assertEqual([x.text for x in history],[str(i) for i in range(451)])
   delta=[];after=0
   while True:
    page=await r.list_order_messages(o.id,after_id=after)
    if not page:break
    delta+=page;after=page[-1].id
   self.assertEqual([x.id for x in history],[x.id for x in delta])
 async def test_ownership_get_ack_access(self):
  o=await self.create(user_id=self.other.id)
  async with open_repo() as r:
   for fn,args in [(shop.order_chat_log,(o.id,None,None,200,self.user,r)),(shop.order_chat_read,(o.id,MessageReadIn(message_ids=[1]),self.user,r)),(shop.order_chat_access,(o.id,self.user,r))]:
    with self.assertRaises(HTTPException) as e:await fn(*args)
    self.assertEqual(e.exception.status_code,404)
 async def test_expired_text_photo_bot_history(self):
  o=await self.create()
  async with open_repo() as r:
   await self.expire(r,o)
   for fn,args in [(shop.order_chat_send,(o.id,shop.ChatSendIn(text='QA'),self.user,r)),(shop.order_chat_photo,(o.id,AsyncMock(),self.user,r))]:
    with self.assertRaises(HTTPException) as e:await fn(*args)
    self.assertEqual(e.exception.status_code,409)
   self.assertIn('закрито',await _deliver(r,self.user,'QA',o.id))
   self.assertEqual(await shop.order_chat_log(o.id,None,None,200,self.user,r),[])
 async def test_archive_exact_ack(self):
  o=await self.create();msg=await self.message(o)
  async with open_repo() as r:
   row=await r.s.get(m.Order,o.id);row.status=m.OrderStatus.DONE;row.updated_at=NOW-timedelta(days=200);row.completed_at=row.updated_at
   await r.s.commit();self.assertEqual((await r.archive_cold_messages(180))['orders'],1)
   self.assertEqual(await r.mark_client_read(o.id,[msg.id]),1)
   self.assertTrue((await r.list_order_messages(o.id))[0].is_read)
   self.assertEqual(await r.mark_client_read(o.id,[msg.id]),0)
 async def test_old_attachment_outside_latest_page(self):
  o=await self.create();first=await self.message(o,file_kind='photo',file_id='old-file')
  async with open_repo() as r:
   r.s.add_all([m.OrderMessage(order_id=o.id,user_id=o.user_id,direction='out',author='QA',text='later',is_read=False) for _ in range(201)])
   await r.s.commit();bot=AsyncMock();bot.get_file.return_value.file_path='fake'
   import io
   bot.download_file.return_value=io.BytesIO(b'photo')
   with patch('api.routers.telegram._instances',return_value=(bot,None)):
    response=await shop.order_chat_file(o.id,first.id,self.user,r);self.assertEqual(response.status_code,200)
   bot.get_file.assert_awaited_once_with('old-file')
 async def test_reply_expired_not_routed(self):
  o=await self.create();await self.message(o,tg_message_id=99);await self.create(status=S.ACCEPTED)
  async with open_repo() as r:
   await self.expire(r,o)
   from types import SimpleNamespace
   self.assertIsNone(await chat.route_incoming(r,self.user,SimpleNamespace(reply_to_message=SimpleNamespace(message_id=99))))
 async def test_expired_callback_preserves_support_and_selection(self):
  o=await self.create()
  async with open_repo() as r:
   await self.expire(r,o)
   from bot.handlers.chat import pick_order
   callback=AsyncMock();callback.data=f'chat:{o.id}'
   with patch.object(r,'set_chat_order',new_callable=AsyncMock) as selected:
    await pick_order(callback,r,self.user)
    selected.assert_not_awaited();callback.message.edit_text.assert_not_awaited()
    self.assertIn('закрито',callback.answer.call_args.args[0])

class MigrationTests(unittest.TestCase):
 def load_revision(self):
  import importlib.util
  path=Path(__file__).resolve().parents[1]/'alembic/versions/f7d4b2c90a61_order_chat_completion.py'
  spec=importlib.util.spec_from_file_location('completion_migration',path)
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  return module
 def test_historical_backfill_upgrade_downgrade(self):
  import sqlalchemy as sa
  from alembic.operations import Operations
  from alembic.migration import MigrationContext
  local=sa.create_engine('sqlite:///:memory:')
  with local.begin() as c:
   c.execute(sa.text('CREATE TABLE orders (id INTEGER PRIMARY KEY, status VARCHAR(16), business_state VARCHAR(16), business_state_at DATETIME, updated_at DATETIME, created_at DATETIME)'))
   c.execute(sa.text("INSERT INTO orders VALUES (1,'DONE','sale','2026-10-12 10:00:00','2026-10-13 10:00:00','2026-09-01 10:00:00'),(2,'CANCELLED','pending',NULL,'2026-10-11 10:00:00','2026-09-01 10:00:00'),(3,'NEW','pending',NULL,'2026-10-13 10:00:00','2026-10-13 10:00:00')"))
   with Operations.context(MigrationContext.configure(c)):self.load_revision().upgrade()
   values=c.execute(sa.text('SELECT completed_at FROM orders ORDER BY id')).scalars().all()
   self.assertEqual(values,['2026-10-12 10:00:00','2026-10-11 10:00:00',None])
   self.assertEqual(c.execute(sa.text('SELECT status FROM orders ORDER BY id')).scalars().all(),['DONE','CANCELLED','NEW'])
   with Operations.context(MigrationContext.configure(c)):self.load_revision().downgrade()
   self.assertNotIn('completed_at',[x['name'] for x in sa.inspect(c).get_columns('orders')])
 def test_postgres_ddl_and_single_head(self):
  from io import StringIO
  from alembic.operations import Operations
  from alembic.migration import MigrationContext
  from alembic.config import Config
  from alembic.script import ScriptDirectory
  out=StringIO()
  with Operations.context(MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':out})):self.load_revision().upgrade()
  self.assertIn('TIMESTAMP WITH TIME ZONE',out.getvalue());self.assertIn('UPDATE orders',out.getvalue())
  backend=Path(__file__).resolve().parents[1]
  cfg=Config(str(backend/'alembic.ini'));cfg.set_main_option('script_location',str(backend/'alembic'))
  self.assertEqual(ScriptDirectory.from_config(cfg).get_heads(),['f7d4b2c90a61'])

if __name__=='__main__':unittest.main(verbosity=2)
