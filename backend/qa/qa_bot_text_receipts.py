"""F11/F12: real bot updates, bounded HTML, full descriptions, durable receipts."""
import os
from qa_paths import qa_db_url
from tests_bot import RecordingSession, message_update, callback_update
os.environ.update(BOT_TOKEN='123456:TEST',JWT_SECRET='t'*32,DATABASE_URL=qa_db_url('bot_text_receipts.db'),
                  REDIS_URL='',ADMIN_CHAT_ID='-1009999',ADMIN_IDS='900001')
import asyncio, unittest
from decimal import Decimal
from html.parser import HTMLParser
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Update
from shop.telegram_text import split_html,units,send_html,answer_html
from shop.entities import Order,OrderLine,Product,CartLine
from shop.models import Base
from shop.db import engine
from shop.repo.factory import open_repo
from shop.services.shop_settings import ShopSettings,prime_cache
from bot.handlers import cart,catalog,checkout
from bot.factory import build_dispatcher
from bot.states import Checkout

class Parser(HTMLParser):
 def __init__(self): super().__init__(convert_charrefs=True);self.stack=[];self.text=[]
 def handle_starttag(self,tag,attrs):self.stack.append(tag)
 def handle_endtag(self,tag):
  if not self.stack or self.stack.pop()!=tag:raise AssertionError('Unbalanced HTML')
 def handle_data(self,data):self.text.append(data)
def plain(html):
 p=Parser();p.feed(html);p.close()
 if p.stack:raise AssertionError('Unclosed HTML')
 return ''.join(p.text)
class StrictSession(RecordingSession):
 async def make_request(self,bot,method,timeout=None):
  data=method.model_dump(exclude_none=True);text=data.get('text') or data.get('caption')
  if text and type(method).__name__!='AnswerCallbackQuery':
   assert units(text)<=(1000 if 'caption' in data else 3500),type(method).__name__;plain(text)
  buttons=[b for row in data.get('reply_markup',{}).get('inline_keyboard',[]) for b in row]
  assert len(buttons)<=100
  assert all(len(b.get('callback_data','').encode())<=64 for b in buttons)
  return await super().make_request(bot,method,timeout)
class State:
 def __init__(self,oid):self.data={'order_id':oid};self.state=Checkout.receipt.state
 async def get_data(self):return self.data.copy()
 async def clear(self):self.data={};self.state=None
class TextTests(unittest.TestCase):
 def test_entities_and_astral_characters(self):
  text='<b>'+('&lt;X&gt; &amp; 😀'*1700)+'</b>';chunks=split_html(text)
  self.assertGreater(len(chunks),1);self.assertTrue(all(units(c)<=3500 for c in chunks))
  self.assertEqual(''.join(map(plain,chunks)),plain(text))
 def test_nested_formatting(self):
  text='<b><i><code>'+('аб😀&amp;'*2200)+'</code></i></b>'
  self.assertEqual(''.join(map(plain,split_html(text))),plain(text))
 def test_one_giant_line(self):
  chunks=split_html('я'*24000);self.assertEqual(''.join(chunks),'я'*24000)
  self.assertTrue(all(units(c)<=3500 for c in chunks))
 def test_exact_budget(self):self.assertEqual(split_html('x'*3500),['x'*3500])
 def test_empty(self):self.assertEqual(split_html(''),[])
 def test_unescaped_html_rejected(self):
  with self.assertRaises(ValueError):split_html('<b>unclosed')
 def test_manager_splits_before_last_buttons(self):
  bot=NS(send_message=AsyncMock());asyncio.run(send_html(bot,1,'<b>'+('x'*13000)+'</b>',reply_markup='buttons'))
  calls=bot.send_message.call_args_list;self.assertEqual(''.join(plain(c.args[1]) for c in calls),'x'*13000)
  self.assertTrue(all(c.kwargs['reply_markup'] is None for c in calls[:-1]));self.assertEqual(calls[-1].kwargs['reply_markup'],'buttons')
 def test_summary_giant_name(self):
  m=NS(answer=AsyncMock());asyncio.run(answer_html(m,'<i>'+('&amp;'*4000)+'</i>',reply_markup='confirm'))
  self.assertEqual(''.join(plain(c.args[0]) for c in m.answer.call_args_list),'&'*4000)
 def test_keyboard_preserves_page(self):
  from bot import keyboards as kb
  item=NS(product=NS(name='<X>'),product_id=1,qty=2)
  buttons=[b for row in kb.cart([item]*8,page=3,pages=5).inline_keyboard for b in row]
  self.assertLessEqual(len(buttons),50);self.assertTrue(any(b.callback_data=='cartqty:1:3:3' for b in buttons))
 def test_escaped_cart_render(self):
  text=cart.render([CartLine(1,2,Product(1,1,'<X> & 😀',Decimal(10),stock=5))])
  self.assertIn('&lt;X&gt; &amp;',text);self.assertIn('20,00',text)
class SQLTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  async with engine.begin() as c:await c.run_sync(Base.metadata.create_all)
  prime_cache(ShopSettings.from_env());self.cm=open_repo();self.repo=await self.cm.__aenter__()
  self.user=await self.repo.create_user(tg_id=10000+hash(self._testMethodName)%10000000,username='qa',first_name='<QA &>',referrer_id=None)
  self.order=await self.repo.create_order(Order(0,self.user.id,payment_method='card',total=Decimal(10)),[OrderLine('Товар',Decimal(10),1)])
 async def asyncTearDown(self):await self.cm.__aexit__(None,None,None);await engine.dispose()
 def message(self,kind='photo'):
  return NS(photo=[NS(file_id='photo-id')] if kind=='photo' else None,
    document=NS(file_id='document-id',file_name='<receipt>.pdf') if kind=='document' else None,
    caption='<proof &>',message_id=self.order.id+100,bot=NS(send_photo=AsyncMock(),send_document=AsyncMock()),answer=AsyncMock())
 async def test_photo_saved_in_chat_and_order(self):
  msg=self.message();state=State(self.order.id);await checkout.receive_receipt(msg,state,self.repo,self.user)
  order=await self.repo.get_order(self.order.id);history=await self.repo.list_order_messages(order.id)
  self.assertEqual(order.receipt_file_id,'photo-id');self.assertEqual(len(history),1)
  self.assertEqual(history[0].file_kind,'photo');self.assertFalse(history[0].is_read)
  self.assertIsNone(state.state);msg.bot.send_photo.assert_awaited_once()
 async def test_document_saved_and_sent_as_document(self):
  msg=self.message('document');state=State(self.order.id);await checkout.receive_receipt(msg,state,self.repo,self.user)
  history=await self.repo.list_order_messages(self.order.id)
  self.assertEqual(history[0].file_kind,'document');self.assertEqual(history[0].file_name,'<receipt>.pdf')
  msg.bot.send_document.assert_awaited_once();msg.bot.send_photo.assert_not_awaited()
 async def test_telegram_failure_preserves_success(self):
  msg=self.message();msg.bot.send_photo.side_effect=RuntimeError('offline');state=State(self.order.id)
  await checkout.receive_receipt(msg,state,self.repo,self.user);self.assertIsNone(state.state)
  self.assertEqual((await self.repo.get_order(self.order.id)).receipt_file_id,'photo-id')
  self.assertIn('збережено',msg.answer.call_args.args[0])
 async def test_missing_admin_chat(self):
  from dataclasses import replace
  prime_cache(replace(ShopSettings.from_env(),admin_chat_id=0));msg=self.message();state=State(self.order.id)
  await checkout.receive_receipt(msg,state,self.repo,self.user)
  self.assertEqual(len(await self.repo.list_order_messages(self.order.id)),1);msg.bot.send_photo.assert_not_awaited()
 async def test_database_failure_keeps_fsm_for_retry(self):
  msg=self.message();state=State(self.order.id)
  with patch.object(self.repo.s,'commit',AsyncMock(side_effect=RuntimeError('db offline'))):await checkout.receive_receipt(msg,state,self.repo,self.user)
  self.assertEqual(state.state,Checkout.receipt.state);self.assertIsNone((await self.repo.get_order(self.order.id)).receipt_file_id)
  self.assertFalse(await self.repo.list_order_messages(self.order.id));msg.bot.send_photo.assert_not_awaited()
 async def test_wrong_owner_rejected(self):
  msg=self.message();state=State(self.order.id);await checkout.receive_receipt(msg,state,self.repo,NS(id=-10,first_name="QA",username="qa",tg_id=1))
  self.assertIsNone((await self.repo.get_order(self.order.id)).receipt_file_id)
  self.assertEqual(state.state,Checkout.receipt.state);msg.bot.send_photo.assert_not_awaited()
 async def test_deleted_order_not_acknowledged(self):
  msg=self.message();state=State(-1);await checkout.receive_receipt(msg,state,self.repo,self.user)
  self.assertEqual(state.state,Checkout.receipt.state);self.assertNotIn('збережено',msg.answer.call_args.args[0])
 async def test_repeated_message_no_duplicate_attachment(self):
  for _ in range(2):await self.repo.save_order_receipt(self.order.id,self.user.id,{'file_id':'abc','file_kind':'photo','file_name':'Фото'},tg_message_id=8181,author='QA',text='Квитанція')
  self.assertEqual(len(await self.repo.list_order_messages(self.order.id)),1)
 async def test_cod_receipt_rejected(self):
  await self.repo.update_order(self.order.id,{'payment_method':'cod'});msg=self.message();state=State(self.order.id)
  await checkout.receive_receipt(msg,state,self.repo,self.user);self.assertFalse(await self.repo.list_order_messages(self.order.id))
 async def test_long_product_photo_full_description_accessible(self):
  desc='<desc> & 😀 '+('A & B\n'*3000)+'THE_END'
  product=Product(101,1,'<Model &>',Decimal(10),stock=5,sku='<SKU>',description=desc,photo_file_id='photo')
  repo=NS(get_product=AsyncMock(return_value=product),get_cart=AsyncMock(return_value=[]))
  msg=NS(answer_photo=AsyncMock(),answer=AsyncMock(),edit_text=AsyncMock(),photo=None)
  cb=NS(data='prod:101',message=msg,answer=AsyncMock());await catalog.open_product(cb,repo,self.user)
  caption=msg.answer_photo.call_args.kwargs['caption'];self.assertLessEqual(units(caption),1000);plain(caption)
  markup=msg.answer_photo.call_args.kwargs['reply_markup']
  self.assertTrue(any(b.callback_data=='prodinfo:101:0' for row in markup.inline_keyboard for b in row))
  chunks=split_html(catalog.product_text(product)[1]);fetched=[]
  for index in range(len(chunks)):
   cb.data=f'prodinfo:101:{index}';await catalog.product_details(cb,repo);fetched.append(msg.edit_text.call_args.args[0])
  self.assertEqual(''.join(map(plain,fetched)),plain(catalog.product_text(product)[1]));self.assertIn('THE_END',fetched[-1])
 async def test_manager_large_order_notification(self):
  from shop.services.notifications import notify_new_order
  self.order.items=[OrderLine('<Item &> '+str(i),Decimal(10),1) for i in range(220)];self.order.comment='😀&'*500
  bot=NS(send_message=AsyncMock());self.assertTrue(await notify_new_order(bot,self.repo,self.order,self.user))
  calls=bot.send_message.call_args_list;self.assertGreater(len(calls),1)
  for c in calls:self.assertLessEqual(units(c.args[1]),3500);plain(c.args[1])
  self.assertIn('219',''.join(plain(c.args[1]) for c in calls))
 async def test_expired_receipt_rejected(self):
  from datetime import datetime,timedelta,timezone
  from shop.entities import OrderStatus
  await self.repo.update_order(self.order.id,{'status':OrderStatus.DONE})
  await self.repo.update_order(self.order.id,{'completed_at':datetime.now(timezone.utc)-timedelta(days=8)})
  msg=self.message();state=State(self.order.id)
  await checkout.receive_receipt(msg,state,self.repo,self.user)
  self.assertFalse(await self.repo.list_order_messages(self.order.id));msg.bot.send_photo.assert_not_awaited()
 async def test_long_product_without_photo(self):
  product=Product(500,1,'<Title>',Decimal(10),description='&😀'*12000,stock=2)
  repo=NS(get_product=AsyncMock(return_value=product),get_cart=AsyncMock(return_value=[]))
  msg=NS(edit_text=AsyncMock(),answer=AsyncMock(),photo=None);cb=NS(data='prod:500',message=msg,answer=AsyncMock())
  await catalog.open_product(cb,repo,self.user)
  self.assertLessEqual(units(msg.edit_text.call_args.args[0]),3500)
  self.assertTrue(any(b.callback_data=='prodinfo:500:0' for row in msg.edit_text.call_args.kwargs['reply_markup'].inline_keyboard for b in row))
 async def test_profile_history_escapes_and_splits(self):
  from bot.handlers.profile import my_orders
  self.order.items=[OrderLine('<Item> & '+str(i),Decimal(10),1) for i in range(300)]
  repo=NS(list_orders=AsyncMock(return_value=[self.order]))
  cb=NS(message=NS(answer=AsyncMock()),answer=AsyncMock())
  await my_orders(cb,repo,self.user)
  calls=cb.message.answer.call_args_list
  self.assertGreater(len(calls),1)
  for c in calls:plain(c.args[0]);self.assertLessEqual(units(c.args[0]),3500)
  self.assertIn('<Item> & 299',''.join(plain(c.args[0]) for c in calls))
 async def test_real_dispatcher_large_cart_and_document_receipt(self):
  await self.repo.confirm_age(self.user);cat=await self.repo.create_category({'name':'<Category> &','is_active':True});products=[]
  for i in range(120):
   product=await self.repo.create_product({'name':f'{i:03} <X> & '+('😀&'*40),'category_id':cat.id,'price':Decimal(10),'stock':5,'is_active':True,'sku':str(i)})
   await self.repo.set_cart_qty(self.user.id,product.id,2);products.append(product)
  session=StrictSession();bot=Bot('123456:TEST',session=session,default=DefaultBotProperties(parse_mode='HTML'));dp=build_dispatcher();uid=self.user.tg_id
  await dp.feed_update(bot,message_update(bot,'🛒 Кошик',tg_id=uid))
  lines=await self.repo.get_cart(self.user.id);pages,total=cart.pages_for(lines)
  self.assertGreater(len(pages),1);self.assertEqual(total,Decimal(2400));output=[session.last_text()]
  for page in range(1,len(pages)):
   session.clear();await dp.feed_update(bot,callback_update(bot,f'cartpage:{page}',tg_id=uid));output.append(session.last_text())
  combined='\n'.join(map(plain,output))
  for product in products:self.assertIn(product.name,combined)
  self.assertTrue(all('2400,00' in text.replace(' ', '').replace('\u00a0','') for text in output))
  item=lines[-1];session.clear();await dp.feed_update(bot,callback_update(bot,f'cartqty:{item.product_id}:0:{len(pages)-1}',tg_id=uid))
  self.assertFalse(any(x.product_id==item.product_id for x in await self.repo.get_cart(self.user.id)))
  await dp.feed_update(bot,callback_update(bot,'cartpage:99999',tg_id=uid))
  state=dp.fsm.get_context(bot=bot,chat_id=uid,user_id=uid)
  await state.update_data(order_id=self.order.id);await state.set_state(Checkout.receipt)
  session.clear();await dp.feed_update(bot,message_update(bot,'👤 Профіль',tg_id=uid))
  self.assertIn('Ваш профіль',session.all_text())
  session.clear();await dp.feed_update(bot,message_update(bot,'/ask',tg_id=uid))
  self.assertIsNone(await state.get_state());self.assertIsNotNone(await self.repo.get_support_thread_for_user(self.user.id))
  await dp.feed_update(bot,message_update(bot,'/done',tg_id=uid))
  await state.update_data(order_id=self.order.id);await state.set_state(Checkout.receipt)
  upd=message_update(bot,'',tg_id=uid).model_dump(exclude_none=True);upd['message'].pop('text',None);upd['message'].pop('entities',None)
  upd['message']['document']={'file_id':'pdf-proof','file_unique_id':'proof-unique','file_name':'receipt.pdf','mime_type':'application/pdf'}
  session.clear();await dp.feed_update(bot,Update.model_validate(upd,context={'bot':bot}))
  history=await self.repo.list_order_messages(self.order.id);self.assertEqual(history[-1].file_id,'pdf-proof')
  self.assertIsNone(await state.get_state());self.assertTrue(any(name=='SendDocument' for name,_ in session.calls))
  await dp.storage.close();await bot.session.close()
if __name__=='__main__':unittest.main(verbosity=2)
