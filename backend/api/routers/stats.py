from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.auth import require_admin
from api.schemas import SeriesPoint, StatsOut, TopProduct
from shop.repo.base import Repository
from shop.repo.factory import get_repo

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/summary", response_model=StatsOut)
async def summary(days: int = Query(30, ge=1, le=365), repo: Repository = Depends(get_repo)):
    return await repo.stats_summary(days)


@router.get("/series", response_model=list[SeriesPoint])
async def series(days: int = Query(30, ge=7, le=365), repo: Repository = Depends(get_repo)):
    return await repo.stats_series(days)


@router.get("/top-products", response_model=list[TopProduct])
async def top_products(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, le=50),
    repo: Repository = Depends(get_repo),
):
    return await repo.stats_top_products(days, limit)


@router.get("/status-breakdown")
async def status_breakdown(repo: Repository = Depends(get_repo)):
    breakdown = await repo.status_breakdown()
    return [{"status": status, "count": count} for status, count in breakdown.items()]
