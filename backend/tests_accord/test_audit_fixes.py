"""Regression tests for the 2026-11-17 audit findings (expected, fixed behaviour).

Each test describes the correct behaviour; the audit evidence reproduced the
opposite. SQLite only, no network: the SMS provider is replaced in-process.
"""
from __future__ import annotations

import asyncio
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException, Request
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.auth import Principal, require_staff
from api.routers import catalog
from shop import models as m
from shop.config import settings
from shop.entities import OperatorRole as Role
from shop.repo.factory import get_repo
from shop.repo.sql import SqlRepository
from shop.services.product_io import parse_salesdrive_xlsx
from shop.services.shop_service import CheckoutQuoteError, checkout_quote


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'audit-fixes.db'))
    async with engine.begin() as connection:
        await connection.run_sync(m.Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(m.User(id=1, tg_id=123, referral_code='AUDIT'))
        await session.commit()
        yield session, factory
    await engine.dispose()


def xlsx(rows):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


async def _client(repo, routers):
    app = FastAPI()
    for router, prefix in routers:
        app.include_router(router, prefix=prefix)
    app.dependency_overrides[get_repo] = lambda: repo
    return app


# ------------------------------------------------------- A08 parent visibility

@pytest.mark.asyncio
async def test_inactive_parent_hides_product_everywhere_without_rewriting_its_flag(db):
    session, _ = db
    repo = SqlRepository(session)
    session.add(m.Category(id=1, name='Hidden', is_active=False))
    session.add(m.Category(id=2, name='Visible', is_active=True))
    session.add(m.Subcategory(id=1, category_id=2, name='Hidden sub', is_active=False))
    session.add(m.Product(id=1, category_id=1, name='Hidden parent', sku='AUD-001', price=100, stock=10, is_active=True))
    session.add(m.Product(id=2, subcategory_id=1, name='Hidden sub product', sku='AUD-002', price=100, stock=10, is_active=True))
    session.add(m.Product(id=3, category_id=2, name='Visible', sku='AUD-003', price=100, stock=10, is_active=True))
    session.add(m.Product(id=4, category_id=2, name='Individually hidden', sku='AUD-004', price=100, stock=10, is_active=False))
    await session.commit()
    assert [p.id for p in await repo.list_products(only_active=True)] == [3]
    assert {p.id for p in await repo.list_products(inventory='hidden')} == {1, 2, 4}
    hidden = await repo.get_product(1)
    assert hidden.is_active and not hidden.is_published  # individual state kept
    assert await repo.change_cart_qty_atomic(1, 2, 1) is None
    # A line saved before the group was hidden cannot be bought.
    session.add(m.CartItem(user_id=1, product_id=1, qty=1))
    await session.commit()
    with pytest.raises(CheckoutQuoteError, match='недоступний'):
        await checkout_quote(repo, await repo.get_user(1))
    # Re-enabling the group publishes only individually active products.
    await repo.update_category(1, {'name': 'Hidden', 'is_active': True})
    session.add(m.Product(id=5, category_id=1, name='Own flag off', sku='AUD-005', price=100, stock=1, is_active=False))
    await session.commit()
    assert sorted(p.id for p in await repo.list_products(only_active=True)) == [1, 3]


# ------------------------------------------------------------ XLSX parsing

def test_parser_rejects_fractional_invalid_and_nonfinite_values_per_row():
    rows = parse_salesdrive_xlsx(xlsx([
        ['Товар', 'Залишок', 'Ціна'],
        ['Fraction', 1.9, 100],
        ['Valid', 2, '99,50'],
        ['Invalid stock', 'oops', 100],
        ['NaN price', 1, 'NaN'],
        ['Infinite', 1, 'inf'],
        ['Negative', -1, 10],
        ['Whole float', 3.0, 10],
    ]))
    by_name = {row['name']: row for row in rows}
    assert len(rows) == 7
    assert 'error' in by_name['Fraction'] and 'stock' not in by_name['Fraction']
    assert by_name['Valid']['stock'] == 2 and by_name['Valid']['current_price'] == Decimal('99.50')
    for name in ('Invalid stock', 'NaN price', 'Infinite', 'Negative'):
        assert by_name[name].get('error'), name
    assert by_name['Whole float']['stock'] == 3
    assert by_name['Fraction']['row'] == 2 and by_name['Whole float']['row'] == 8


# ------------------------------------------------------- import replay (A02)

@pytest.mark.asyncio
async def test_repeated_import_does_not_overwrite_stock_sold_in_between(db):
    session, _ = db
    repo = SqlRepository(session)
    session.add(m.Product(id=1, name='Aroma', sku='AUD-001', price=100, stock=10, is_active=True))
    await session.commit()
    app = await _client(repo, [(catalog.router, '/api/catalog')])
    who = Principal('root', 'root', Role.SYSADMIN, 0)
    app.dependency_overrides[require_staff] = lambda: who
    body = xlsx([['SKU', 'Товар', 'Категорія', 'Субкатегорія', 'Ціна', 'Залишок'],
                 ['AUD-001', 'Aroma', '', '', 100, 10], ['AUD-BAD', 'Broken', '', '', 100, 1.5]])
    files = {'file': ('audit.xlsx', body, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://dashboard.test') as http:
        first = await http.post('/api/catalog/product-transfer/import', files=files)
        assert first.status_code == 200, first.text
        assert first.json()['replayed'] is False and first.json()['updated'] == 1
        assert [e['row'] for e in first.json()['errors']] == [3]
        await repo.update_product(1, {'stock': 9})  # a sale after the import
        retry = await http.post('/api/catalog/product-transfer/import', files=files)
        assert retry.status_code == 200 and retry.json()['replayed'] is True
        assert (await repo.get_product(1)).stock == 9
        forced = await http.post('/api/catalog/product-transfer/import', files=files, data={'force': 'true'})
        assert forced.status_code == 200 and forced.json()['replayed'] is False
    assert (await repo.get_product(1)).stock == 10
