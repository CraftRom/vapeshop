"""Adversarial HTTP tests of cookie sessions, CSRF, uploads and Telegram."""
import asyncio, hashlib, hmac, io, json, time, tempfile, zipfile, struct, zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from PIL import Image
from fastapi.testclient import TestClient
from qa_common import boot, Report, TOKEN
app, Session, fake = boot('/tmp/qa_modern_sec.db')
from shop.config import settings
from shop.repo.sql import SqlRepository
from api.browser_sessions import cookie_name, digest_cookie
from api.routers.telegram import webhook_header_secret
from api.webapp_auth import parse_init_data, InitDataError
from shop.services.product_io import parse_salesdrive_xlsx
from api.request_log import safe_path, safe_referer, client_ip
from starlette.requests import Request
r = Report('MODERN SECURITY')
c = TestClient(app, base_url='https://testserver')
browser = {'X-Dashboard-Request': '1', 'Origin': settings.public_url}
credentials = {'login': 'admin', 'password': 'secret'}
r.check(c.post('/api/auth/browser-login',json=credentials).status_code==403,'login CSRF: simple request rejected')
r.check(c.post('/api/auth/browser-login',json=credentials,headers={**browser,'Origin':'https://attacker.example'}).status_code==403,'login CSRF: foreign origin rejected')
x=c.post('/api/auth/browser-login',json=credentials,headers=browser)
r.check(x.status_code==200 and 'access_token' not in x.json(),'browser login returns profile without access token')
cs=x.headers['set-cookie']
r.check(all(v in cs for v in ['HttpOnly','Secure','SameSite=strict','Path=/']) and 'Domain=' not in cs and cs.startswith('__Host-'),'secure cookie attributes')
raw=c.cookies.get(cookie_name())
async def read(digest):
 async with Session() as s:return await SqlRepository(s).get_dashboard_session(digest)
stored=asyncio.run(read(digest_cookie(raw)))
r.check(stored and stored['id']!=raw and len(stored['id'])==64,'database stores cookie digest only')
r.check(c.get('/api/catalog/products').status_code==200,'cookie authenticates reads')
profile=c.get('/api/auth/session').json()
r.check(profile['csrf_token']==x.json()['csrf_token'],'reload restores profile and CSRF')
r.check('no-store' in x.headers.get('cache-control','') and x.headers.get('x-content-type-options')=='nosniff','private response headers')
url='/api/catalog/categories';body={'name':'Security QA'}
r.check(c.post(url,json=body,headers=browser).status_code==403,'write without CSRF rejected')
r.check(c.post(url,json=body,headers={**browser,'X-CSRF-Token':'bad'}).status_code==403,'wrong CSRF rejected')
protected={**browser,'X-CSRF-Token':profile['csrf_token']}
r.check(c.post(url,json=body,headers={**protected,'Sec-Fetch-Site':'cross-site'}).status_code==403,'cross-site fetch rejected despite valid CSRF')
r.check(c.post(url,json=body,headers=protected).status_code==201,'protected write succeeds')
r.check(c.get('/api/orders',headers={'Authorization':'Bearer bad'}).status_code==401,'invalid bearer cannot fall back to cookie')
r.check(c.post('/api/auth/logout',headers=protected).status_code==204,'server-side logout succeeds')
c.cookies.set(cookie_name(),raw,domain='testserver.local',path='/')
r.check(c.get('/api/orders').status_code==401,'logged-out cookie replay rejected')
x=c.post('/api/auth/browser-login',json=credentials,headers=browser);old=c.cookies.get(cookie_name())
x=c.post('/api/auth/browser-login',json=credentials,headers=browser);fresh=c.cookies.get(cookie_name())
r.check(fresh!=old and asyncio.run(read(digest_cookie(old))) is None,'re-login rotates and deletes previous session')
async def expire(column,delta):
 from shop.models import DashboardSession
 async with Session() as s:
  row=await s.get(DashboardSession,digest_cookie(fresh));setattr(row,column,datetime.now(timezone.utc)-delta);await s.commit()
asyncio.run(expire('last_seen_at',timedelta(minutes=61)))
r.check(c.get('/api/orders').status_code==401,'idle timeout enforced')
x=c.post('/api/auth/browser-login',json=credentials,headers=browser);fresh=c.cookies.get(cookie_name());asyncio.run(expire('expires_at',timedelta(seconds=1)))
r.check(c.get('/api/orders').status_code==401,'absolute expiry enforced')
c.cookies.clear();a=c.post('/api/auth/login',json=credentials).json();A={'Authorization':'Bearer '+a['access_token']}
op=c.post('/api/operators',json={'login':'security-op','name':'QA','password':'StrongQa!2026'},headers=A).json()
password={'login':'security-op','password':'StrongQa!2026'}
bearer=c.post('/api/auth/login',json=password).json()['access_token']
c.post('/api/auth/browser-login',json=password,headers=browser)
r.check(c.get('/api/operators').status_code==403,'manager cookie denied owner routes')
r.check(c.put('/api/operators/'+str(op['id']),json={'password':'NewStrongQa!2026'},headers=A).status_code==200,'password update succeeds')
r.check(c.get('/api/orders').status_code==401,'password change revokes old operator cookie')
r.check(c.get('/api/orders',headers={'Authorization':'Bearer '+bearer}).status_code==401,'password change revokes old operator JWT')
r.check(c.post('/api/auth/login',json={'login':'security-op','password':'NewStrongQa!2026'}).status_code==200,'new password login succeeds')
import jwt
payload=jwt.decode(a['access_token'],settings.jwt_secret,algorithms=['HS256'],audience='shop-api',issuer='shop-dashboard')
for key,value in [('oid','bad'),('oid',True),('role','unknown'),('sub','attacker'),('aud','other')]:
 signed=jwt.encode({**payload,key:value},settings.jwt_secret,algorithm='HS256')
 r.check(c.get('/api/orders',headers={'Authorization':'Bearer '+signed}).status_code==401,f'malformed JWT {key}={value!r} rejected')
c.cookies.clear()
r.check(c.get('/api/health',headers={'Host':'attacker.example'}).status_code==400,'untrusted Host rejected')
r.check(c.post('/api/auth/login',content=b'x'*600000,headers={'Content-Type':'application/json'}).status_code==413,'declared JSON body limit')
def chunks():
 for _ in range(20):yield b'x'*32768
r.check(c.post('/api/auth/login',content=chunks(),headers={'Content-Type':'application/json'}).status_code==413,'chunked request limit')
r.check(c.post('/api/media',files={'file':('x.jpg',b'x'*1000)}).status_code==401,'anonymous upload rejected before parsing')
r.check(c.post('/api/media',files={'file':('x.jpg',b'x'*1000)},headers={'Authorization':'Bearer bad'}).status_code==401,'invalid upload token rejected before parsing')
import api.routers.media as media
with tempfile.TemporaryDirectory() as tmp:
 media._media_dir=lambda:Path(tmp)
 r.check(c.post('/api/media',files={'file':('bad.jpg',b'\xff\xd8\xff'+b'<?php code ?>'*30)},headers=A).status_code==415,'fake magic-byte image rejected')
 image=Image.new('RGB',(12,12),'green');exif=Image.Exif();exif[270]='private EXIF';out=io.BytesIO();image.save(out,format='JPEG',exif=exif)
 raw_image=out.getvalue()+b'<script>alert(1)</script>'
 x=c.post('/api/media',files={'file':('../../secret.html',raw_image)},headers=A)
 r.check(x.status_code==201,'valid image upload succeeds')
 dest=Path(tmp)/x.json()['name'];encoded=dest.read_bytes()
 r.check(b'<script>' not in encoded and b'private EXIF' not in encoded,'metadata and appended payload stripped')
 r.check(dest.parent==Path(tmp) and dest.suffix=='.jpg','filename traversal and active extension prevented')
 y=c.post('/api/media',files={'file':('../../secret.html',raw_image)},headers=A)
 r.check(y.json()['reused'] is True and len(list(Path(tmp).iterdir()))==1,'canonical image deduplicated')
 gif=io.BytesIO();Image.new('RGBA',(8,8),'red').save(gif,format='GIF',save_all=True,append_images=[Image.new('RGBA',(8,8),'blue')],duration=100,loop=0)
 z=c.post('/api/media',files={'file':('animation.gif',gif.getvalue())},headers=A)
 r.check(z.status_code==201 and Image.open(Path(tmp)/z.json()['name']).n_frames==2,'safe animation preserved')
 head=struct.pack('>IIBBBBB',100000,100000,8,2,0,0,0)
 bomb=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',len(head))+b'IHDR'+head+struct.pack('>I',zlib.crc32(b'IHDR'+head))+b'\x00\x00\x00\x00IEND\xaeB`\x82'
 r.check(c.post('/api/media',files={'file':('bomb.png',bomb)},headers=A).status_code==415,'image decompression bomb rejected')
 (Path(tmp)/'outside.png').symlink_to('/etc/hosts')
 r.check('outside.png' not in [f['name'] for f in c.get('/api/media',headers=A).json()['files']],'symlink hidden from media library')
def signed(fields):
 check='\n'.join(f'{k}={fields[k]}' for k in sorted(fields));secret=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
 return urlencode({**fields,'hash':hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()})
valid={'auth_date':str(int(time.time())),'user':json.dumps({'id':123,'first_name':'QA'})}
for label,fields in [('missing auth_date',{'user':valid['user']}),('negative ID',{**valid,'user':json.dumps({'id':-1})}),('boolean ID',{**valid,'user':json.dumps({'id':True})}),('array user',{**valid,'user':'[]'}),('object name',{**valid,'user':json.dumps({'id':1,'first_name':{}})}),('future session',{**valid,'auth_date':str(int(time.time())+500)})]:
 r.check(c.get('/api/shop/config',headers={'X-Telegram-Init-Data':signed(fields)}).status_code==401,'Telegram '+label+' rejected')
r.check(c.get('/api/shop/config',headers={'X-Telegram-Init-Data':signed(valid)}).status_code==200,'valid Telegram session works')
try:parse_init_data(signed(valid)+'&foo=1&foo=2',TOKEN);duplicate=False
except InitDataError:duplicate=True
r.check(duplicate,'all duplicate initData fields rejected')
r.check(c.post('/api/telegram/hook/777001',json={}).status_code==404,'missing webhook header rejected')
r.check(c.post('/api/telegram/hook/777001',json={},headers={'X-Telegram-Bot-Api-Secret-Token':hashlib.sha256(b'hook:header').hexdigest()}).status_code==404,'path cannot reveal header secret')
r.check(c.post('/api/telegram/hook/999999',json={},headers={'X-Telegram-Bot-Api-Secret-Token':webhook_header_secret()}).status_code==409,'valid webhook header reaches bot validation')
r.check('hook' not in safe_path('/api/telegram/hook/777001'),'webhook path redacted')
r.check('sensitive' not in safe_path('/api/integrations/salesdrive/webhook/sensitive'),'CRM webhook path redacted')
r.check('password' not in safe_referer('https://host/api/auth?password=x#secret'),'referrer query stripped')
for peer,expected in [('198.51.100.2','198.51.100.2'),('127.0.0.1','1.2.3.4')]:
 req=Request({'type':'http','headers':[(b'x-real-ip',b'1.2.3.4')],'client':(peer,123),'path':'/'})
 r.check(client_ip(req)==expected,'proxy header trusted only for trusted peer '+peer)
b=io.BytesIO()
with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('xl/worksheets/sheet1.xml',b'x'*(65*1024*1024))
try:parse_salesdrive_xlsx(b.getvalue());blocked=False
except ValueError:blocked=True
r.check(blocked,'XLSX expansion bomb rejected before XML parsing')
r.check(c.post('/api/telegram/hook/777001',json={},headers={'X-Telegram-Bot-Api-Secret-Token':webhook_header_secret()}).status_code==400,'malformed trusted Telegram update rejected')
r.check('input' not in c.post('/api/auth/login',json={'login':'admin','password':'s'*1100}).json()['detail'][0], 'validation error does not echo password')
from api.routers.landing_pages import _html_response
rendered=_html_response('<script>console.log(1)</script>',{})
policy=rendered.headers['content-security-policy'].split('script-src',1)[1].split(';',1)[0]
r.check("'sha256-" in policy and "unsafe-inline" not in policy,'promo inline scripts allowlist by SHA256')
raise SystemExit(1 if r.done() else 0)
