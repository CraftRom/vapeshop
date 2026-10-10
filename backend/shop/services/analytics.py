"""Calendar reporting and first-party acquisition analytics.

Amounts are UAH; finance follows the existing CRM sale/payment rules. Sources
are attribution hints supplied by the client, never authorization data.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, func, and_, or_
from sqlalchemy.exc import IntegrityError

from shop import models as m
from shop.repo.sql import stats_finance_values, _stats_payment_method, _aware

UTC = timezone.utc
from shop.services.attribution import clean_attribution, order_attribution


def month_start(value: str, tz) -> datetime:
    try:
        if not re.fullmatch(r"\d{4}-\d{2}", value):
            raise ValueError()
        year, month = map(int, value.split("-"))
        if year < 1970:
            raise ValueError()
        return datetime(year, month, 1, tzinfo=tz)
    except (ValueError, TypeError):
        raise HTTPException(422, "Місяць має бути у форматі YYYY-MM")


def next_month(start: datetime) -> datetime:
    return start.replace(year=start.year + (start.month == 12), month=start.month % 12 + 1, day=1)


def window(tz, *, period="month", month=None, date_from=None, date_to=None,
           compare="previous", compare_month=None, now=None, earliest=None):
    now = _aware(now or datetime.now(UTC)).astimezone(tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if month:
        start = month_start(month, tz)
        end = min(next_month(start), now)
    elif period == "custom":
        try:
            start = datetime.combine(date.fromisoformat(date_from), time.min, tz)
            end = datetime.combine(date.fromisoformat(date_to) + timedelta(days=1), time.min, tz)
        except (ValueError, TypeError, OverflowError):
            raise HTTPException(422, "Вкажіть коректні початкову й кінцеву дати")
        end = min(end, now)
    elif period == "today":
        start, end = midnight, now
    elif period in {"7d", "90d"}:
        start, end = midnight - timedelta(days=int(period[:-1]) - 1), now
    elif period == "month":
        start, end = midnight.replace(day=1), now
    elif period == "all":
        start, end = _aware(earliest).astimezone(tz) if earliest else midnight, now
    else:
        raise HTTPException(422, "Невідомий період статистики")
    if start >= end or start.year < 1970:
        raise HTTPException(422, "Початок періоду має бути раніше кінця й не в майбутньому")
    if compare not in {"previous", "month", "none"}:
        raise HTTPException(422, "Невідомий режим порівняння")
    prev_start = prev_end = None
    if compare == "month":
        if not compare_month:
            raise HTTPException(422, "Оберіть місяць для порівняння")
        prev_start = month_start(compare_month, tz)
        prev_end = min(next_month(prev_start), now)
        if prev_start >= prev_end:
            raise HTTPException(422, "Місяць порівняння ще не почався")
    elif compare == "previous" and period != "all":
        if month or period == "month":
            prev_start = (start.replace(day=1) - timedelta(days=1)).replace(day=1)
            # Completed months compare in full. MTD compares the same elapsed
            # calendar portion, clamped for shorter months (incl. leap years).
            prev_end = min(next_month(prev_start), prev_start + (end - start)) if end == now else next_month(prev_start)
        else:
            prev_start, prev_end = start - (end - start), start
    return {
        "since": start.astimezone(UTC), "until": end.astimezone(UTC), "tz": tz,
        "previous_since": prev_start.astimezone(UTC) if prev_start else None,
        "previous_until": prev_end.astimezone(UTC) if prev_end else None,
        "partial": end == now,
    }


async def earliest_date(session):
    values = []
    for model, field in ((m.Order, m.Order.created_at), (m.AnalyticsSession, m.AnalyticsSession.started_at),
                         (m.MarketingSpend, m.MarketingSpend.day)):
        value = await session.scalar(select(func.min(field)).select_from(model))
        if value:
            values.append(datetime.combine(value, time.min, UTC) if isinstance(value, date) and not isinstance(value, datetime) else _aware(value))
    return min(values) if values else None


async def months(session, tz):
    earliest = await earliest_date(session)
    now = datetime.now(UTC).astimezone(tz)
    first = earliest.astimezone(tz).replace(day=1, hour=0, minute=0, second=0, microsecond=0) if earliest else now.replace(day=1)
    rows = []
    while first <= now:
        rows.append(first.strftime("%Y-%m"))
        first = next_month(first)
    return list(reversed(rows))


async def record_session(session, user_id, session_id, attribution):
    # Unique (user, session) makes retries idempotent; timestamp is server-side.
    row = await session.scalar(select(m.AnalyticsSession).where(
        m.AnalyticsSession.user_id == user_id, m.AnalyticsSession.session_id == session_id))
    if row:
        return
    try:
        session.add(m.AnalyticsSession(user_id=user_id, session_id=session_id,
                                     attribution=clean_attribution(attribution), started_at=datetime.now(UTC)))
        await session.commit()
    except IntegrityError:
        await session.rollback()  # Concurrent retry of the same visit.


async def checkout_attribution(session, user_id, session_id, attribution):
    # A missing analytics POST must never prevent checkout. Link only a visit
    # owned by this authenticated user; don't insert telemetry in checkout.
    row = await session.scalar(select(m.AnalyticsSession).where(
        m.AnalyticsSession.user_id == user_id, m.AnalyticsSession.session_id == session_id)) if session_id else None
    result = clean_attribution(attribution)
    if row:
        result["session_id"] = row.session_id
    return result


def ratio(numerator, denominator, multiplier=1):
    return round(float(numerator / denominator) * multiplier, 2) if denominator else None


def delta(value, previous):
    if value is None or previous is None or previous == 0:
        return None
    return round((float(value) / float(previous) - 1) * 100, 2)


def finance(row):
    return stats_finance_values(row.business_state, row.status, _stats_payment_method(row, row.crm_snapshot or {}), row.total, row.crm_snapshot)


def slot():
    return {"sales": Decimal(0), "ad_sales": Decimal(0), "revenue": Decimal(0), "expected": Decimal(0), "spend": Decimal(0),
            "orders": 0, "new_customers": 0, "sessions": 0, "converted_sessions": 0, "checkouts": 0}


def finish(row):
    return {**row, "avg_check": ratio(row["sales"], row["orders"]),
            "cac": ratio(row["spend"], row["new_customers"]) if row["spend"] > 0 else None,
            "roas": ratio(row["ad_sales"], row["spend"]),
            "conversion": ratio(row["converted_sessions"], row["sessions"], 100)}


async def aggregate(session, w, granularity="day"):
    since, until, tz = w["since"], w["until"], w["tz"]
    event = func.coalesce(m.Order.business_state_at, m.Order.created_at)
    # Deterministic first purchase, including equal timestamps: one new
    # customer belongs to exactly one source/order.
    ranked = select(m.Order.id.label("order_id"), func.row_number().over(
        partition_by=m.Order.user_id, order_by=(event, m.Order.id)).label("rank")).where(m.Order.business_state == "sale").subquery()
    first_ids = set(await session.scalars(select(ranked.c.order_id).join(
        m.Order, m.Order.id == ranked.c.order_id).where(ranked.c.rank == 1, event >= since, event < until)))
    sales = (await session.execute(select(
        m.Order.id, m.Order.user_id, m.Order.business_state_at, m.Order.created_at,
        m.Order.business_state, m.Order.status, m.Order.total, m.Order.payment_method,
        m.Order.crm_snapshot, m.Order.attribution,
    ).where(m.Order.business_state == "sale", event >= since, event < until))).all()
    created = (await session.execute(select(m.Order.id, m.Order.created_at, m.Order.attribution, m.Order.crm_snapshot).where(
        m.Order.created_at >= since, m.Order.created_at < until))).all()
    visits = (await session.execute(select(m.AnalyticsSession.user_id, m.AnalyticsSession.session_id,
        m.AnalyticsSession.started_at, m.AnalyticsSession.attribution).where(
        m.AnalyticsSession.started_at >= since, m.AnalyticsSession.started_at < until))).all()
    # Conversion is a visit cohort: any submitted order created after this
    # visit and before report end; cancellation still counts as checkout.
    converted = set((await session.execute(select(m.Order.user_id, m.AnalyticsSession.session_id).join(
        m.AnalyticsSession, and_(m.Order.user_id == m.AnalyticsSession.user_id,
          m.Order.attribution["session_id"].as_string() == m.AnalyticsSession.session_id)).where(
        m.AnalyticsSession.started_at >= since, m.AnalyticsSession.started_at < until,
        m.Order.created_at >= m.AnalyticsSession.started_at, m.Order.created_at < until))).all())
    local_start, local_end = since.astimezone(tz), (until - timedelta(microseconds=1)).astimezone(tz)
    spend_rows = (await session.execute(select(m.MarketingSpend).where(
        m.MarketingSpend.day >= local_start.date(), m.MarketingSpend.day <= local_end.date()))).scalars().all()
    funded = {(r.source, r.campaign) for r in spend_rows if r.amount > 0}
    funded_channels = {source for source, campaign in funded if not campaign}
    total, sources, campaigns, buckets = slot(), {}, {}, {}
    cursor = local_start.date()
    while cursor <= local_end.date():
        key = cursor.isoformat() if granularity == "day" else cursor.strftime("%Y-%m")
        buckets.setdefault(key, slot())
        cursor = cursor + timedelta(days=1) if granularity == "day" else (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)

    def targets(attribution, when):
        a = clean_attribution(attribution)
        src = sources.setdefault(a["source"], slot())
        campaign = campaigns.setdefault((a["source"], a["campaign"]), slot())
        when = _aware(when).astimezone(tz) if isinstance(when, datetime) else when
        key = when.strftime("%Y-%m-%d" if granularity == "day" else "%Y-%m")
        return (total, src, campaign, buckets.setdefault(key, slot()))

    for row in sales:
        fin = finance(row)
        attribution = order_attribution(row.attribution, row.crm_snapshot)
        paid = attribution["source"] in funded_channels or (attribution["source"], attribution["campaign"]) in funded
        for out in targets(attribution, row.business_state_at or row.created_at):
            for key in ("revenue", "expected"):
                out[key] += fin["received" if key == "revenue" else key]
            out["sales"] += fin["total"]
            if paid:
                out["ad_sales"] += fin["total"]
            out["orders"] += 1
            out["new_customers"] += int(row.id in first_ids)
    for row in visits:
        for out in targets(row.attribution, row.started_at):
            out["sessions"] += 1
            out["converted_sessions"] += int((row.user_id, row.session_id) in converted)
    for row in created:
        # The total and channel checkout count use order creation, not sale.
        for out in targets(order_attribution(row.attribution, row.crm_snapshot), row.created_at):
            out["checkouts"] += 1
    for row in spend_rows:
        for out in targets({"source": row.source, "campaign": row.campaign}, row.day):
            out["spend"] += row.amount
    metrics = finish(total)
    return {
        "metrics": metrics,
        "sources": [{"source": key, **finish(value)} for key, value in sorted(sources.items(), key=lambda x: -x[1]["sales"])],
        "campaigns": [{"source": key[0], "campaign": key[1], **finish(value)} for key, value in sorted(campaigns.items(), key=lambda x: -x[1]["sales"])],
        "series": [{"date": key, **finish(value)} for key, value in sorted(buckets.items())],
        "attribution_coverage": ratio(sum(1 for r in sales if order_attribution(r.attribution, r.crm_snapshot)["source"] != "unknown"), len(sales), 100),
    }


async def order_sources(session, w, source=None, offset=0, limit=25):
    clause = [m.Order.created_at >= w["since"], m.Order.created_at < w["until"]]
    if source:
        field = m.Order.attribution["source"].as_string()
        crm_source = m.Order.crm_snapshot["utm"]["source"].as_string()
        missing = or_(field == "unknown", field.is_(None), field == "")
        # Resolve distinct CRM labels using the same normalization as display,
        # instead of database-specific regexes or loading every order.
        raw_sources = list(await session.scalars(select(crm_source).where(*clause, missing).distinct()))
        matching = [value for value in raw_sources if clean_attribution({"source": value})["source"] == source and value]
        if source == "unknown":
            clause.append(and_(missing, or_(crm_source.is_(None), crm_source == "", crm_source.in_(matching))))
        else:
            clause.append(or_(field == source, and_(missing, crm_source.in_(matching))))
    count = await session.scalar(select(func.count(m.Order.id)).where(*clause))
    rows = (await session.execute(select(m.Order.id, m.Order.created_at, m.Order.contact_name,
        m.Order.business_state, m.Order.status, m.Order.total, m.Order.payment_method,
        m.Order.crm_snapshot, m.Order.attribution).where(*clause)
        .order_by(m.Order.created_at.desc(), m.Order.id.desc()).offset(offset).limit(limit))).all()
    return {"total": count, "items": [{"id": r.id, "created_at": _aware(r.created_at).isoformat(),
        "contact_name": r.contact_name, "total": r.total, "business_state": r.business_state,
        "sales": finance(r)["total"], "revenue": finance(r)["received"],
        "attribution": order_attribution(r.attribution, r.crm_snapshot)} for r in rows]}


def attributed_button_url(target, params, *, campaign=""):
    """Preserve tagged promo traffic across the Telegram launch boundary.

    Existing chat/referral deep links keep their destination. Named Mini App
    payloads use Telegram's allowed base64url alphabet, bounded to 512 chars.
    """
    import base64
    import json
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    from shop.links import NAMED_MINIAPP_URL
    parts = urlsplit(target)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    a = clean_attribution({k: params.get('utm_' + k, '') for k in ('source', 'medium', 'campaign', 'content', 'term')})
    if a['source'] == 'unknown':
        a.update(source='promo', medium='landing', campaign=campaign[:160])
    named = urlsplit(NAMED_MINIAPP_URL)
    if parts.hostname == named.hostname and parts.path.rstrip('/') == named.path.rstrip('/'):
        if not query.get('startapp'):
            # Shorten long optional fields until the launch payload fits.
            def encode():
                return 'acq_' + base64.urlsafe_b64encode(json.dumps(a, separators=(',', ':'), ensure_ascii=True).encode()).decode().rstrip('=')
            payload = encode()
            for key in ('term', 'content', 'medium', 'campaign'):
                if len(payload) <= 512:
                    break
                a[key] = ''
                payload = encode()
            query['startapp'] = payload
    elif parts.hostname not in {'t.me', 'telegram.me'}:
        for key, value in a.items():
            if value:
                query.setdefault('utm_' + key, value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
