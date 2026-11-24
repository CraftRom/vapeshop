"""Durable XLSX catalog import (A02).

The API parses and validates the file, stores the parsed rows as a queued job
and returns 202 with its id. Rows are applied in the background with a fenced
checkpoint after every row: if the API restarts mid-import, the lease expires
and the maintenance worker continues from the checkpoint instead of starting
over or leaving the catalog half-imported without anyone knowing.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

log = logging.getLogger("catalog.import")

LEASE_SECONDS = 60
MAX_ATTEMPTS = 3
DECIMAL_FIELDS = ("current_price", "old_price", "regular_price", "discount_price")


def encode_rows(rows: list[dict]) -> str:
    """JSON with exact money: Decimals travel as strings, never floats."""
    def clean(item):
        out = {}
        for key, value in item.items():
            if isinstance(value, Decimal):
                out[key] = {"$decimal": str(value)}
            elif value is None or isinstance(value, (str, int, float, bool)):
                out[key] = value
            else:
                out[key] = str(value)
        return out
    return json.dumps([clean(item) for item in rows], ensure_ascii=False, separators=(",", ":"))


def decode_rows(payload: str) -> list[dict]:
    rows = json.loads(payload)
    for item in rows:
        for key, value in list(item.items()):
            if isinstance(value, dict) and set(value) == {"$decimal"}:
                item[key] = Decimal(value["$decimal"])
    return rows


def same_database(repo):
    """open_repo() bound to the engine of an existing request session.

    The background task outlives the request session, so it opens its own,
    but on the very same database (also when tests override get_repo).
    """
    from contextlib import asynccontextmanager
    from sqlalchemy.ext.asyncio import AsyncSession
    from shop.repo.sql import SqlRepository
    bind = repo.s.bind

    @asynccontextmanager
    async def factory():
        async with AsyncSession(bind, expire_on_commit=False) as session:
            yield SqlRepository(session)
    return factory


def empty_stats(total: int) -> dict:
    return {"rows": total, "created": 0, "updated": 0, "skipped": 0, "sku_generated": 0,
            "prices_changed": 0, "errors": []}


class ImportApplier:
    """Applies one row at a time; state (group caches, seen SKUs) is rebuildable."""

    def __init__(self, repo, mode: str, prices: str, stats: dict):
        self.repo, self.mode, self.prices, self.stats = repo, mode, prices, stats
        self.seen: set[str] = set()
        self.cats: dict = {}
        self.subs: dict = {}

    async def prepare(self, done_rows=()):
        self.cats = {c.name.strip().casefold(): c for c in await self.repo.list_categories()}
        self.subs = {(s.category_id, s.name.strip().casefold()): s for s in await self.repo.list_subcategories()}
        # Duplicate-SKU detection must survive a resume from a checkpoint.
        for item in done_rows:
            sku = str(item.get("sku") or "").strip()
            if sku and not item.get("error"):
                self.seen.add(sku)

    async def apply(self, item: dict, n: int) -> None:
        n = item.get('row', n)
        if item.get('error'):
            self.stats['skipped'] += 1
            self.stats['errors'].append({'row': n, 'name': item.get('name'), 'error': item['error'][:200]})
            return
        try:
            source_sku = str(item.get('sku') or '').strip()
            if source_sku and source_sku in self.seen:
                self.stats['skipped']+=1
                return
            if source_sku:
                self.seen.add(source_sku)
            existing=None
            if source_sku:
                existing=(await self.repo.get_product_by_sku(source_sku) or await self.repo.get_product_by_external_sku(source_sku)) if item.get("hierarchy") else (await self.repo.get_product_by_external_sku(source_sku) or await self.repo.get_product_by_sku(source_sku))
            if existing is None:
                matches=await self.repo.list_products(search=item['name'], limit=100)
                exact=[p for p in matches if p.name.strip().casefold()==item['name'].strip().casefold()]
                if len(exact)==1:
                    existing=exact[0]
                elif len(exact)>1:
                    raise ValueError('Кілька товарів із такою назвою — вкажіть SKU')
            if self.mode=='add' and existing or self.mode=='update' and not existing:
                self.stats['skipped']+=1
                return
            cid=sid=None
            if item.get('hierarchy'):
                cname=item['category']
                if cname:
                    key=cname.casefold(); cat=self.cats.get(key)
                    if not cat:
                        cat=await self.repo.create_category({'name':cname,'is_active':True}); self.cats[key]=cat
                    cid=cat.id
                sname=item.get('subcategory')
            else:
                # SalesDrive's former single category is now a subcategory.
                sname=item['category']
            sub_parent=cid
            if item.get('subcategory_parent') and sub_parent is None:
                pname=item['subcategory_parent']; pk=pname.casefold(); parent=self.cats.get(pk)
                if not parent:
                    parent=await self.repo.create_category({'name':pname,'is_active':True}); self.cats[pk]=parent
                sub_parent=parent.id
            if sname:
                key=(sub_parent,sname.casefold()); sub=self.subs.get(key)
                if not sub:
                    sub=await self.repo.create_subcategory({'category_id':sub_parent,'name':sname,'is_active':True}); self.subs[key]=sub
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
            if item.get('hierarchy') and self.prices!='none' and item.get('current_price') is not None:
                current=item['current_price']; previous=item.get('old_price') if self.prices!='regular' else None
                sale=item.get('is_sale') if item.get('is_sale') is not None else bool(previous is not None and previous>current)
                data.update(price=current,old_price=previous,is_sale=bool(sale) if self.prices!='regular' else False); changed=True
            elif self.prices=='regular' and regular is not None:
                data.update(price=regular,old_price=None,is_sale=False); changed=True
            elif self.prices in {'discount','both'}:
                if discount is not None and regular is not None and discount < regular:
                    data.update(price=discount,old_price=regular,is_sale=True); changed=True
                elif regular is not None:
                    data.update(price=regular,old_price=None,is_sale=False); changed=True
            if changed:
                self.stats['prices_changed']+=1
                if not existing:
                    data['is_active']=True
            for flag in ('is_active','is_new','is_sale'):
                if flag=='is_sale' and self.prices=='regular':
                    return
                if item.get(flag) is not None and (existing or changed or flag == 'is_new'):
                    data[flag]=item[flag]
            if existing:
                if item.get('stock') is not None: data['stock']=item['stock']
                await self.repo.update_product(existing.id,data); self.stats['updated']+=1
            else:
                await self.repo.create_product(data); self.stats['created']+=1; self.stats['sku_generated']+=1
        except Exception as exc:
            if hasattr(self.repo, 's'):
                await self.repo.s.rollback()
            self.stats['errors'].append({'row':n,'name':item.get('name'),'error':str(exc)[:200]})


async def apply_all(rows, mode, prices, repo) -> dict:
    """Synchronous helper (tests, tools): applies every row in this session."""
    applier = ImportApplier(repo, mode, prices, empty_stats(len(rows)))
    await applier.prepare()
    for index, item in enumerate(rows):
        await applier.apply(item, index + 2)
    return applier.stats


async def run_job(digest: str, *, open_repo=None, owner: str | None = None, now=None) -> str | None:
    """Lease the job, apply remaining rows with checkpoints, finish. Returns final status."""
    if open_repo is None:
        from shop.repo.factory import open_repo
    owner = owner or "import-" + secrets.token_hex(8)
    clock = (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))
    async with open_repo() as repo:
        if not await repo.lease_import_job(digest, owner, now=clock(), lease_until=clock() + timedelta(seconds=LEASE_SECONDS),
                                           max_attempts=MAX_ATTEMPTS):
            return None
        job = await repo.get_import_job(digest)
        try:
            payload = await repo.import_job_rows(digest)
            if payload is None:
                raise RuntimeError("Рядки завдання не збережені")
            rows = decode_rows(json.dumps(payload))
            done = int(job["rows_done"] or 0)
            stats = job["result"] if (done and job["result"]) else empty_stats(len(rows))
            applier = ImportApplier(repo, job["mode"], job["prices"], stats)
            await applier.prepare(rows[:done])
            for index in range(done, len(rows)):
                await applier.apply(rows[index], index + 2)
                if not await repo.checkpoint_import_job(digest, owner, rows_done=index + 1, partial=applier.stats,
                                                        lease_until=clock() + timedelta(seconds=LEASE_SECONDS)):
                    log.warning("Оренду імпорту %s перехопив інший виконавець", digest[:12],
                                extra={"event": "catalog.import.lease_lost"})
                    return "lost"
            await repo.finish_catalog_import(digest, applier.stats, owner=owner)
            log.info("Імпорт каталогу завершено", extra={"event": "catalog.import.done", "jobId": digest[:12],
                     "created": applier.stats["created"], "updated": applier.stats["updated"],
                     "errors": len(applier.stats["errors"])})
            return "done"
        except Exception as exc:
            log.exception("Імпорт каталогу перервано", extra={"event": "catalog.import.failed", "jobId": digest[:12]})
            try:
                await repo.s.rollback()
            except Exception:
                pass
            return await repo.fail_import_job(digest, owner, str(exc) or type(exc).__name__, max_attempts=MAX_ATTEMPTS)


async def run_pending(*, open_repo=None, limit: int = 1) -> int:
    """Maintenance recovery: queued jobs and jobs whose lease expired."""
    if open_repo is None:
        from shop.repo.factory import open_repo
    handled = 0
    for _ in range(limit):
        async with open_repo() as repo:
            digest = await repo.next_import_job(datetime.now(timezone.utc), max_attempts=MAX_ATTEMPTS)
        if not digest:
            break
        if await run_job(digest, open_repo=open_repo):
            handled += 1
    return handled
