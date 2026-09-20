from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException

from api.auth import Principal, require_staff
from api.schemas import CategoryIn, CategoryOut, ProductIn, ProductOut, StockDeltaIn, StockIn
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services.product_io import normalize_sku

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


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    category_id: int | None = None,
    search: str | None = None,
    only_active: bool = False,
    repo: Repository = Depends(get_repo),
):
    return await repo.list_products(
        category_id=category_id, search=search, only_active=only_active
    )


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(
    data: ProductIn,
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    if not await repo.get_category(data.category_id):
        raise HTTPException(400, "Такої категорії немає")
    payload=data.model_dump()
    if payload.get("sku"):
        sku=normalize_sku(payload["sku"])
        if not sku: raise HTTPException(400, "Невалідний SKU: 3–32 символи A–Z, 0–9, ., _ або -")
        if await repo.get_product_by_sku(sku): raise HTTPException(409, "Такий SKU вже використовується")
        payload["sku"]=sku
    product = await repo.create_product(payload)

    from shop.services.panel_notifications import safe_publish
    await safe_publish(
        repo,
        "product.created",
        "Новий товар у каталозі",
        f"{product.name} · {product.stock} шт. · {product.price} ₴",
        href=f"/catalog?search={quote_plus(product.name)}",
        entity_id=product.id,
        actor=who.name or who.login,
    )
    return product


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, repo: Repository = Depends(get_repo)):
    found = await repo.get_product(product_id)
    if not found:
        raise HTTPException(404, "Товар не знайдено")
    return found


@router.put("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int, data: ProductIn, repo: Repository = Depends(get_repo)
):
    payload=data.model_dump()
    if payload.get("sku"):
        sku=normalize_sku(payload["sku"])
        if not sku: raise HTTPException(400, "Невалідний SKU")
        other=await repo.get_product_by_sku(sku)
        if other and other.id != product_id: raise HTTPException(409, "Такий SKU вже використовується")
        payload["sku"]=sku
    else:
        current=await repo.get_product(product_id)
        payload["sku"]=current.sku if current else None
    product = await repo.update_product(product_id, payload)
    if not product:
        raise HTTPException(404, "Товар не знайдено")
    return product


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
from shop.services.product_io import export_xlsx, generate_sku, parse_salesdrive_xlsx

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
    stats={'rows':len(rows),'created':0,'updated':0,'skipped':0,'sku_generated':0,'prices_changed':0,'errors':[]}
    seen=set()
    for n,item in enumerate(rows,2):
        try:
            cname=item['category'] or 'Без категорії'; key=cname.casefold(); cat=cats.get(key)
            if not cat:
                cat=await repo.create_category({'name':cname,'description':None,'sort_order':len(cats),'is_active':True}); cats[key]=cat
            sku=normalize_sku(item.get('sku'))
            if sku and sku in seen: sku=None
            if sku:
                existing=await repo.get_product_by_sku(sku)
            else:
                existing=None; sku=await generate_sku(repo,cname); stats['sku_generated']+=1
            seen.add(sku)
            # When SalesDrive SKU is invalid, try matching by exact name before creating a duplicate.
            if existing is None:
                matches=await repo.list_products(search=item['name'], limit=20)
                existing=next((p for p in matches if p.name.strip().casefold()==item['name'].strip().casefold()),None)
                if existing and normalize_sku(item.get('sku')) is None: sku=existing.sku
            if mode=='add' and existing: stats['skipped']+=1; continue
            if mode=='update' and not existing: stats['skipped']+=1; continue
            data={'category_id':cat.id,'name':item['name'],'sku':sku,'description':item.get('description') or None,
                  'photo_url':item.get('photo_url') or None,'is_active':True}
            if existing:
                data.update({'stock':existing.stock,'sort_order':existing.sort_order,'price':existing.price,'old_price':existing.old_price})
            else:
                # Price is mandatory internally. With prices disabled, new items get 0 and stay hidden until reviewed.
                data.update({'stock':0,'sort_order':0,'price':0,'old_price':None,'is_active':prices!='none'})
            regular=item.get('regular_price'); discount=item.get('discount_price')
            if prices=='regular' and regular is not None:
                data['price']=regular; data['old_price']=None; stats['prices_changed']+=1
            elif prices in {'discount','both'}:
                if discount is not None and regular is not None and discount < regular:
                    data['price']=discount; data['old_price']=regular; stats['prices_changed']+=1
                elif regular is not None:
                    data['price']=regular; data['old_price']=None; stats['prices_changed']+=1
            if existing: await repo.update_product(existing.id,data); stats['updated']+=1
            else: await repo.create_product(data); stats['created']+=1
        except Exception as exc:
            stats['errors'].append({'row':n,'name':item.get('name'),'error':str(exc)[:200]})
    return stats

@router.get('/product-transfer/export')
async def export_products_endpoint(repo: Repository = Depends(get_repo)):
    products=await repo.list_products(limit=10000)
    body=export_xlsx(products)
    return Response(body, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition':'attachment; filename="elfar-products.xlsx"'})
