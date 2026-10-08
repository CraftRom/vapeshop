from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from api.auth import Principal, require_staff
from api.schemas import CategoryIn, CategoryOut, SubcategoryIn, SubcategoryOut, ProductIn, ProductOut, ProductPatch, StockDeltaIn, StockIn
from shop.repo.base import Repository
from shop.repo.factory import get_repo

router = APIRouter(dependencies=[Depends(require_staff)])


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(repo: Repository = Depends(get_repo)):
    return await repo.list_categories()


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(data: CategoryIn, repo: Repository = Depends(get_repo)):
    return await repo.create_category(data.model_dump())


@router.get("/categories/{category_id}", response_model=CategoryOut)
async def get_category(category_id: int, repo: Repository = Depends(get_repo)):
    found = await repo.get_category(category_id)
    if not found:
        raise HTTPException(404, "Категорію не знайдено")
    return found


@router.put("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: int, data: CategoryIn, repo: Repository = Depends(get_repo)
):
    category = await repo.update_category(category_id, data.model_dump())
    if not category:
        raise HTTPException(404, "Категорію не знайдено")
    return category


@router.delete("/categories/{category_id}")
async def delete_category(category_id: int, repo: Repository = Depends(get_repo)):
    """М'яке видалення: категорія та її товари зникають з бота, але лишаються в базі."""
    if not await repo.get_category(category_id):
        raise HTTPException(404, "Категорію не знайдено")
    hidden = await repo.delete_category(category_id)
    return {"hidden_products": hidden}


@router.delete("/categories/{category_id}/purge")
async def purge_category(category_id: int, repo: Repository = Depends(get_repo)):
    """Остаточне видалення: категорія та її товари стираються з бази назавжди.

    Окремий шлях, а не прапорець у DELETE — щоб випадковий запит не зніс дані.
    Історія замовлень лишається читабельною: позиції зберігають знімок
    назви й ціни, обнуляється лише посилання на товар.
    """
    if not await repo.get_category(category_id):
        raise HTTPException(404, "Категорію не знайдено")
    return {"purged_products": await repo.purge_category(category_id)}


@router.delete("/products/{product_id}/purge", status_code=204)
async def purge_product(product_id: int, repo: Repository = Depends(get_repo)):
    if not await repo.purge_product(product_id):
        raise HTTPException(404, "Товар не знайдено")


@router.get("/subcategories", response_model=list[SubcategoryOut])
async def list_subcategories(category_id: int | None = None, repo: Repository = Depends(get_repo)):
    return await repo.list_subcategories(category_id=category_id)


@router.post("/subcategories", response_model=SubcategoryOut, status_code=201)
async def create_subcategory(data: SubcategoryIn, repo: Repository = Depends(get_repo)):
    try:
        return await repo.create_subcategory(data.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/subcategories/{subcategory_id}", response_model=SubcategoryOut)
async def update_subcategory(subcategory_id: int, data: SubcategoryIn, repo: Repository = Depends(get_repo)):
    try:
        found = await repo.update_subcategory(subcategory_id, data.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not found:
        raise HTTPException(404, "Субкатегорію не знайдено")
    return found


@router.delete("/subcategories/{subcategory_id}")
async def delete_subcategory(subcategory_id: int, repo: Repository = Depends(get_repo)):
    if not await repo.get_subcategory(subcategory_id):
        raise HTTPException(404, "Субкатегорію не знайдено")
    return {"hidden_products": await repo.delete_subcategory(subcategory_id)}


@router.delete("/subcategories/{subcategory_id}/purge")
async def purge_subcategory(subcategory_id: int, repo: Repository = Depends(get_repo)):
    if not await repo.get_subcategory(subcategory_id):
        raise HTTPException(404, "Субкатегорію не знайдено")
    return {"purged_products": await repo.purge_subcategory(subcategory_id)}


@router.get("/products", response_model=list[ProductOut])
async def list_products(category_id: int | None = None, subcategory_id: int | None = None,
                        search: str | None = None, only_active: bool = False,
                        is_new: bool | None = None, is_sale: bool | None = None,
                        uncategorized: bool = False, repo: Repository = Depends(get_repo)):
    return await repo.list_products(category_id=category_id, subcategory_id=subcategory_id,
                                    search=search, only_active=only_active,
                                    is_new=is_new, is_sale=is_sale, uncategorized=uncategorized)


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(data: ProductIn, who: Principal = Depends(require_staff), repo: Repository = Depends(get_repo)):
    payload = data.model_dump()
    payload.pop("sku", None)
    try:
        product = await repo.create_product(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    from shop.services.panel_notifications import safe_publish
    await safe_publish(repo, "product.created", "Новий товар у каталозі",
                       f"{product.name} · {product.stock} шт. · {product.price} ₴",
                       href=f"/catalog/products/{product.id}", entity_id=product.id, actor=who.name or who.login)
    return product


@router.get("/products/{product_id}/photo")
async def product_photo(product_id: int, repo: Repository = Depends(get_repo)):
    product = await repo.get_product(product_id)
    if not product or not product.photo_file_id:
        raise HTTPException(404, "Фото немає")
    from api.routers.orders import _bot
    from shop.services.product_media import telegram_product_photo
    bot = _bot()
    if not bot:
        raise HTTPException(503, "Бот недоступний — фото не отримати")
    try:
        content = await telegram_product_photo(bot, product.photo_file_id)
    except Exception as exc:
        raise HTTPException(502, "Telegram не віддав фото") from exc
    return Response(content, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, repo: Repository = Depends(get_repo)):
    found = await repo.get_product(product_id)
    if not found:
        raise HTTPException(404, "Товар не знайдено")
    return found


async def _save_product(product_id, payload, repo):
    try:
        product = await repo.update_product(product_id, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not product:
        raise HTTPException(404, "Товар не знайдено")
    return product


@router.put("/products/{product_id}", response_model=ProductOut)
async def update_product(product_id: int, data: ProductIn, repo: Repository = Depends(get_repo)):
    payload = data.model_dump()
    payload.pop("sku", None)
    return await _save_product(product_id, payload, repo)


@router.patch("/products/{product_id}", response_model=ProductOut)
async def patch_product(product_id: int, data: ProductPatch, repo: Repository = Depends(get_repo)):
    payload = data.model_dump(exclude_unset=True)
    if "photo_url" in payload:
        payload["photo_file_id"] = None
    return await _save_product(product_id, payload, repo)


@router.patch("/products/{product_id}/stock", response_model=ProductOut)
async def set_stock(product_id: int, data: StockIn, repo: Repository = Depends(get_repo)):
    product = await repo.set_stock(product_id, data.stock)
    if not product:
        raise HTTPException(404, "Товар не знайдено")
    return product


@router.patch("/products/{product_id}/stock-delta", response_model=ProductOut)
async def adjust_stock(product_id: int, data: StockDeltaIn, repo: Repository = Depends(get_repo)):
    if data.delta == 0:
        product = await repo.get_product(product_id)
    else:
        product = await repo.adjust_stock(product_id, data.delta)
    if not product:
        if data.delta < 0:
            raise HTTPException(409, "Залишок уже змінився — оновіть товар")
        raise HTTPException(404, "Товар не знайдено")
    return product


@router.delete("/products/{product_id}", status_code=204)
async def delete_product(product_id: int, repo: Repository = Depends(get_repo)):
    # М'яке видалення — історія замовлень має лишитись читабельною
    if not await repo.update_product(product_id, {"is_active": False}):
        raise HTTPException(404, "Товар не знайдено")

# ------------------------------- bulk product import / export
from fastapi import File, Form, UploadFile
from fastapi.responses import Response
from shop.services.product_io import export_xlsx, parse_salesdrive_xlsx

@router.post('/product-transfer/import')
async def import_products(
    file: UploadFile = File(...),
    mode: str = Form('upsert'),
    prices: str = Form('none'),
    repo: Repository = Depends(get_repo),
):
    if mode not in {'add','update','upsert'}:
        raise HTTPException(400, 'Невідомий режим імпорту')
    if prices not in {'none','regular','discount','both'}:
        raise HTTPException(400, 'Невідомий режим цін')
    if not (file.filename or '').lower().endswith('.xlsx'):
        raise HTTPException(400, 'Підтримується XLSX (експорт SalesDrive)')
    raw=await file.read()
    if len(raw) > 10*1024*1024: raise HTTPException(413, 'Файл завеликий (максимум 10 МБ)')
    try: rows=parse_salesdrive_xlsx(raw)
    except Exception as exc: raise HTTPException(400, str(exc)) from exc
    cats={c.name.strip().casefold():c for c in await repo.list_categories()}
    subs={(s.category_id, s.name.strip().casefold()):s for s in await repo.list_subcategories()}
    stats={'rows':len(rows),'created':0,'updated':0,'skipped':0,'sku_generated':0,'prices_changed':0,'errors':[]}
    seen=set()
    for n,item in enumerate(rows,2):
        try:
            source_sku = str(item.get('sku') or '').strip()
            if source_sku and source_sku in seen:
                stats['skipped']+=1
                continue
            if source_sku:
                seen.add(source_sku)
            existing=None
            if source_sku:
                existing=(await repo.get_product_by_sku(source_sku) or await repo.get_product_by_external_sku(source_sku)) if item.get("hierarchy") else (await repo.get_product_by_external_sku(source_sku) or await repo.get_product_by_sku(source_sku))
            if existing is None:
                matches=await repo.list_products(search=item['name'], limit=100)
                exact=[p for p in matches if p.name.strip().casefold()==item['name'].strip().casefold()]
                if len(exact)==1:
                    existing=exact[0]
                elif len(exact)>1:
                    raise ValueError('Кілька товарів із такою назвою — вкажіть SKU')
            if mode=='add' and existing or mode=='update' and not existing:
                stats['skipped']+=1
                continue
            cid=sid=None
            if item.get('hierarchy'):
                cname=item['category']
                if cname:
                    key=cname.casefold(); cat=cats.get(key)
                    if not cat:
                        cat=await repo.create_category({'name':cname,'is_active':True}); cats[key]=cat
                    cid=cat.id
                sname=item.get('subcategory')
            else:
                # SalesDrive's former single category is now a subcategory.
                sname=item['category']
            sub_parent=cid
            if item.get('subcategory_parent') and sub_parent is None:
                pname=item['subcategory_parent']; pk=pname.casefold(); parent=cats.get(pk)
                if not parent:
                    parent=await repo.create_category({'name':pname,'is_active':True}); cats[pk]=parent
                sub_parent=parent.id
            if sname:
                key=(sub_parent,sname.casefold()); sub=subs.get(key)
                if not sub:
                    sub=await repo.create_subcategory({'category_id':sub_parent,'name':sname,'is_active':True}); subs[key]=sub
                sid=sub.id
            data={'category_id':cid,'subcategory_id':sid,'name':item['name'],
                  'description':item.get('description') or None,'photo_url':item.get('photo_url') or None}
            if item.get('hierarchy') and item.get('external_sku') is not None:
                data['external_sku']=str(item['external_sku']).strip()[:255] or None
            elif source_sku and (not existing or source_sku != existing.sku):
                data['external_sku']=source_sku[:255]
            if existing:
                data.update({'price':existing.price,'old_price':existing.old_price,'is_sale':existing.is_sale})
            else:
                data.update({'stock':item.get('stock') or 0,'sort_order':0,'price':0,'old_price':None,'is_active':False,'is_new':False,'is_sale':False})
            regular=item.get('regular_price'); discount=item.get('discount_price')
            changed=False
            if item.get('hierarchy') and prices!='none' and item.get('current_price') is not None:
                current=item['current_price']; previous=item.get('old_price') if prices!='regular' else None
                sale=item.get('is_sale') if item.get('is_sale') is not None else bool(previous is not None and previous>current)
                data.update(price=current,old_price=previous,is_sale=bool(sale) if prices!='regular' else False); changed=True
            elif prices=='regular' and regular is not None:
                data.update(price=regular,old_price=None,is_sale=False); changed=True
            elif prices in {'discount','both'}:
                if discount is not None and regular is not None and discount < regular:
                    data.update(price=discount,old_price=regular,is_sale=True); changed=True
                elif regular is not None:
                    data.update(price=regular,old_price=None,is_sale=False); changed=True
            if changed:
                stats['prices_changed']+=1
                if not existing:
                    data['is_active']=True
            for flag in ('is_active','is_new','is_sale'):
                if flag=='is_sale' and prices=='regular':
                    continue
                if item.get(flag) is not None and (existing or changed or flag == 'is_new'):
                    data[flag]=item[flag]
            if existing:
                if item.get('stock') is not None: data['stock']=item['stock']
                await repo.update_product(existing.id,data); stats['updated']+=1
            else:
                await repo.create_product(data); stats['created']+=1; stats['sku_generated']+=1
        except Exception as exc:
            if hasattr(repo, 's'):
                await repo.s.rollback()
            stats['errors'].append({'row':n,'name':item.get('name'),'error':str(exc)[:200]})
    return stats

@router.get('/product-transfer/export')
async def export_products_endpoint(repo: Repository = Depends(get_repo)):
    products=await repo.list_products(limit=10000)
    body=export_xlsx(products, await repo.list_subcategories())
    return Response(body, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition':'attachment; filename="elfar-products.xlsx"'})
