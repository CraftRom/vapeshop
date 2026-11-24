"""Стан модулів (адміністратор) і приватна готовність релізу (системний адміністратор).

``/api/health`` лишається публічною liveness-перевіркою без деталей. Тут —
те, що відрізняє «процес API живий» від «магазин справді готовий»: поточна
збірка, ревізія БД проти коду, доступність БД і Redis, heartbeat виконавців.
Секрети, адреси й дані клієнтів не повертаються.
"""
from __future__ import annotations

import ast
import time
from pathlib import Path

from fastapi import APIRouter, Depends

from api.auth import Principal, require_admin, require_sysadmin
from shop.build import release
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services.module_status import module_report

router = APIRouter()
ALEMBIC_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def code_heads(directory: Path = ALEMBIC_VERSIONS) -> list[str]:
    """Alembic heads from the shipped revision files, without importing them."""
    known, parents = set(), set()
    for file in directory.glob("*.py"):
        for node in ast.parse(file.read_text()).body:
            if isinstance(node, ast.Assign):
                pairs = [(t.id, node.value) for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
                pairs = [(node.target.id, node.value)]
            else:
                continue
            for name, raw in pairs:
                if name not in {"revision", "down_revision"}:
                    continue
                value = ast.literal_eval(raw)
                if name == "revision":
                    known.add(value)
                elif value:
                    parents.update(value if isinstance(value, (tuple, list)) else [value])
    return sorted(known - parents)


async def _database() -> dict:
    from sqlalchemy import text
    from shop.db import SessionMaker
    started = time.monotonic()
    try:
        async with SessionMaker() as session:
            revisions = [row[0] for row in await session.execute(text("SELECT version_num FROM alembic_version"))]
        return {"ok": True, "revisions": sorted(revisions),
                "latency_ms": round((time.monotonic() - started) * 1000, 1)}
    except Exception as exc:
        return {"ok": False, "revisions": [], "error": type(exc).__name__}


async def _redis() -> dict:
    from shop.services.realtime import _redis_url
    url = _redis_url()
    if not url:
        return {"configured": False, "ok": None}
    try:
        import redis.asyncio as redis
        client = redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.8)
        try:
            return {"configured": True, "ok": bool(await client.ping())}
        finally:
            await client.aclose()
    except Exception as exc:
        return {"configured": True, "ok": False, "error": type(exc).__name__}


@router.get("/modules")
async def modules(_who: Principal = Depends(require_admin), repo: Repository = Depends(get_repo)):
    return await module_report(repo)


@router.get("/readiness")
async def readiness(_who: Principal = Depends(require_sysadmin), repo: Repository = Depends(get_repo)):
    heads = code_heads()
    database = await _database()
    redis = await _redis()
    report = await module_report(repo)
    migrations_current = database["ok"] and database["revisions"] == heads
    problems = []
    if not database["ok"]:
        problems.append("База даних недоступна")
    elif not migrations_current:
        problems.append("Ревізія БД не збігається з кодом: міграції не застосовані або код старший за БД")
    if redis["configured"] and not redis["ok"]:
        problems.append("Redis недоступний: живі оновлення панелі працюють лише в межах процесу")
    problems.extend(f"{m['title']}: {m['detail']}" for m in report["modules"] if m["status"] == "no_worker")
    current = release()
    # A worker that was not restarted after a deploy still runs the old code.
    for worker in report["workers"]:
        if worker["running"] and worker.get("build") and worker["build"] != current["id"]:
            problems.append(f"{worker['title']} працює на іншій збірці ({worker['build']}); перезапустіть його")
    return {"build": current["id"], "release": current, "ready": not problems, "problems": problems,
            "migrations": {"code_heads": heads, "database": database["revisions"], "current": migrations_current},
            "database": {k: v for k, v in database.items() if k != "revisions"},
            "redis": redis, **report}
