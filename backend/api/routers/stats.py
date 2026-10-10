from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from api.auth import require_staff
from api.schemas import SeriesPoint, StatsOut, TopProduct
from shop.entities import OrderStatus
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services.shop_settings import get_shop_settings

router = APIRouter(dependencies=[Depends(require_staff)])

_PERIODS = {"today", "7d", "month", "90d", "all"}


async def _display_new_count(repo: Repository) -> int:
    """Той самий «Новий», який бачить таблиця замовлень.

    CRM-linked заявки рахуються за SalesDrive statusId, legacy — за local
    workflow. Це прибирає розбіжність між sidebar/overview і Orders page.
    """
    from shop.services import salesdrive

    shop = await get_shop_settings(repo)
    new_status_id = salesdrive.mapping(shop.salesdrive_status_map).get(OrderStatus.NEW.value)
    return await repo.count_display_new_orders(new_status_id)


async def _stats_window(repo: Repository, period: str | None, days: int) -> dict:
    """Календарні межі статистики у часовій зоні магазину.

    Раніше «Сьогодні» означало останні 24 години, а «Цей місяць» — N діб
    назад від поточної хвилини. Через це замовлення попереднього вечора
    потрапляли в сьогоднішні цифри, а перший день місяця міг обрізатися.
    UI тепер передає явний period; days лишається для старих клієнтів API.
    """
    shop = await get_shop_settings(repo)
    tz = shop.tz
    now_utc = datetime.now(timezone.utc)
    local_now = now_utc.astimezone(tz)

    if period and period not in _PERIODS:
        period = None

    if period == "today":
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "7d":
        local_start = (local_now - timedelta(days=6)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "month":
        local_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "90d":
        local_start = (local_now - timedelta(days=89)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "all":
        return {
            "since": datetime.fromtimestamp(0, tz=timezone.utc),
            "until": now_utc,
            "previous_since": None,
            "tz": tz,
            "period": "all",
        }
    else:
        # Backward compatibility: direct API callers still get rolling N days.
        if days <= 0:
            return {
                "since": datetime.fromtimestamp(0, tz=timezone.utc),
                "until": now_utc,
                "previous_since": None,
                "tz": tz,
                "period": "all",
            }
        local_start = local_now - timedelta(days=days)

    since = local_start.astimezone(timezone.utc)
    duration = now_utc - since
    return {
        "since": since,
        "until": now_utc,
        "previous_since": since - duration,
        "tz": tz,
        "period": period or f"{days}d",
    }


@router.get("/badges")
async def badges(repo: Repository = Depends(get_repo)):
    """Легкі лічильники для sidebar панелі."""
    return {
        "orders_new": await _display_new_count(repo),
        "support_unread": await repo.support_unread_count(),
    }


@router.get("/summary", response_model=StatsOut)
async def summary(
    days: int = Query(30, ge=0, le=3650),
    period: str | None = Query(None),
    repo: Repository = Depends(get_repo),
):
    window = await _stats_window(repo, period, days)
    result = await repo.stats_summary(
        days, since=window["since"], until=window["until"]
    )
    result.orders_new = await _display_new_count(repo)
    return result


@router.get("/by-operator")
async def by_operator(
    days: int = Query(30, ge=0, le=3650),
    period: str | None = Query(None),
    repo: Repository = Depends(get_repo),
):
    """Продажі CRM «Продаж» і отримані/очікувані кошти по менеджерах."""
    window = await _stats_window(repo, period, days)
    return await repo.stats_by_operator(
        days, since=window["since"], until=window["until"]
    )


@router.get("/series", response_model=list[SeriesPoint])
async def series(
    days: int = Query(30, ge=1, le=3650),
    period: str | None = Query(None),
    repo: Repository = Depends(get_repo),
):
    window = await _stats_window(repo, period, days)
    return await repo.stats_series(
        days,
        since=window["since"],
        until=window["until"],
        tz=window["tz"],
    )


@router.get("/top-products", response_model=list[TopProduct])
async def top_products(
    days: int = Query(30, ge=0, le=3650),
    period: str | None = Query(None),
    limit: int = Query(10, le=50),
    repo: Repository = Depends(get_repo),
):
    window = await _stats_window(repo, period, days)
    return await repo.stats_top_products(
        days, limit, since=window["since"], until=window["until"]
    )


@router.get("/status-breakdown")
async def status_breakdown(
    period: str | None = Query(None),
    days: int = Query(0, ge=0, le=3650),
    repo: Repository = Depends(get_repo),
):
    """Ті самі статуси, які бачить панель, у межах вибраного періоду."""
    if period is None and days == 0:
        since = until = None
    else:
        window = await _stats_window(repo, period, days)
        since, until = window["since"], window["until"]

    rows = await repo.display_status_breakdown(since=since, until=until)
    from shop.services import salesdrive
    from shop.services.shop_settings import get_shop_settings

    shop = await get_shop_settings(repo)
    try:
        names = {x["id"]: x["name"] for x in await salesdrive.status_options(shop)}
    except salesdrive.SalesDriveError:
        names = {}
    for row in rows:
        if row.get("source") == "crm" and names.get(str(row.get("status") or "")):
            row["name"] = names[str(row["status"])]
    return rows


@router.get("/insights")
async def insights(
    days: int = Query(30, ge=1, le=3650),
    period: str | None = Query(None),
    repo: Repository = Depends(get_repo),
):
    """Фінансові зрізи продажів; активність замовлень — за created_at."""
    window = await _stats_window(repo, period, days)
    return await repo.stats_insights(
        days,
        since=window["since"],
        until=window["until"],
        previous_since=window["previous_since"],
        tz=window["tz"],
    )


# The report endpoint keeps all widgets on the same explicit calendar window.
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field
from fastapi import HTTPException
from api.auth import Principal, require_admin
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from shop import models as m
from shop.services import analytics as analytics_service


async def report_window(
    period: str = "month", month: str | None = None,
    date_from: str | None = None, date_to: str | None = None,
    compare: str = "previous", compare_month: str | None = None,
    repo: Repository = Depends(get_repo),
):
    shop = await get_shop_settings(repo)
    return analytics_service.window(shop.tz, period=period, month=month,
        date_from=date_from, date_to=date_to, compare=compare, compare_month=compare_month,
        earliest=await analytics_service.earliest_date(repo.s) if period == "all" else None)


@router.get("/months")
async def available_months(repo: Repository = Depends(get_repo)):
    shop = await get_shop_settings(repo)
    return {"months": await analytics_service.months(repo.s, shop.tz), "timezone": str(shop.tz)}


@router.get("/report")
async def report(w: dict = Depends(report_window),
                 granularity: str = Query("day", pattern="^(day|month)$"),
                 repo: Repository = Depends(get_repo)):
    # Keep at most one point per month for multi-year reports.
    if (w["until"] - w["since"]).days > 730:
        granularity = "month"
    current = await analytics_service.aggregate(repo.s, w, granularity)
    previous = None
    if w["previous_since"]:
        previous = await analytics_service.aggregate(repo.s,
            {**w, "since": w["previous_since"], "until": w["previous_until"]}, granularity)
    args = {"since": w["since"], "until": w["until"]}
    summary_data = await repo.stats_summary(0, **args)
    summary_data.orders_new = await _display_new_count(repo)
    insights_data = await repo.stats_insights(0, **args, previous_since=None, tz=w["tz"])
    for key, metric in (("revenue", "revenue"), ("turnover", "sales"), ("avg_check", "avg_check")):
        insights_data[key]["change"] = analytics_service.delta(current["metrics"][metric], previous["metrics"][metric]) if previous else None
    return {
        "summary": summary_data, "insights": insights_data,
        "series": current["series"], "top": await repo.stats_top_products(0, 10, **args),
        "breakdown": await status_breakdown_for_window(repo, args),
        "operators": await repo.stats_by_operator(0, **args),
        "analytics": current, "previous": previous,
        "changes": {key: analytics_service.delta(value, previous["metrics"].get(key)) if previous else None
                    for key, value in current["metrics"].items()},
        "window": {"from": w["since"].isoformat(), "to": w["until"].isoformat(),
                   "previous_from": w["previous_since"].isoformat() if w["previous_since"] else None,
                   "previous_to": w["previous_until"].isoformat() if w["previous_until"] else None,
                   "partial": w["partial"], "timezone": str(w["tz"]), "granularity": granularity},
    }


async def status_breakdown_for_window(repo, args):
    rows = await repo.display_status_breakdown(**args)
    # Cached CRM names on orders avoid an external CRM call on every refresh.
    names = dict((await repo.s.execute(select(m.Order.crm_status_id, m.Order.crm_status_name)
                 .where(m.Order.crm_status_name.is_not(None)).distinct())).all())
    for row in rows:
        if row.get("source") == "crm":
            row["name"] = names.get(str(row.get("status"))) or row.get("name") or ""
    return rows


@router.get("/order-sources")
async def order_sources(w: dict = Depends(report_window),
                        source: str | None = Query(None, max_length=80),
                        offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
                        repo: Repository = Depends(get_repo)):
    return await analytics_service.order_sources(repo.s, w, source, offset, limit)


class SpendIn(BaseModel):
    day: date
    source: str = Field(..., min_length=1, max_length=80)
    campaign: str = Field("", max_length=160)
    amount: Decimal = Field(..., ge=0, le=Decimal("9999999999.99"), decimal_places=2)


@router.get("/spend")
async def list_spend(w: dict = Depends(report_window), repo: Repository = Depends(get_repo)):
    rows = await repo.s.scalars(select(m.MarketingSpend).where(
        m.MarketingSpend.day >= w["since"].astimezone(w["tz"]).date(),
        m.MarketingSpend.day <= (w["until"] - timedelta(microseconds=1)).astimezone(w["tz"]).date())
        .order_by(m.MarketingSpend.day.desc(), m.MarketingSpend.id.desc()))
    return [{"id": r.id, "day": r.day, "source": r.source, "campaign": r.campaign,
             "amount": r.amount, "updated_by": r.updated_by} for r in rows]


@router.put("/spend")
async def save_spend(data: SpendIn, repo: Repository = Depends(get_repo),
                     who: Principal = Depends(require_admin)):
    shop = await get_shop_settings(repo)
    if data.day > datetime.now(timezone.utc).astimezone(shop.tz).date() or data.day.year < 1970:
        raise HTTPException(422, "Витрати доступні лише за поточну або минулу дату")
    source = analytics_service.clean_attribution({"source": data.source})["source"]
    campaign = data.campaign.strip()
    row = await repo.s.scalar(select(m.MarketingSpend).where(m.MarketingSpend.day == data.day,
        m.MarketingSpend.source == source, m.MarketingSpend.campaign == campaign))
    if not row:
        row = m.MarketingSpend(day=data.day, source=source, campaign=campaign)
        repo.s.add(row)
    row.amount, row.updated_by, row.updated_at = data.amount, who.login, datetime.now(timezone.utc)
    try:
        await repo.s.commit()
    except IntegrityError:
        await repo.s.rollback()
        raise HTTPException(409, "Цей запис щойно змінено. Оновіть список і повторіть")
    return {"ok": True}


@router.delete("/spend/{spend_id}")
async def remove_spend(spend_id: int, repo: Repository = Depends(get_repo),
                       who: Principal = Depends(require_admin)):
    row = await repo.s.get(m.MarketingSpend, spend_id)
    if not row:
        raise HTTPException(404, "Запис витрат не знайдено")
    await repo.s.delete(row)
    await repo.s.commit()
    return {"ok": True}
