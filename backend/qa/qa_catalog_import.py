"""Import round trip, external articles and photo parity with neutral goods."""
from io import BytesIO
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import asyncio
from openpyxl import Workbook
from fastapi.testclient import TestClient
from qa_common import boot,init_data,Report
app,Session,_=boot('/tmp/catalog_import_validation.db'); c=TestClient(app); r=Report('CATALOG IMPORT')
A={'Authorization':'Bearer '+c.post('/api/auth/login',json={'login':'admin','password':'secret'}).json()['access_token']}
H=init_data(12342); c.get('/api/shop/config',headers=H); c.post('/api/shop/age-confirm',headers=H)
def req(method,path,data=None):
 response=c.request(method,'/api/catalog'+path,json=data,headers=A)
 assert response.status_code<300,(response.status_code,response.text)
 return response.json() if response.content else None
def xlsx(rows):
 wb=Workbook(); ws=wb.active
 for row in rows: ws.append(row)
 out=BytesIO(); wb.save(out); return out.getvalue()
def upload(rows,prices='both'):
 response=c.post('/api/catalog/product-transfer/import',headers=A,files={'file':('goods.xlsx',xlsx(rows),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},data={'mode':'upsert','prices':prices})
 assert response.status_code==200,response.text
 return response.json()
sheet=[['Товар/Послуга','SKU','Категорія','Ціна','Ціна зі знижкою','Новинка','Активний','Залишок'],['Нейтральний аксесуар','зовнішній артикул','Група імпорту',100,80,'Так','Так',7]]
result=upload(sheet); item=next(p for p in req('GET','/products') if p['name']=='Нейтральний аксесуар')
r.check(result['created']==1 and not result['errors'] and item['sku'].startswith('ELF-') and item['external_sku']=='зовнішній артикул','імпорт генерує системний SKU та зберігає зовнішній')
r.check(item['category_id'] is None and item['subcategory_id'] and item['is_new'] and item['is_sale'] and item['stock']==7,'старий імпорт створює субкатегорію та зберігає позначки')
result=upload(sheet)
r.check(result['created']==0 and result['updated']==1 and req('GET',f"/products/{item['id']}")['sku']==item['sku'],'повторний імпорт не створює дубль і не змінює SKU')
result=upload([sheet[0],['Без ціни','NO-PRICE',None,10,None,'Так','Так',1]],prices='none')
unpriced=next(p for p in req('GET','/products') if p['name']=='Без ціни')
r.check(result['created']==1 and not unpriced['is_active'],'новий товар без імпорту ціни залишається прихованим')
root=req('POST','/categories',{'name':'Колекції'}); sub=req('POST','/subcategories',{'name':'Літня колекція','category_id':root['id']})
only_sub=req('POST','/products',{'name':'Сумка','subcategory_id':sub['id'],'price':'129.90','stock':5})
inactive_sale=req('POST','/products',{'name':'Без активної акції','price':'200','old_price':'150','is_sale':False})
export=c.get('/api/catalog/product-transfer/export',headers=A)
result=c.post('/api/catalog/product-transfer/import',headers=A,files={'file':('own.xlsx',export.content,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},data={'mode':'upsert','prices':'both'}).json()
r.check(result['created']==0 and not result['errors'],'власний експорт повертається без дублювання')
after=req('GET',f"/products/{only_sub['id']}")
r.check(after['category_id'] is None and after['subcategory_id']==sub['id'] and after['price']=='129.90','XLSX зберігає товар лише із субкатегорією та точну ціну')
unchanged=req('GET',f"/products/{inactive_sale['id']}")
r.check(unchanged['price']=='200.00' and unchanged['old_price']=='150.00' and not unchanged['is_sale'],'XLSX не підміняє поточну ціну старою для вимкненої акції')
result=upload([['Товар','SKU','Субкатегорія','Ціна','Зовнішній артикул'],['Новий аксесуар','EXPORT-COPY-001',None,'73.50','ORIGIN-COPY']])
copied=next(p for p in req('GET','/products') if p['name']=='Новий аксесуар')
r.check(result['created']==1 and copied['sku']!='EXPORT-COPY-001' and copied['external_sku']=='ORIGIN-COPY','перенесення власного XLSX зберігає зовнішній артикул і генерує системний')
from shop.formatting import money
r.check(money(Decimal('129.90'))=='129.9' and money(Decimal('100'))=='100','грошовий формат зберігає копійки')
r.check(c.post('/api/catalog/categories',json={'name':'   '},headers=A).status_code==422,'порожня назва групи відхиляється')
async def photo_setup():
 from shop.repo.sql import SqlRepository
 async with Session() as session: await SqlRepository(session).update_product(item['id'],{'photo_file_id':'sample-photo','photo_url':None})
asyncio.run(photo_setup())
class PhotoBot:
 async def get_file(self,fid): return SimpleNamespace(file_path='photo.jpg')
 async def download_file(self,path): return BytesIO(b'\xff\xd8sample\xff\xd9')
with patch('api.routers.orders._bot',return_value=PhotoBot()):
 private=c.get(f"/api/catalog/products/{item['id']}/photo",headers=A); public=c.get(f"/api/shop/products/{item['id']}/photo",headers=H)
 r.check(private.status_code==200 and private.content==public.content,'dashboard і вітрина отримують те саме Telegram фото через проксі')
r.check(c.get(f"/api/catalog/products/{item['id']}/photo").status_code==401,'фото dashboard потребує авторизації')
raise SystemExit(bool(r.done()))
