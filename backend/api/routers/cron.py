"""Ендпоінти для планувальника.

Захищені окремим секретом, а не JWT: їх смикає машина, а не людина.
Працюють і з Vercel Cron, і з будь-яким зовнішнім планувальником.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status

from shop.config import settings
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services import broadcast as broadcast_service

router = APIRouter()
log = logging.getLogger("cron")

# Vercel Hobby дає 10 с на функцію, Pro — 60 с. При 25 msg/s тримаємо запас
# на холодний старт і мережу.
CHUNK = 100


async def require_cron_secret(authorization: str = Header(default="")) -> None:
    if not settings.cron_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "CRON_SECRET не налаштовано — ендпоінт вимкнено"
        )
    if authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невірний секрет планувальника")


@router.get("/broadcast-tick", dependencies=[Depends(require_cron_secret)])
async def broadcast_tick(repo: Repository = Depends(get_repo)):
    """Відпрацьовує одну порцію найстарішої активної розсилки."""
    broadcast = await repo.next_pending_broadcast()
    if not broadcast:
        return {"status": "idle", "message": "Активних розсилок немає"}

    processed, finished = await broadcast_service.send_chunk(repo, broadcast, CHUNK)
    log.info("Тік розсилки %s: оброблено %s, завершено=%s", broadcast.id, processed, finished)
    return {
        "status": "finished" if finished else "in_progress",
        "broadcast_id": broadcast.id,
        "processed": processed,
        "sent_total": broadcast.sent_count,
        "failed_total": broadcast.failed_count,
    }
