"""Real HTTP + SQLite: ownership, shared support history, pagination and replay."""
from qa_paths import qa_db_path
from qa_common import boot, init_data, Report
app, Session, fake = boot(qa_db_path('miniapp_support.db'))
import asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from shop.repo.sql import SqlRepository
from shop import models as m
from shop.services import support_chat
r=Report('MINIAPP SUPPORT')
c=TestClient(app); H=init_data(17001); OTHER=init_data(17002)
base='/api/shop/support/threads'
r.check(c.get(base).status_code==401,'unsigned list rejected')
r.check(c.post(base,headers={'X-Telegram-Init-Data':'forged'}).status_code==401,'forged launch rejected')
r.check(c.get(base,headers=H).json()['items']==[],'opening list creates no thread')
start=c.post(base,headers=H);thread=start.json();tid=thread['id'];url=f'{base}/{tid}'
r.check(start.status_code==201 and thread['status']=='open','explicit start opens general support before any purchase')
r.check(c.post(base,headers=H).json()['id']==tid,'repeat start resumes one active thread')
r.check('user_id' not in thread and 'user' not in thread,'thread DTO excludes internal customer data')
for path,method in [(url,'get'),(url+'/messages','get'),(url+'/close','post'),(url+'/files/1','get')]:
 r.check(getattr(c,method)(path,headers=OTHER).status_code==404,'foreign '+path.split('/')[-1]+' is inaccessible')
r.check(c.post(url+'/messages',headers=OTHER,json={'text':'intrusion','request_id':'foreign_request_17002'}).status_code==404,'foreign send rejected')
for body in ({'text':'   ','request_id':'valid_request_17001'}, {'text':'x'*2001,'request_id':'valid_request_17001'}, {'text':'ok','request_id':'short'}):
 r.check(c.post(url+'/messages',headers=H,json=body).status_code==422,'invalid message/key rejected')
payload={'text':'Текст <b> & 😀','request_id':'same_request_17001'}
first=c.post(url+'/messages',headers=H,json=payload);sent=first.json();notifications=len(fake.sent)
r.check(first.status_code==201 and sent['text']==payload['text'],'incoming text stored completely')
r.check('file_id' not in sent and 'is_automatic' not in sent and 'user_id' not in sent,'client DTO excludes Telegram and staff metadata')
replay=c.post(url+'/messages',headers=H,json=payload)
r.check(replay.status_code==201 and replay.json()['id']==sent['id'] and len(fake.sent)==notifications,'replay returns same message without duplicate staff notification')
r.check(c.post(url+'/messages',headers=H,json={**payload,'text':'different'}).status_code==409,'same request key cannot change text')
admin=c.post('/api/auth/login',json={'login':'admin','password':'secret'}).json()['access_token'];A={'Authorization':'Bearer '+admin}
r.check(c.get(f'/api/support/{tid}/messages',headers=A).json()[0]['id']==sent['id'],'staff sees Mini App message in existing support inbox')
answer=c.post(f'/api/support/{tid}/messages',headers=A,json={'text':'Відповідь менеджера'})
r.check(answer.status_code==201,'existing manager endpoint still sends reply')
r.check(c.get(url+'/messages',headers=H).json()['items'][-1]['text']=='Відповідь менеджера','manager reply appears in Mini App history')
async def seed():
 async with Session() as session:
  repo=SqlRepository(session);user=await repo.get_user_by_tg(17001)
  await support_chat.save_incoming(repo,user,'З Telegram /ask')
  rows=[m.SupportMessage(thread_id=tid,user_id=user.id,direction='out',author='QA',text=f'History {i}',is_read=True) for i in range(451)]
  session.add_all(rows);await session.commit()
  return user.id, rows[-1].id
uid,last=asyncio.run(seed())
r.check(any(x['text']=='З Telegram /ask' for x in c.get(url+'/messages?after_id=0',headers=H).json()['items']),'Telegram and Mini App share the same history')
page=c.get(url+'/messages',headers=H).json();allids=[x['id'] for x in page['items']]
r.check(len(allids)==200 and allids[-1]==last,'initial page is latest 200, not oldest 300')
while page['has_more']:
 page=c.get(url+f'/messages?before_id={allids[0]}',headers=H).json();allids=[x['id'] for x in page['items']]+allids
r.check(len(allids)==454 and len(set(allids))==454 and allids==sorted(allids),'all 454 historical messages load once in chronological order')
ids=[];cursor=0
while True:
 page=c.get(url+f'/messages?after_id={cursor}',headers=H).json();items=page['items']
 if not items:break
 ids.extend(x['id'] for x in items);cursor=ids[-1]
 if not page['has_more']:break
r.check(ids==allids,'delta batches catch >200 replies without gaps')
r.check(c.get(url+'/messages?before_id=3&after_id=0',headers=H).status_code==422,'ambiguous cursors rejected')
r.check(c.get(f'/api/support/{tid}/messages',headers=A).json()[-1]['id']==last,'staff latest window includes newest reply beyond 300')
async def concurrent():
 async with AsyncClient(transport=ASGITransport(app=app),base_url='http://testserver') as client:
  return await asyncio.gather(*[client.post(url+'/messages',headers=H,json={'text':'Parallel','request_id':'parallel_request_17001'}) for _ in range(2)])
results=asyncio.run(concurrent())
r.check(all(x.status_code==201 for x in results) and results[0].json()['id']==results[1].json()['id'],'concurrent retry records one message')
from shop.telegram_text import units
original_send=fake.send_message
async def strict_send(cid,text,**kwargs):
 assert units(text)<=3500
 return await original_send(cid,text,**kwargs)
fake.send_message=strict_send
before=len(fake.sent)
long_reply=c.post(f'/api/support/{tid}/messages',headers=A,json={'text':'😀'*2000})
r.check(long_reply.status_code==201 and len(fake.sent)>=before+2,'long emoji reply splits safely for Telegram without truncating history')
before=len(fake.sent)
long_in=c.post(url+'/messages',headers=H,json={'text':'😀'*2000,'request_id':'long_emoji_request_17001'})
r.check(long_in.status_code==201 and len(fake.sent)>=before+2,'long customer notification also respects Telegram limits')
async def automatic():
 async with Session() as session:
  repo=SqlRepository(session);user=await repo.get_user(uid)
  await support_chat.save_automatic_reply(repo,user,tid,'<b>FAQ</b> &amp; info')
asyncio.run(automatic())
r.check(c.get(url+'/messages',headers=H).json()['items'][-1]['text']=='FAQ & info','automatic Telegram HTML becomes safe plain client text')
r.check(c.post(url+'/messages',headers=H,json={**payload,'user_id':999}).status_code==422,'extra identity fields rejected')
r.check(c.get(base+'/9999999999999999999999',headers=H).status_code==422,'oversized path ID rejected before SQL')
closed=c.post(url+'/close',headers=H)
r.check(closed.json()['status']=='closed' and c.post(url+'/close',headers=H).json()['status']=='closed','close is idempotent')
r.check(c.post(url+'/messages',headers=H,json=payload).json()['id']==sent['id'],'committed replay works after closure without reopening')
r.check(c.post(url+'/messages',headers=H,json={'text':'late','request_id':'new_request_after_close'}).status_code==409,'new text cannot append after close')
r.check(c.get(url+'/messages',headers=H).status_code==200,'closed history remains readable')
next_thread=c.post(base,headers=H).json()
r.check(next_thread['id']!=tid,'explicit next question creates a new thread')
r.check(c.get(url,headers=H).json()['status']=='closed','old thread is never reopened')
async def archive():
 from shop.repo.sql import _support_message_to_archive
 from sqlalchemy import delete
 async with Session() as session:
  repo=SqlRepository(session)
  rows=list(await session.scalars(select(m.SupportMessage).where(m.SupportMessage.thread_id==tid).order_by(m.SupportMessage.id).limit(50)))
  rows[0].file_id='qa-file';rows[0].file_kind='photo';rows[0].file_name='proof.jpg'
  await repo._merge_message_archive('support',tid,[_support_message_to_archive(row) for row in rows])
  await session.execute(delete(m.SupportMessage).where(m.SupportMessage.id.in_([row.id for row in rows])));await session.commit()
asyncio.run(archive())
r.check(c.get(url+'/messages?after_id=0',headers=H).json()['items'][0]['id']==sent['id'],'archived messages remain pageable')
from types import SimpleNamespace
from io import BytesIO
async def get_file(fid):return SimpleNamespace(file_path='qa-photo')
async def download_file(path):return BytesIO(b'photo-bytes')
fake.get_file=get_file;fake.download_file=download_file
photo=c.get(url+f'/files/{sent["id"]}',headers=H)
r.check(photo.status_code==410,'archived attachment follows existing file retention policy')
async def hot_file():
 async with Session() as session:
  row=await session.get(m.SupportMessage,last);row.file_id='qa-file';row.file_kind='photo';await session.commit()
asyncio.run(hot_file())
r.check(c.get(url+f'/files/{last}',headers=H).content==b'photo-bytes','owned live attachment beyond first 300 messages can be read')
r.check(c.get(url+f'/files/{sent["id"]}',headers=OTHER).status_code==404,'archived attachment has same ownership protection')
async def seed_closed():
 async with Session() as session:
  session.add_all([m.SupportThread(user_id=uid,status='closed') for _ in range(25)])
  await session.commit()
asyncio.run(seed_closed())
page=c.get(base,headers=H).json();threads=page['items'];page2=c.get(base+f'?before_id={threads[-1]["id"]}',headers=H).json()
r.check(len(threads)==20 and page['has_more'] and len(page2['items'])==7,'thread history paginates without mixing users')
r.check(not set(x['id'] for x in threads)&set(x['id'] for x in page2['items']),'thread pages do not duplicate IDs')
async def block():
 async with Session() as session:
  user=await session.get(m.User,uid);user.is_blocked=True;await session.commit()
asyncio.run(block())
r.check(c.get(base,headers=H).status_code==403,'blocked customer cannot access support API')
c.close()
raise SystemExit(bool(r.done()))
