"""HTTP/repository/migration catalog checks with neutral goods."""
import asyncio, importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from decimal import Decimal
from unittest.mock import patch
from sqlalchemy import create_engine, text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from qa_common import boot,init_data,Report
test_directory=TemporaryDirectory(prefix='catalog-hierarchy-')
app,Session,_=boot(str(Path(test_directory.name)/'catalog.db')); c=TestClient(app); r=Report('CATALOG HIERARCHY')
A={'Authorization':'Bearer '+c.post('/api/auth/login',json={'login':'admin','password':'secret'}).json()['access_token']}
H=init_data(90123); c.get('/api/shop/config',headers=H); c.post('/api/shop/age-confirm',headers=H)
def req(method,path,data=None):
 response=c.request(method,'/api/catalog'+path,json=data,headers=A)
 assert response.status_code<300,(response.status_code,response.text)
 return response.json() if response.content else None
root=req('POST','/categories',{'name':'Аксесуари'}); other=req('POST','/categories',{'name':'Подарунки'})
sub=req('POST','/subcategories',{'name':'Сумки','category_id':root['id']}); orphan=req('POST','/subcategories',{'name':'Самостійна група'})
groups=[{}, {'category_id':root['id']}, {'subcategory_id':sub['id']}, {'category_id':root['id'],'subcategory_id':sub['id']}, {'subcategory_id':orphan['id']}]
ps=[req('POST','/products',{'name':f'Сумка {i}','price':'129.90','stock':4,'sku':'USER-ARTICLE',**group}) for i,group in enumerate(groups)]
r.check(all(p['sku'].startswith('ELF-') and p['sku']!='USER-ARTICLE' for p in ps),'автоматичний SKU для всіх варіантів групування')
r.check(len({p['sku'] for p in ps})==5,'унікальність SKU')
def public(**params): return c.get('/api/shop/products',params=params,headers=H).json()
r.check(len(public())==5,'товари без груп не губляться в JOIN')
r.check(len(public(category_id=root['id']))==3,'категорія включає дочірні товари без дублів')
r.check(len(public(subcategory_id=sub['id']))==2,'відбір субкатегорії')
r.check(len(public(uncategorized=True))==1,'відбір без обох груп')
r.check(next(x for x in req('GET','/categories') if x['id']==root['id'])['products_count']==3,'лічильник категорії включає субкатегорії')
p=ps[3]; pid=p['id']; ep=f'/products/{pid}'
req('PATCH',ep,{'is_new':True}); r.check(len(public(is_new=True))==1,'новинка збережена й керує API вітрини')
req('PATCH',ep,{'is_sale':True,'old_price':'159.90','price':'129.90'}); r.check(len(public(is_sale=True))==1,'акція збігається в обох API')
r.check(c.patch('/api/catalog'+ep,json={'old_price':'100'},headers=A).status_code==400,'невалідна акційна ціна відхиляється')
x=req('PATCH',ep,{'description':'Новий опис'})
r.check(x['is_new'] and x['is_sale'] and x['stock']==4 and x['price']=='129.90','зміна опису не перезаписує інші блоки')
r.check(x['sku']==p['sku'],'SKU незмінний')
r.check(c.patch('/api/catalog'+ep,json={'sku':'REPLACED'},headers=A).status_code==422,'PATCH забороняє зміну SKU')
r.check(c.patch('/api/catalog'+ep,json={'category_id':other['id']},headers=A).status_code==400,'несумісні групи відхиляються')
r.check(c.patch('/api/catalog'+ep,json={'category_id':99999},headers=A).status_code==400,'неіснуюча категорія відхиляється')
req('PUT',f"/subcategories/{sub['id']}",{'name':sub['name'],'category_id':other['id']})
r.check(req('GET',ep)['category_id']==other['id'] and req('GET',f"/products/{ps[2]['id']}")['category_id'] is None,'переміщення групи узгоджує батьківські зв’язки')
req('PATCH',ep,{'category_id':None,'subcategory_id':None,'is_sale':False}); r.check(not public(is_sale=True),'вимкнена акція прибрана з розділу')
req('PATCH',ep,{'is_active':False}); r.check(c.get(f'/api/shop/products/{pid}',headers=H).status_code==404,'прихований товар недоступний на сторінці вітрини')
req('PATCH',ep,{'is_active':True}); r.check(req('GET',ep)['is_new'],'відновлення видимості зберігає новинку')
async def repository_checks():
 from shop.repo.sql import SqlRepository
 from shop import models as m
 from shop.services.product_io import export_xlsx,parse_salesdrive_xlsx
 from bot import keyboards as kb
 async with Session() as session:
  repo=SqlRepository(session); row=await session.get(m.Product,pid); row.photo_file_id='old-photo'; await session.commit()
 response=c.patch('/api/catalog'+ep,json={'photo_url':'https://example.com/image.png'},headers=A)
 async with Session() as session:
  repo=SqlRepository(session); after=await repo.get_product(pid); article=after.sku
  r.check(after.photo_file_id is None and after.photo_url,'нове фото замінює Telegram фото')
  after=await repo.update_product(pid,{'sku':'OVERRIDE','name':'Змінена назва'})
  r.check(after.sku==article,'SKU захищений також у репозиторії')
  parsed=parse_salesdrive_xlsx(export_xlsx(await repo.list_products(),await repo.list_subcategories()))
  r.check(len(parsed)==5 and all(x['hierarchy'] for x in parsed),'XLSX читає власний експорт із новою ієрархією')
  r.check(kb.product_card(await repo.get_product(ps[0]['id'])).inline_keyboard[-1][0].callback_data=='shelf:all','бот повертає товар без груп до всіх товарів')
  r.check(kb.product_card(await repo.get_product(ps[2]['id'])).inline_keyboard[-1][0].callback_data.startswith('sub:'),'бот відкриває субкатегорії')
  with patch('shop.services.product_io.generate_sku',side_effect=[article,'ELF-GEN-UNIQUE01']):
   created=await repo.create_product({'name':'Колізія','price':Decimal('10')})
  r.check(created.sku=='ELF-GEN-UNIQUE01','колізія під час INSERT повторює генерацію')
asyncio.run(repository_checks())
spec=importlib.util.spec_from_file_location('catalog_migration','alembic/versions/d7a24c10b853_catalog_taxonomy.py'); mig=importlib.util.module_from_spec(spec); spec.loader.exec_module(mig)
with create_engine('sqlite:///:memory:').begin() as conn:
 conn.execute(text('CREATE TABLE categories (id INTEGER PRIMARY KEY,name VARCHAR(128) NOT NULL,description TEXT,sort_order INTEGER NOT NULL,is_active BOOLEAN NOT NULL)'))
 conn.execute(text('CREATE TABLE products (id INTEGER PRIMARY KEY,category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,name VARCHAR(255),sku VARCHAR(32) NOT NULL UNIQUE,price NUMERIC,old_price NUMERIC,is_active BOOLEAN,sort_order INTEGER)'))
 conn.execute(text("INSERT INTO categories VALUES (7,'Сумки','Опис групи',3,1)"))
 for pid,sku in [(1,'VALID-001'),(2,' abc-12 '),(3,'невалідний'),(4,'ABC-12')]:
  conn.execute(text('INSERT INTO products VALUES (:id,7,:name,:sku,100,150,1,0)'),{'id':pid,'name':f'Товар {pid}','sku':sku})
 with Operations.context(MigrationContext.configure(conn)): mig.upgrade()
 rows=conn.execute(text('SELECT id,category_id,subcategory_id,sku,external_sku,is_new,is_sale FROM products ORDER BY id')).all()
 r.check(len(rows)==4 and all(x.category_id is None and x.subcategory_id==7 for x in rows),'міграція зберігає всі товари й зв’язки')
 r.check(conn.scalar(text('SELECT COUNT(*) FROM categories'))==0 and conn.scalar(text('SELECT name FROM subcategories WHERE id=7'))=='Сумки','старі категорії перенесені зі збереженням ID')
 r.check(rows[0].sku=='VALID-001' and rows[3].sku=='ABC-12','коректні SKU збережені')
 r.check(rows[1].sku.startswith('ELF-LEG-') and rows[2].sku.startswith('ELF-LEG-'),'невалідні та конфліктні SKU виправлені')
 r.check(rows[1].external_sku==' abc-12 ' and rows[2].external_sku=='невалідний','початкові артикули не втрачені')
 r.check(all(not x.is_new and x.is_sale for x in rows),'старі акції перенесені, новинки не вигадуються')
 conn.execute(text("INSERT INTO subcategories (name,sort_order,is_active) VALUES ('Нова група',0,1)"))
 r.check(conn.scalar(text('SELECT MAX(id) FROM subcategories'))==8,'нові ID не конфліктують із перенесеними')
raise SystemExit(bool(r.done()))
