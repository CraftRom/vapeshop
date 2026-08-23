from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.auth import require_staff
from api.schemas import SeriesPoint, StatsOut, TopProduct
from shop.repo.base import Repository
from shop.repo.factory import get_repo

router = APIRouter(dependencies=[Depends(require_staff)])


# days=0 — за весь час. Окремий прапорець замість магічного числа зробив би
# API незручним для фронтенду, де період вибирається одним селектом.
@router.get("/summary", response_model=StatsOut)
async def summary(days: int = Query(30, ge=0, le=3650), repo: Repository = Depends(get_repo)):
    return await repo.stats_summary(days)


@router.get("/by-operator")
async def by_operator(
    days: int = Query(30, ge=0, le=3650), repo: Repository = Depends(get_repo)
):
    """Виторг у розрізі операторів за період."""
    return await repo.stats_by_operator(days)


@router.get("/series", response_model=list[SeriesPoint])
async def series(days: int = Query(30, ge=7, le=365), repo: Repository = Depends(get_repo)):
    return await repo.stats_series(days)


@router.get("/top-products", response_model=list[TopProduct])
async def top_products(
    days: int = Query(30, ge=0, le=3650),
    limit: int = Query(10, le=50),
    repo: Repository = Depends(get_repo),
):
    return await repo.stats_top_products(days, limit)


@router.get("/status-breakdown")
async def status_breakdown(repo: Repository = Depends(get_repo)):
    breakdown = await repo.status_breakdown()
    return [{"status": status, "count": count} for status, count in breakdown.items()]
