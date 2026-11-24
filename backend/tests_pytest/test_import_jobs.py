"""A02: durable XLSX import jobs — checkpoints, leases, recovery, failure."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shop import models as m
from shop.repo.sql import SqlRepository
from shop.services import catalog_import as jobs

NOW = datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def env(tmp_path):
    engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'jobs.db'))
    async with engine.begin() as connection:
        await connection.run_sync(m.Base.metadata.create_all)

    @asynccontextmanager
    async def open_repo():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield SqlRepository(session)
    async with open_repo() as repo:
        for n in range(1, 6):
            await repo.create_product({'name': f'Aroma {n}', 'price': Decimal('100'), 'stock': 1, 'is_active': True,
                                       'sort_order': 0, 'is_new': False, 'is_sale': False, 'old_price': None})
    yield open_repo
    await engine.dispose()


def rows():
    return [{'row': n + 1, 'name': f'Aroma {n}', 'sku': None, 'external_sku': None, 'category': '', 'subcategory': '',
             'hierarchy': False, 'subcategory_parent': '', 'description': None, 'photo_url': None,
             'current_price': Decimal('99.90'), 'old_price': None, 'regular_price': Decimal('99.90'),
             'discount_price': None, 'stock': 10 * n, 'is_active': None, 'is_new': None, 'is_sale': None}
            for n in range(1, 6)]


async def queue(open_repo, digest='d' * 64):
    async with open_repo() as repo:
        assert await repo.claim_catalog_import(digest, 'admin', forget_before=NOW - timedelta(days=1), mode='update',
                                               prices='none', payload=jobs.encode_rows(rows()), total=5) is None
    return digest


async def stocks(open_repo):
    async with open_repo() as repo:
        return [p.stock for p in sorted(await repo.list_products(), key=lambda p: p.id)]


def test_money_travels_exactly_through_the_stored_payload():
    decoded = jobs.decode_rows(jobs.encode_rows(rows()))
    assert decoded[0]['current_price'] == Decimal('99.90') and isinstance(decoded[0]['current_price'], Decimal)
    assert decoded == rows()


@pytest.mark.asyncio
async def test_a_job_applies_every_row_and_releases_its_payload(env):
    digest = await queue(env)
    assert await jobs.run_job(digest, open_repo=env) == 'done'
    assert await stocks(env) == [10, 20, 30, 40, 50]
    async with env() as repo:
        job = await repo.get_import_job(digest)
        assert job['status'] == 'done' and job['rows_done'] == 5 and job['result']['updated'] == 5
        assert await repo.import_job_rows(digest) is None, 'parsed rows are not kept after completion'


@pytest.mark.asyncio
async def test_interrupted_job_resumes_from_its_checkpoint_without_reapplying_done_rows(env):
    digest = await queue(env)
    owner = 'api-crashed'
    async with env() as repo:
        assert await repo.lease_import_job(digest, owner, now=NOW, lease_until=NOW + timedelta(seconds=60))
        applier = jobs.ImportApplier(repo, 'update', 'none', jobs.empty_stats(5))
        await applier.prepare()
        for index, item in enumerate(jobs.decode_rows(jobs.encode_rows(rows()))[:2]):
            await applier.apply(item, index + 2)
        # The API dies right after the second checkpoint; its lease is in the past.
        assert await repo.checkpoint_import_job(digest, owner, rows_done=2, partial=applier.stats,
                                                lease_until=NOW - timedelta(seconds=1))
        await repo.update_product(1, {'stock': 3})  # a sale after row 1 was imported
    async with env() as repo:
        assert await repo.next_import_job(datetime.now(timezone.utc)) == digest
    assert await jobs.run_pending(open_repo=env) == 1
    assert await stocks(env) == [3, 20, 30, 40, 50], 'row 1 is not re-applied over the later sale'
    async with env() as repo:
        job = await repo.get_import_job(digest)
    assert job['status'] == 'done' and job['attempts'] == 2 and job['result']['updated'] == 5


@pytest.mark.asyncio
async def test_a_live_lease_is_never_taken_and_a_lost_lease_cannot_write(env):
    digest = await queue(env)
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    async with env() as repo:
        assert await repo.lease_import_job(digest, 'first', now=NOW, lease_until=future)
        assert not await repo.lease_import_job(digest, 'second', now=NOW, lease_until=future)
        assert await repo.next_import_job(datetime.now(timezone.utc)) is None
        assert not await repo.checkpoint_import_job(digest, 'second', rows_done=5, partial={}, lease_until=future)
        assert not await repo.finish_catalog_import(digest, {}, owner='second')
    assert await jobs.run_pending(open_repo=env) == 0
    assert await stocks(env) == [1, 1, 1, 1, 1]


@pytest.mark.asyncio
async def test_repeated_failures_end_as_failed_with_the_reason_and_no_stored_rows(env, monkeypatch):
    digest = await queue(env)

    async def broken(self, item, n):
        raise RuntimeError('database went away')
    monkeypatch.setattr(jobs.ImportApplier, 'apply', broken)
    outcomes = [await jobs.run_job(digest, open_repo=env) for _ in range(jobs.MAX_ATTEMPTS)]
    assert outcomes == ['queued', 'queued', 'failed']
    assert await jobs.run_job(digest, open_repo=env) is None, 'no fourth attempt'
    async with env() as repo:
        job = await repo.get_import_job(digest)
        assert job['status'] == 'failed' and 'database went away' in job['error']
        assert await repo.import_job_rows(digest) is None


@pytest.mark.asyncio
async def test_same_content_while_queued_returns_the_existing_job(env):
    digest = await queue(env)
    async with env() as repo:
        again = await repo.claim_catalog_import(digest, 'admin', forget_before=NOW - timedelta(days=1), mode='update',
                                                prices='none', payload=jobs.encode_rows(rows()), total=5)
        assert again['status'] == 'queued' and again['id'] == digest
        count = len((await repo.s.scalars(select(m.CatalogImport))).all())
    assert count == 1
