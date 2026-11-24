from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Literal
from pydantic import BaseModel
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


class ProductPage(BaseModel):
    items:list[ProductOut]
    total:int
    limit:int
    offset:int

@router.get("/products", response_model=list[ProductOut] | ProductPage)
async def list_products(category_id: int | None = None, subcategory_id: int | None = None,
                        search: str | None = Query(None,max_length=160), only_active: bool = False,
                        is_new: bool | None = None, is_sale: bool | None = None,
                        uncategorized: bool = False,paginated:bool=False,
                        limit:int=Query(500,ge=1,le=1000),offset:int=Query(0,ge=0,le=1000000),
                        inventory:Literal['','available','low','out','unpriced','hidden','missing_photos']='',
                        sort:Literal['','name-asc','name-desc','stock-asc','stock-desc','price-asc','price-desc']='',
                        repo: Repository = Depends(get_repo)):
    filters=dict(category_id=category_id,subcategory_id=subcategory_id,search=search,only_active=only_active,
                 is_new=is_new,is_sale=is_sale,uncategorized=uncategorized)
    if inventory:filters['inventory']=inventory
    items=await repo.list_products(**filters,limit=limit,offset=offset,**({'sort':sort} if sort else {}))
    if not paginated:return items
    return dict(items=items,total=await repo.count_products(**filters),limit=limit,offset=offset)


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
from fastapi import BackgroundTasks, File, Form, UploadFile
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from shop.services.product_io import export_xlsx, parse_salesdrive_xlsx

IMPORT_REPLAY_WINDOW = timedelta(hours=24)


def _job_out(job: dict) -> dict:
    """Public job state; the stored rows never leave the server."""
    return {"job_id": job["id"], "status": job["status"], "rows_total": job["rows_total"],
            "rows_done": job["rows_done"], "attempts": job["attempts"], "error": job["error"] or None,
            "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
            "finished_at": job["finished_at"].isoformat() if job.get("finished_at") else None,
            "result": job["result"] if job["status"] == "done" else None}


@router.post('/product-transfer/import')
async def import_products(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    mode: str = Form('upsert'),
    prices: str = Form('none'),
    force: bool = Form(False),
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    """Приймає XLSX як довговічне завдання (A02).

    Файл перевіряється й розбирається одразу: зіпсований файл отримує 400 до
    будь-яких змін. Далі рядки зберігаються в БД, відповідь — 202 з ID, а
    застосування йде у фоні з контрольною точкою після кожного рядка. Якщо
    API перезапуститься, виконавець maintenance продовжить з тієї ж точки.

    Той самий вміст із тими самими параметрами протягом доби не застосовується
    вдруге (залишки з файла перезаписали б продажі): повертається попередній
    підсумок або вже запущене завдання. Свідомий повтор — лише з force.
    """
    if mode not in {'add','update','upsert'}:
        raise HTTPException(400, 'Невідомий режим імпорту')
    if prices not in {'none','regular','discount','both'}:
        raise HTTPException(400, 'Невідомий режим цін')
    if not (file.filename or '').lower().endswith('.xlsx'):
        raise HTTPException(400, 'Підтримується XLSX (експорт SalesDrive)')
    raw=await file.read(10*1024*1024 + 1)
    if len(raw) > 10*1024*1024: raise HTTPException(413, 'Файл завеликий (максимум 10 МБ)')
    try: rows=await run_in_threadpool(parse_salesdrive_xlsx, raw)
    except Exception as exc: raise HTTPException(400, str(exc)) from exc
    from shop.services.catalog_import import encode_rows, run_job, same_database
    payload=encode_rows(rows)
    # Digest of the parsed content, not file bytes: XLSX writers embed save
    # timestamps, so a re-exported identical sheet must count as the same import.
    digest=hashlib.sha256(json.dumps({'mode':mode,'prices':prices,'rows':payload}, ensure_ascii=False).encode()).hexdigest()
    now=datetime.now(timezone.utc)
    if force:  # an explicit re-apply never interrupts an import that is still running
        await repo.forget_catalog_import(digest, only_done=True)
    existing=await repo.claim_catalog_import(digest, who.login, forget_before=now-IMPORT_REPLAY_WINDOW,
                                             mode=mode, prices=prices, payload=payload, total=len(rows))
    if existing is not None and existing.get('status') == 'done' and existing.get('result'):
        imported_at=existing['created_at']
        return {**existing['result'], 'replayed':True, 'job_id':digest, 'status':'done',
                'imported_at':imported_at.isoformat() if imported_at else None}
    if existing is None:
        background.add_task(run_job, digest, open_repo=same_database(repo))
    job=await repo.get_import_job(digest)
    return JSONResponse(status_code=202, content={**_job_out(job), 'replayed': False})


@router.get('/product-transfer/import/{job_id}')
async def import_status(job_id: str, repo: Repository = Depends(get_repo)):
    if not re.fullmatch(r'[a-f0-9]{64}', job_id):
        raise HTTPException(404, 'Завдання імпорту не знайдено')
    job=await repo.get_import_job(job_id)
    if not job:
        raise HTTPException(404, 'Завдання імпорту не знайдено')
    return _job_out(job)


@router.get('/product-transfer/export')
async def export_products_endpoint(repo: Repository = Depends(get_repo)):
    products=await repo.list_products(limit=10000)
    body=await run_in_threadpool(export_xlsx, products, await repo.list_subcategories())
    return Response(body, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition':'attachment; filename="elfar-products.xlsx"'})
