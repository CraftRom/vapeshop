"""Offline contract matrix for checkout/delivery/CRM/Telegram/Cloudflare.

No provider credentials, database, or live traffic required.
Run: PYTHONPATH=backend python3 backend/qa/qa_api_compat_matrix.py
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import AsyncMock, patch

from shop.entities import OrderStatus
from shop.services import novaposhta as np, shipment, salesdrive, waybill, cloudflare
from api.webapp_auth import parse_init_data, InitDataError

checked = 0


def check(condition: bool, label: str) -> None:
    global checked
    if not condition:
        raise AssertionError(label)
    checked += 1


def order(*, payment='cod', delivery='warehouse', point='Поштомат №26', selected=True):
    return SimpleNamespace(
        id=42, status=OrderStatus.CONFIRMED, payment_method=payment,
        delivery_method=delivery, delivery_city='Рівне', delivery_address=point,
        delivery_city_ref='city-ref' if selected else '',
        delivery_warehouse_ref='warehouse-ref' if selected and delivery == 'warehouse' else '',
        contact_name='Іваненко Марія', contact_surname='Іваненко',
        contact_patronymic='', contact_phone='+380671112233',
        items=[SimpleNamespace(id=1, product_id=12, name='Товар', qty=2, price=Decimal('99.95'))],
        subtotal=Decimal('199.90'), discount=Decimal('0'), bonus_used=Decimal('0'),
        total=Decimal('199.90'), comment='', promo_code='', tracking_number='',
    )


def shop():
    return SimpleNamespace(
        delivery_weight_per_item=0.5, novaposhta_cargo_description='Товари',
        salesdrive_form_key='form', salesdrive_payment_map='{}', salesdrive_shipping_map='{}',
        salesdrive_status_map='{}', salesdrive_site='elfar.pp.ua', public_url='https://elfar.pp.ua',
        currency='грн', novaposhta_connected=True, novaposhta_sender_city='Рівне',
        novaposhta_sender_warehouse_ref='warehouse-sender', novaposhta_sender_phone='0671112233',
    )


def combo_matrix():
    s=shop()
    sender=waybill.Sender('counterparty-sender', 'contact-sender', '380671112233', 'city-sender', 'warehouse-sender')
    # Different entry points (selected and manual), payment and destination combinations.
    for delivery in ('warehouse', 'courier'):
        for payment in ('card', 'cod'):
            for selected in (True, False):
                obj=order(payment=payment, delivery=delivery,
                          point='вул. Соборна, 1' if delivery=='courier' else 'Поштомат №26',
                          selected=selected)
                destination=shipment.destination(obj)
                box=shipment.parcel(obj,s)
                crm=salesdrive.create_payload(obj,s)
                check(destination.to_door == (delivery=='courier'), f'destination route {delivery}')
                check(box.declared_cost == Decimal('199.90'), f'declared amount {delivery}/{payment}')
                check(box.cod_amount == (Decimal('199.90') if payment=='cod' else 0), f'COD {delivery}/{payment}')
                check(crm['payment_method'] == ('Накладений платіж' if payment=='cod' else 'Переказ на картку'), 'CRM payment label')
                check(crm['novaposhta']['ServiceType'] == ('WarehouseDoors' if delivery=='courier' else 'Warehouse'), 'CRM route')
                check(('WarehouseNumber' in crm['novaposhta']) == (selected and delivery=='warehouse'), 'CRM selected warehouse')
                if delivery == 'warehouse' and selected:
                    doc=waybill.document_properties(obj,s,sender,'recipient-ref','contact-ref')
                    check(doc['CargoType']=='Parcel' and doc['ServiceType']=='WarehouseWarehouse', 'TTN cargo and route')
                    check(doc['Cost']=='199.9', 'TTN declared amount')
                    check(('BackwardDeliveryData' in doc) == (payment=='cod'), 'TTN COD inclusion')
                    if payment=='cod':
                        check(doc['BackwardDeliveryData'][0]['RedeliveryString']=='199.9', 'TTN COD precision')


async def nova_price_matrix():
    np.reset_cache()
    received=[]
    async def provider(payload):
        received.append(payload)
        return {'success': True, 'data': [{'Cost': '82.50', 'CostRedelivery': '4.25'}]}
    with patch.object(np,'_post',provider):
        a=await np.document_price('key','sender','recipient',False,199.90,0.5,199.90)
        check((a.cost,a.redelivery)==(82.5,4.25), 'fractional carrier cost and commission preserved')
        body=received[-1]['methodProperties']
        check(body['Cost']=='199.9' and body['RedeliveryCalculate']['Amount']=='199.9','amounts sent with cents')
        check(body['CargoType']=='Parcel' and body['ServiceType']=='WarehouseWarehouse','quote cargo type same as TTN')
        await np.document_price('key','sender','recipient',False,199.90,0.5,199.90)
        check(len(received)==1,'same quote reuses cache')
        await np.document_price('key','sender','recipient',False,199.91,0.5,199.91)
        check(len(received)==2 and received[-1]['methodProperties']['Cost']=='199.91','different cents do not collide in cache')
        await np.document_price('key','sender','recipient',True,199.91,0.5,0)
        check(received[-1]['methodProperties']['ServiceType']=='WarehouseDoors','courier quote uses door route')
        check('RedeliveryCalculate' not in received[-1]['methodProperties'],'card has no money return')
        for invalid in ('NaN','Infinity',-2,'invalid'):
            try:
                await np.document_price('key','sender','recipient',False,invalid,0.5)
                ok=False
            except np.NovaPoshtaError:
                ok=True
            check(ok, f'invalid price rejected {invalid}')
    np.reset_cache()
    async def bad_provider(_):
        return {'success':True,'data':[{'Cost':'none','CostRedelivery':'3.2'}]}
    with patch.object(np,'_post',bad_provider):
        try:await np.document_price('key','sender','recipient',False,100,0.5);ok=False
        except np.NovaPoshtaError:ok=True
        check(ok,'malformed provider price cannot silently become 0')


async def warehouses_paging():
    np.reset_cache()
    async def provider(payload):
        page=int(payload['methodProperties'].get('Page','1'))
        # Even if carrier returns a full page, client-side conservative
        # filtering can reduce visible matches to one item. Do not hide page 2.
        if page==1:
            data=[{'Ref':f'ref-{i}','Number':str(i),
                  'Description':f'Відділення №{i}', 'CategoryOfWarehouse':'Branch'} for i in range(1,50)]
            data.append({'Ref':'ref-50','Number':'50','Description':'Кафе біля Вокзалу', 'ShortAddress':'вул. Вокзальна', 'CategoryOfWarehouse':'Postomat'})
        else:
            data=[{'Ref':'ref-51','Number':'51','Description':'Поштомат Вокзальна','CategoryOfWarehouse':'Postomat'}]
        return {'success':True,'data':data}
    with patch.object(np,'_post',provider):
        p1=await np.warehouses('key','city','',query='Вокзаль',return_meta=True,limit=50)
        check(len(p1['items'])==1 and p1['has_more'] is True,'carrier page fullness controls has_more')
        check(p1['items'][0].is_postomat is True,'carrier CategoryOfWarehouse identifies postomat')
        p2=await np.warehouses('key','city','',query='Вокзаль',return_meta=True,page=2,limit=50)
        check(len(p2['items'])==1 and p2['has_more'] is False,'second provider page terminates')


def telegram_auth_matrix():
    token='111111:token'
    now=int(time.time())
    def signed(user_id=1234567,issued=now):
        data={'auth_date':str(issued),'query_id':'AAA','user':json.dumps({'id':user_id,'first_name':'Ірина'},ensure_ascii=False,separators=(',',':'))}
        string='\n'.join(f'{k}={data[k]}' for k in sorted(data))
        key=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
        signature=hmac.new(key,string.encode(),hashlib.sha256).hexdigest()
        return urlencode({**data,'hash':signature})
    valid=signed()
    check(parse_init_data(valid,token)['user']['id']==1234567,'Telegram signed initData accepted')
    for raw, label in (
        (valid.replace('1234567','2345678'),'tampered user'),
        (valid+'&auth_date=123','duplicated auth date'),
        (signed(issued=now-90000),'expired auth date'),
        (signed(issued=now+3600),'future auth date'),
    ):
        try:parse_init_data(raw,token);ok=False
        except InitDataError:ok=True
        check(ok,f'Telegram rejects {label}')


async def cloudflare_account_matrix():
    with patch.object(cloudflare,'request',AsyncMock(return_value={'success':True,'result':{'status':'active'}})) as rq:
        check((await cloudflare.verify_token('token','a'*32))['status']=='active','Cloudflare valid account verified')
        check(rq.call_args.args[2] == '/accounts/'+'a'*32+'/tokens/verify','Cloudflare exact account URL')
        prev=rq.await_count
        for account in ('../user', 'bad-id', 'x'*32, 'a'*33):
            try:await cloudflare.verify_token('token',account);ok=False
            except cloudflare.CloudflareError:ok=True
            check(ok and rq.await_count == prev, 'invalid Cloudflare account cannot reach API: '+account)


async def main():
    combo_matrix()
    await nova_price_matrix()
    await warehouses_paging()
    telegram_auth_matrix()
    await cloudflare_account_matrix()
    print(f'API COMPATIBILITY MATRIX: {checked}/{checked}')


if __name__=='__main__':
    asyncio.run(main())
