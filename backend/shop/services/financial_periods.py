"""Saved reports, independent of subsequent CRM / spend / attribution changes."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.exc import IntegrityError, DBAPIError

from shop import models as m
from shop.repo.sql import SqlRepository, _aware
from shop.services import analytics
from shop.services.shop_settings import get_shop_settings

SCHEMA_VERSION = 1

def digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def metadata(row):
    return {"month": row.month, "timezone": row.timezone, "closed_at": _aware(row.closed_at),
            "closed_by": row.closed_by, "schema_version": row.schema_version,
            "checksum": row.checksum}

def saved_report(row):
    if row.schema_version != SCHEMA_VERSION or not hmac.compare_digest(digest(row.payload), row.checksum):
        raise HTTPException(409, "Збережений звіт не пройшов перевірку цілісності. Зверніться до адміністратора")
    return {**row.payload, "snapshot": metadata(row)}

async def close_month(bind, month, login, build_report):
    # Authentication uses its own session. Start isolation before any report
    # SELECT: every widget must describe the same database snapshot.
    maker = async_sessionmaker(bind, expire_on_commit=False)
    async with maker() as session:
        if bind.dialect.name == 'postgresql':
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        elif bind.dialect.name == 'sqlite':
            await session.execute(text('BEGIN'))
        existing = await session.get(m.FinancialPeriod, month)
        if existing:
            return saved_report(existing)
        repo = SqlRepository(session)
        shop = await get_shop_settings(repo)
        now = datetime.now(timezone.utc)
        start = analytics.month_start(month, shop.tz)
        if start >= now.astimezone(shop.tz) or analytics.next_month(start) > now.astimezone(shop.tz):
            raise HTTPException(422, "Можна зафіксувати лише завершений календарний місяць")
        w = analytics.window(shop.tz, month=month, compare='none', now=now)
        report = await build_report(w=w, granularity='day', repo=repo)
        # Exact money is stored as decimal strings, without binary rounding.
        payload = jsonable_encoder(report, custom_encoder={Decimal: str})
        row = m.FinancialPeriod(month=month, timezone=str(shop.tz), closed_at=now,
            closed_by=login, schema_version=SCHEMA_VERSION, checksum=digest(payload), payload=payload)
        session.add(row)
        try:
            await session.commit()
        except IntegrityError:
            # Two administrators or a retry can close the same month only once.
            await session.rollback()
            row = await session.get(m.FinancialPeriod, month)
            if row is None:
                raise
        except DBAPIError as exc:
            await session.rollback()
            if getattr(exc.orig, 'sqlstate', None) == '40001' or 'database is locked' in str(exc.orig).lower():
                raise HTTPException(409, "Звіт зараз фіксує інший запит. Оновіть список звітів і повторіть") from exc
            raise
        return saved_report(row)

async def list_months(session):
    # Do not fetch large payloads for the selector.
    fields = (m.FinancialPeriod.month, m.FinancialPeriod.timezone, m.FinancialPeriod.closed_at,
              m.FinancialPeriod.closed_by, m.FinancialPeriod.schema_version, m.FinancialPeriod.checksum)
    return [{**dict(row._mapping), "closed_at": _aware(row.closed_at)} for row in (await session.execute(select(*fields)
            .order_by(m.FinancialPeriod.month.desc()))).all()]
