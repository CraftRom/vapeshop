"""Current provider wire contracts and outage behavior. Every external HTTP call is intercepted."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import os
from unittest.mock import AsyncMock, patch
import httpx
from cryptography.fernet import Fernet
os.environ['DATA_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
from qa_common import Report, boot
from qa_paths import qa_db_path
app, Session, _ = boot(qa_db_path('external_contracts.db'))
from shop.http_utils import retry_after_seconds
from shop.services import novaposhta as np, salesdrive as sd, cloudflare as cf
from shop.services.shop_settings import ShopSettings, prime_cache
from shop.repo.sql import SqlRepository
from shop import telegram
from shop.secret_crypto import decrypt_secret

r=Report('External API contracts')
RealClient=httpx.AsyncClient
SHOP=replace(ShopSettings.from_env(),salesdrive_enabled=True,salesdrive_domain='qa',salesdrive_api_key='sd-secret-key',salesdrive_form_key='form-secret',salesdrive_telegram_form_id=7,novaposhta_api_key='np-secret-key')

def client_factory(handler):
    transport=httpx.MockTransport(handler)
    return lambda **kwargs: RealClient(transport=transport,**kwargs)

async def nova_tests():
    for body in [[], ['invalid'], 'bad', {'success':True,'data':{}}, {'success':'true','data':[]}]:
        np.reset_cache()
        with patch.object(np,'_post',AsyncMock(return_value=body)):
            try: await np._call('np-key','Address','getWarehouses',{});ok=False
            except np.NovaPoshtaError:ok=True
        r.check(ok,f'Nova malformed envelope rejected: {str(body)[:50]}')
    calls=[]
    def redirected(request):
        calls.append(request)
        return httpx.Response(303,headers={'Location':'/v2.0/json/redirected'}) if len(calls)==1 else httpx.Response(200,json={'success':True,'data':[]})
    with patch('shop.services.novaposhta.httpx.AsyncClient',side_effect=client_factory(redirected)):
        await np._post({'apiKey':'hidden','modelName':'Address'})
    r.check([x.method for x in calls]==['POST','POST'] and json.loads(calls[1].content)['apiKey']=='hidden','Nova same-origin redirect preserves POST body')
    calls.clear()
    def foreign(request):calls.append(request);return httpx.Response(307,headers={'Location':'https://evil.example/steal'})
    with patch('shop.services.novaposhta.httpx.AsyncClient',side_effect=client_factory(foreign)):
        try:await np._post({'apiKey':'hidden'});ok=False
        except np.NovaPoshtaError:ok=True
    r.check(ok and len(calls)==1,'Nova never forwards API key to a redirected host')
    with patch('shop.services.novaposhta.httpx.AsyncClient',side_effect=client_factory(lambda request:httpx.Response(200,text='<html>outage</html>'))):
        try:await np._post({'apiKey':'hidden'});ok=False
        except np.NovaPoshtaError:ok=True
    r.check(ok,'Nova invalid JSON becomes a provider error')
    np.reset_cache();calls.clear()
    def limited(request):
        calls.append(request)
        return httpx.Response(429,headers={'Retry-After':'120'}) if len(calls)==1 else httpx.Response(200,json={'success':True,'data':[]})
    with patch('shop.services.novaposhta.httpx.AsyncClient',side_effect=client_factory(limited)):
        for _ in range(2):
            try:await np._call('limited-key','Address','getWarehouses',{})
            except np.NovaPoshtaError:pass
        r.check(len(calls)==1,'Nova respects full Retry-After and does not hammer the provider')
        await np._call('different-key','Address','getWarehouses',{})
    r.check(len(calls)==2,'Nova outage cooldown is scoped to the API key')
    np.reset_cache()
    row={'success':True,'data':[{'Addresses':[{'Ref':'R','DeliveryCity':'C','MainDescription':'Київ','Warehouses':'2'}]}]}
    mocked=AsyncMock(return_value=row)
    with patch.object(np,'_post',mocked):
        await np.search_settlements('first','Київ');await np.search_settlements('second','Київ');await np.search_settlements('first','Київ')
    r.check(mocked.await_count==2,'Nova cached dictionaries are isolated by credential fingerprint')
    r.check(all('first' not in key and 'second' not in key for key in np._cache),'Nova cache keys do not retain raw credentials')

async def salesdrive_tests():
    calls=[]
    async def slow(request):
        calls.append(request);await asyncio.sleep(.02)
        return httpx.Response(200,json={'data':[{'id':123}]})
    with patch('shop.services.salesdrive.httpx.AsyncClient',side_effect=client_factory(slow)):
        results=await asyncio.gather(*(sd._get_json(SHOP,'/api/order/list/',params={'limit':1}) for _ in range(20)))
    r.check(len(calls)==1 and len(results)==20,'20 identical concurrent SalesDrive reads use one provider request')
    r.check(calls[0].headers['Form-Api-Key']=='sd-secret-key' and calls[0].headers['X-Api-Key']=='sd-secret-key','SalesDrive preserves documented and legacy API-key headers')
    calls.clear()
    with patch('shop.services.salesdrive.httpx.AsyncClient',side_effect=client_factory(slow)):
        first=asyncio.create_task(sd._get_json(SHOP,'/api/order/list/',params={'limit':2}))
        second=asyncio.create_task(sd._get_json(SHOP,'/api/order/list/',params={'limit':2}))
        await asyncio.sleep(.005);first.cancel()
        try:await first
        except asyncio.CancelledError:pass
        result=await second
    r.check(len(calls)==1 and result['data'][0]['id']==123,'disconnected SalesDrive waiter does not cancel another reader')
    calls.clear()
    future=format_datetime(datetime.now(timezone.utc)+timedelta(seconds=120),usegmt=True)
    def limited(request):calls.append(request);return httpx.Response(429,headers={'Retry-After':future},json={'message':'quota'})
    with patch('shop.services.salesdrive.httpx.AsyncClient',side_effect=client_factory(limited)):
        delays=[]
        for _ in range(2):
            try:await sd._get_json(SHOP,'/api/order/list/')
            except sd.SalesDriveError as exc:delays.append(exc.retry_after)
    r.check(len(calls)==1 and all(delay>118 for delay in delays),'SalesDrive HTTP-date Retry-After blocks early repeated reads')
    sd._read_cooldowns.get(asyncio.get_running_loop(),{}).clear()
    snapshot=sd._snapshot({'id':1,'products':[{'name':'A','upsell':0,'preSale':1,'stockBalance':{'1':9},'priceTypes':[{'price':30}]}]},body={})
    p=snapshot['products'][0]
    r.check(p['upsell']==0 and p['stockBalance']=={'1':9} and p['priceTypes']==[{'price':30}],'SalesDrive October product fields work without removed product metadata; explicit upsell wins')
    calls.clear()
    def server_failure(request):calls.append(request);return httpx.Response(503,json={'error':'outage'})
    with patch('shop.services.salesdrive.httpx.AsyncClient',side_effect=client_factory(server_failure)):
        try:await sd._send(SHOP,'/api/order/update/',{'id':123})
        except sd.SalesDriveError:pass
    r.check(len(calls)==1,'SalesDrive mutations never receive an automatic HTTP replay')

async def cloudflare_tests():
    account='a'*32;paths=[]
    def active(request):paths.append(request.url.path);return httpx.Response(200,json={'success':True,'result':{'status':'active'}})
    with patch('shop.services.cloudflare.httpx.AsyncClient',side_effect=client_factory(active)):
        await cf.verify_token('user-token');await cf.verify_token('account-token',account)
    r.check(paths==['/client/v4/user/tokens/verify',f'/client/v4/accounts/{account}/tokens/verify'],'Cloudflare user and account tokens use their documented verification routes')
    for body in [[],{}, {'success':True,'result':{}},{'success':True,'result':{'status':'expired'}}]:
        with patch('shop.services.cloudflare.httpx.AsyncClient',side_effect=client_factory(lambda request,b=body:httpx.Response(200,json=b))):
            try:await cf.verify_token('invalid-token');ok=False
            except cf.CloudflareError:ok=True
        r.check(ok,f'Cloudflare rejects invalid verification response: {body}')
    calls=[]
    def limited(request):calls.append(request);return httpx.Response(429,headers={'Retry-After':'120'},json={'success':False,'errors':[]})
    with patch('shop.services.cloudflare.httpx.AsyncClient',side_effect=client_factory(limited)):
        delays=[]
        for _ in range(2):
            try:await cf.request('limited-token','GET','/zones')
            except cf.CloudflareError as exc:delays.append(exc.retry_after)
    r.check(len(calls)==1 and all(delay>119 for delay in delays),'Cloudflare full Retry-After prevents premature retries')
    calls.clear()
    def gateway(request):calls.append(request);return httpx.Response(503,json={'success':False})
    with patch('shop.services.cloudflare.httpx.AsyncClient',side_effect=client_factory(gateway)):
        try:await cf.request('write-token','POST','/zones/id/dns_records',body={'type':'A'})
        except cf.CloudflareError:pass
    r.check(len(calls)==1,'Cloudflare DNS writes are never automatically repeated')
    calls.clear()
    def transient(request):calls.append(request);return httpx.Response(503,json={'success':False}) if len(calls)==1 else httpx.Response(200,json={'success':True,'result':[]})
    with patch('shop.services.cloudflare.httpx.AsyncClient',side_effect=client_factory(transient)):
        result=await cf.request('read-token','GET','/zones')
    r.check(len(calls)==2 and result['success'],'Cloudflare safe reads recover after one gateway failure')

async def telegram_tests():
    for failure in [httpx.ReadTimeout('token-bearing-url'),httpx.WriteError('token-bearing-url')]:
        sender=AsyncMock();sender.post.side_effect=failure
        with patch('shop.telegram.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value=sender
            result=await telegram._call('sendMessage',{'chat_id':1,'text':'hello'})
        r.check(sender.post.await_count==1 and not result[0] and 'token-bearing-url' not in result[1],'Telegram ambiguous writes are not duplicated and do not leak URL')
    sender=AsyncMock();sender.post.return_value=httpx.Response(429,json={'ok':False,'error_code':429,'parameters':{'retry_after':120}})
    with patch('shop.telegram.httpx.AsyncClient') as factory,patch('shop.telegram.asyncio.sleep',new_callable=AsyncMock) as sleep:
        factory.return_value.__aenter__.return_value=sender
        result=await telegram._call('sendMessage',{'chat_id':1,'text':'hello'})
    r.check(sender.post.await_count==1 and sleep.await_count==0 and '120' in result[1],'Telegram does not clip a long flood wait or block checkout')
    sender=AsyncMock();sender.post.return_value=httpx.Response(200,json={'ok':True})
    result=await telegram.send_broadcast_once(1,'plain text',text_format='plain',client=sender)
    r.check(result.status=='sent' and sender.post.await_count==1,'Telegram broadcast accepts a shared connection pool')

async def api_tests():
    async with RealClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
        auth=(await client.post('/api/auth/login',json={'login':'admin','password':'secret'})).json()
        headers={'Authorization':'Bearer '+auth['access_token']}
        r.check((await client.get('/api/integrations/health')).status_code==401,'integration diagnostics requires authorization')
        token='cloudflare-sensitive-token-123456';account='b'*32
        def active(request):return httpx.Response(200,json={'success':True,'result':{'status':'active'}})
        with patch('shop.services.cloudflare.httpx.AsyncClient',side_effect=client_factory(active)):
            response=await client.put('/api/landing-pages/cloudflare/config',headers=headers,json={'api_token':token,'account_id':account})
        r.check(response.status_code==200 and response.json()['accountId']==account and token not in response.text,'Cloudflare account config can be saved without exposing token',response.text)
        async with Session() as session:
            raw=await SqlRepository(session).get_settings_map()
            r.check(raw['promo_cloudflare_api_token']!=token and decrypt_secret(raw['promo_cloudflare_api_token'])==token,'Cloudflare token remains encrypted at rest')
        response=await client.get('/api/landing-pages/cloudflare/config',headers=headers)
        r.check(response.json()['accountId']==account and token not in response.text,'Cloudflare status returns account ID and no credential')
        prime_cache(SHOP)
        with patch('shop.services.integration_health.httpx.AsyncClient',side_effect=AssertionError('network must not run')):
            response=await client.get('/api/integrations/health',headers=headers)
        r.check(response.status_code==200 and response.json()['readOnly'] and response.json()['verified']==0,'static integration check never contacts a provider')
        calls=[]
        def providers(request):
            calls.append(request)
            if request.url.host=='api.telegram.org':return httpx.Response(200,json={'ok':True,'result':{'id':1}})
            if request.url.host=='api.novaposhta.ua':return httpx.Response(200,json={'success':True,'data':[]})
            if request.url.host.endswith('.salesdrive.me'):return httpx.Response(200,json={'data':[{'id':1,'name':'Новий'}]})
            return active(request)
        with patch('shop.services.integration_health.httpx.AsyncClient',side_effect=client_factory(providers)):
            response=await client.get('/api/integrations/health?live=true',headers=headers)
        data=response.json()
        r.check(response.status_code==200 and data['verified']==4 and data['errors']==0,'live diagnostics probes all four configured providers with read methods',response.text)
        r.check(all('sendMessage' not in str(request.url) and 'sendPhoto' not in str(request.url) and 'dns_records' not in str(request.url) for request in calls),'diagnostics never sends messages or modifies DNS')
        r.check(all(secret not in response.text for secret in [token,SHOP.salesdrive_api_key,SHOP.novaposhta_api_key]),'diagnostics report contains no provider keys')
        prime_cache(ShopSettings.from_env())
    await Session.kw['bind'].dispose()

async def run():
    now=datetime(2026,11,2,12,tzinfo=timezone.utc)
    r.check(retry_after_seconds('120')==120 and retry_after_seconds(format_datetime(now+timedelta(seconds=90),usegmt=True),now=now)==90,'Retry-After supports seconds and HTTP dates')
    r.check(retry_after_seconds('nan',default=7)==7 and retry_after_seconds('-1',default=7)==7,'invalid Retry-After never creates NaN or negative sleeps')
    await nova_tests();await salesdrive_tests();await cloudflare_tests();await telegram_tests();await api_tests()
asyncio.run(run())
raise SystemExit(bool(r.done()))
