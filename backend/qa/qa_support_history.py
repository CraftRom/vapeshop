"""Staff support cursor pages and exact read ACK: real authenticated HTTP/SQLite."""
import asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select, delete
from qa_common import boot, Report, init_data
from qa_paths import qa_db_path
app, Session, fake = boot(qa_db_path('support_history.db'))
from shop import models as m
from shop.repo.sql import SqlRepository, _pack_archive, _archive_json
from api.auth import create_token
from shop.entities import OperatorRole
r=Report('SUPPORT HISTORY');c=TestClient(app)
A={'Authorization':'Bearer '+create_token('admin',OperatorRole.SYSADMIN)}
async def seed():
 async with Session() as s:
  repo=SqlRepository(s);u=await repo.create_user(28001,None,'History',None)
  v=await repo.create_user(28002,None,'Other',None)
  first=await repo.ensure_support_thread(u.id);second=await repo.ensure_support_thread(v.id)
  rows=[m.SupportMessage(thread_id=first.id,user_id=u.id,direction='in' if i%2 else 'out',author='QA',text=f'Message {i}',is_read=False) for i in range(1,652)]
  foreign=m.SupportMessage(thread_id=second.id,user_id=v.id,direction='in',author='Other',text='Foreign',is_read=False)
  s.add_all([*rows,foreign]);await s.commit()
  return first.id,second.id,[row.id for row in rows],foreign.id,u.id
tid,other,ids,foreign,uid=asyncio.run(seed());url=f'/api/support/{tid}/messages'
get=lambda suffix='':c.get(url+suffix,headers=A)
def ack(values):return c.post(url+'/read',headers=A,json={'message_ids':values})
def unread():return c.get('/api/support/unread/count',headers=A).json()['count']
r.check(c.get(url).status_code==401,'unsigned history rejected')
r.check(c.post(url+'/read',json={'message_ids':[ids[0]]}).status_code==401,'unsigned ACK rejected')
r.check(c.get(url,headers=init_data(28001)).status_code==401,'customer initData cannot read staff history')
initial=unread();latest=get('?limit=200').json()
r.check(len(latest)==200 and latest[-1]['id']==ids[-1] and latest[0]['id']==ids[-200],'latest 200 opens at end of long history')
r.check(unread()==initial,'GET does not mark unseen history read')
r.check(len(get().json())==300,'legacy client keeps latest-300 response')
allids=[x['id'] for x in latest]
while True:
 page=get(f'?before_id={allids[0]}&limit=200').json()
 if not page:break
 allids=[x['id'] for x in page]+allids
r.check(allids==ids and len(set(allids))==651,'all 651 replies can be loaded without holes or duplicates')
delta=[];cursor=0
while True:
 page=get(f'?after_id={cursor}&limit=200').json()
 if not page:break
 delta += [x['id'] for x in page];cursor=delta[-1]
r.check(delta==ids,'ascending delta pages drain a large backlog')
for query in ('?before_id=2&after_id=0','?limit=201','?limit=0','?before_id=0','?after_id=-1','?after_id=999999999999999999999'):
 r.check(get(query).status_code==422,'invalid cursor/limit rejected '+query)
r.check(c.get('/api/support/999999/messages?limit=200',headers=A).status_code==404,'missing thread history is explicit')
r.check(c.post('/api/support/999999/messages/read',headers=A,json={'message_ids':[]}).status_code==404,'missing thread ACK rejected')
r.check(c.post('/api/support/999999999999999999999/messages/read',headers=A,json={'message_ids':[]}).status_code==422,'oversized thread ID rejected before SQL')
r.check(ack([]).json()=={'marked':0} and unread()==initial,'empty ACK marks nothing')
r.check(ack([ids[0],ids[0],ids[1],foreign,999999]).json()=={'marked':1},'ACK deduplicates and scopes to incoming messages of this thread')
r.check(unread()==initial-1,'only one incoming message becomes read')
r.check(ack([ids[0]]).json()=={'marked':0},'replayed ACK is idempotent')
for values in ([0],[-1],[2147483648],[999999999999999999999],list(range(1,502))):
 r.check(ack(values).status_code==422,'invalid ACK payload rejected')
r.check(c.post(url+'/read',headers=A).status_code==422,'missing body cannot mark whole session')
page=get('?limit=20&mark_read=true').json()
r.check(all(x['is_read'] for x in page if x['direction']=='in'),'legacy mark_read response acknowledges returned incoming rows')
r.check(unread()==initial-11,'legacy mark_read marks only its returned page, not older unseen history')

# Closed sessions transparently merge compressed old history with hot rows.
async def cold():
 async with Session() as s:
  repo=SqlRepository(s)
  archived=[]
  for row in (await s.scalars(select(m.SupportMessage).where(m.SupportMessage.thread_id==tid,m.SupportMessage.id<=ids[399]))).all():
   archived.append({'id':row.id,'thread_id':tid,'user_id':uid,'direction':row.direction,'author':row.author,'text':row.text,'is_read':True,'created_at':row.created_at.isoformat(),'file_kind':None,'file_name':None,'file_id':None})
  archived[0]['is_read']=False # imported legacy archive edge case
  s.add(m.MessageArchive(kind='support',entity_id=tid,payload=_pack_archive(archived),raw_bytes=len(_archive_json(archived)),message_count=len(archived),min_message_id=archived[0]['id'],max_message_id=archived[-1]['id']))
  await s.execute(delete(m.SupportMessage).where(m.SupportMessage.thread_id==tid,m.SupportMessage.id<=ids[399]))
  thread=await s.get(m.SupportThread,tid);thread.status='closed';await s.commit()
asyncio.run(cold())
loaded=[];cursor=None
while True:
 page=get('?limit=200'+(f'&before_id={cursor}' if cursor else '')).json()
 if not page:break
 loaded=[x['id'] for x in page]+loaded;cursor=loaded[0]
r.check(loaded==ids,'closed cold+hot history remains complete')
r.check(ack([ids[0]]).json()=={'marked':1},'exact ACK updates an imported archived incoming message')
r.check(get(f'?before_id={ids[1]}&limit=200').json()[0]['is_read'] is True,'archived ACK survives next read')
r.check(c.get(f'/api/support/{other}/messages',headers=A).json()[0]['is_read'] is False,'another thread stays unread')
c.close();raise SystemExit(bool(r.done()))
