"""Cart incident: inactive/orphan rows must remain removable. Real signed HTTP/SQLite."""
import asyncio
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import select, delete
from qa_common import boot, init_data, Report
from qa_paths import qa_db_path
app, Session, fake = boot(qa_db_path('cart_unstick.db'))
from shop import models as m
from shop.repo.sql import SqlRepository
from shop.services import shop_service as svc
r=Report('CART UNSTICK');c=TestClient(app);H=init_data(24001);OTHER=init_data(24002)
async def seed():
 async with Session() as session:
  repo=SqlRepository(session);u=await repo.create_user(24001,None,'QA',None);await repo.confirm_age(u)
  other=await repo.create_user(24002,None,'Other',None);await repo.confirm_age(other)
  good=await repo.create_product({'name':'Available','price':Decimal('19.90'),'stock':50})
  bad=await repo.create_product({'name':'Unavailable','price':Decimal('9.50'),'stock':20})
  await repo.set_cart_qty(u.id,good.id,2);await repo.set_cart_qty(u.id,bad.id,2)
  await repo.set_cart_qty(other.id,bad.id,1);await repo.update_product(bad.id,{'is_active':False})
  return u.id,other.id,good.id,bad.id
uid,otherid,good,bad=asyncio.run(seed())
def cart():return c.get('/api/shop/cart',headers=H).json()
def qty(pid):return next((x['qty'] for x in cart()['lines'] if x['product_id']==pid),0)
r.check(len(cart()['problems'])==1,'inactive product reports checkout blocker')
response=c.post('/api/shop/cart',headers=H,json={'product_id':bad,'delta':-1})
r.check(response.status_code==200 and qty(bad)==1,'minus reduces inactive product instead of silently ignoring it')
c.post('/api/shop/cart',headers=H,json={'product_id':bad,'delta':-1})
r.check(qty(bad)==0,'minus removes last inactive item')
r.check(qty(good)==2 and cart()['problems']==[],'removal preserves available goods and unblocks checkout')
r.check(c.post('/api/shop/checkout/quote',headers=H,json={}).status_code==200,'quote works after removing unavailable line')
# Direct deletion must ignore activity, stock and quantity limits, and be idempotent.
async def reset_bad(q=120):
 async with Session() as session:
  await session.execute(delete(m.CartItem).where(m.CartItem.user_id==uid,m.CartItem.product_id==bad))
  session.add(m.CartItem(user_id=uid,product_id=bad,qty=q));await session.commit()
asyncio.run(reset_bad())
url=f'/api/shop/cart/{bad}'
r.check(c.delete(url).status_code==401,'unsigned line delete rejected')
r.check(c.delete(url,headers=OTHER).status_code==200 and qty(bad)==120,'one user cannot delete another user cart line')
response=c.delete(url,headers=H)
r.check(response.status_code==200 and qty(bad)==0,'direct delete removes whole inactive line with quantity above 99')
r.check(c.delete(url,headers=H).status_code==200,'repeated deletion is safe')
r.check(qty(good)==2,'line delete never clears another product')
async def stockzero():
 async with Session() as session:
  repo=SqlRepository(session);await repo.update_product(bad,{'is_active':True,'stock':0})
asyncio.run(stockzero());asyncio.run(reset_bad(5))
c.post('/api/shop/cart',headers=H,json={'product_id':bad,'delta':-1})
r.check(qty(bad)==0,'minus can clear a zero-stock position')
asyncio.run(reset_bad(5))
r.check(c.delete(url,headers=H).status_code==200 and qty(bad)==0,'direct delete ignores zero stock')
# Historical corrupt/orphan rows (foreign keys disabled only in this isolated SQLite fixture).
async def orphan():
 async with Session() as session:
  await session.execute(delete(m.CartItem).where(m.CartItem.user_id==uid,m.CartItem.product_id==987654))
  session.add(m.CartItem(user_id=uid,product_id=987654,qty=1));await session.commit()
asyncio.run(orphan())
r.check(any(x['product_id']==987654 for x in cart()['lines']),'orphan remains visible with a readable problem')
c.post('/api/shop/cart',headers=H,json={'product_id':987654,'delta':-1})
r.check(qty(987654)==0,'minus removes orphan without product lookup blocking removal')
asyncio.run(orphan())
r.check(c.delete('/api/shop/cart/987654',headers=H).status_code==200 and qty(987654)==0,'direct delete removes orphan')
asyncio.run(reset_bad())
response=c.delete('/api/shop/cart',headers=H)
r.check(response.status_code==200 and response.json()['lines']==[] and response.json()['problems']==[],'clear removes all invalid and valid positions')
r.check(c.delete('/api/shop/cart',headers=H).json()['lines']==[],'clear is idempotent')
c.post('/api/shop/cart',headers=H,json={'product_id':good,'delta':3})
r.check(qty(good)==3,'valid products can be added again after cleanup')
c.post('/api/shop/cart',headers=H,json={'product_id':bad,'delta':1})
r.check(qty(bad)==0,'out-of-stock product cannot be added by cleanup path')
async def inactive():
 async with Session() as session:
  repo=SqlRepository(session);await repo.update_product(bad,{'is_active':False,'stock':20})
asyncio.run(inactive())
c.post('/api/shop/cart',headers=H,json={'product_id':bad,'delta':1})
r.check(qty(bad)==0,'inactive product cannot be re-added')
r.check(c.delete('/api/shop/cart/0',headers=H).status_code==422,'invalid product ID rejected')
c.close();raise SystemExit(bool(r.done()))
