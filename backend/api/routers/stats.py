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
        "orders_new": await repo.count_orders(OrderStatus.NEW),
        "support_unread": await repo.support_unread_count(),
    }


@router.get("/summary", response_model=StatsOut)
async def summary(
    days: int = Query(30, ge=0, le=3650),
    period: str | None = Query(None),
    repo: Repository = Depends(get_repo),
):
    window = await _stats_window(repo, period, days)
    return await repo.stats_summary(
        days, since=window["since"], until=window["until"]
    )


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
    """Порівняння й зрізи фактичних продажів: CRM-статус «Продаж»."""
    window = await _stats_window(repo, period, days)
    return await repo.stats_insights(
        days,
        since=window["since"],
        until=window["until"],
        previous_since=window["previous_since"],
        tz=window["tz"],
    )
