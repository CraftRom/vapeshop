"""Розсилка порціями.

Один код на обидва сценарії:
  • власний сервер — фонове завдання крутить порції поспіль до кінця;
  • serverless — планувальник смикає /api/cron/broadcast-tick, і кожен виклик
    відпрацьовує одну порцію в межах ліміту часу функції.

Курсор зберігається в самій розсилці, тому процес можна обірвати будь-коли
й продовжити з того ж місця.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from shop.entities import Broadcast, BroadcastStatus
from shop.repo.base import Repository
from shop.telegram import send_broadcast_message

log = logging.getLogger("broadcast")

RATE_PER_SECOND = 25       # Telegram пропускає ~30/с, тримаємось нижче межі
CONCURRENCY = 8            # паралельні відправки в межах порції


async def send_chunk(repo: Repository, broadcast: Broadcast, size: int) -> tuple[int, bool]:
    """Надсилає до `size` повідомлень. Повертає (оброблено, чи завершено)."""
    recipients = await repo.segment_recipients(broadcast.segment or {}, broadcast.cursor_id, size)

    if not recipients:
        await repo.update_broadcast(broadcast.id, {
            "status": BroadcastStatus.SENT,
            "finished_at": datetime.now(timezone.utc),
        })
        return 0, True

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def deliver(tg_id: int) -> bool:
        async with semaphore:
            ok, error = await send_broadcast_message(
                tg_id, broadcast.text, broadcast.photo_url,
                broadcast.button_text, broadcast.button_url,
            )
            if not ok:
                log.info("Не доставлено %s: %s", tg_id, error)
            return ok

    sent = failed = 0
    # Ріжемо порцію на секундні пачки: паралелимо всередині, але не перевищуємо ліміт
    for start in range(0, len(recipients), RATE_PER_SECOND):
        batch = recipients[start:start + RATE_PER_SECOND]
        outcomes = await asyncio.gather(*(deliver(tg_id) for _, tg_id in batch))
        sent += sum(outcomes)
        failed += len(outcomes) - sum(outcomes)
        if start + RATE_PER_SECOND < len(recipients):
            await asyncio.sleep(1)

    cursor = recipients[-1][0]
    await repo.update_broadcast(broadcast.id, {
        "cursor_id": cursor,
        "sent_count": broadcast.sent_count + sent,
        "failed_count": broadcast.failed_count + failed,
    })
    broadcast.cursor_id = cursor
    broadcast.sent_count += sent
    broadcast.failed_count += failed

    finished = len(recipients) < size
    if finished:
        await repo.update_broadcast(broadcast.id, {
            "status": BroadcastStatus.SENT,
            "finished_at": datetime.now(timezone.utc),
        })

    return len(recipients), finished


async def run_to_completion(broadcast_id: int, chunk: int = 100) -> None:
    """Режим власного сервера: крутимо порції, доки не закінчаться отримувачі."""
    from shop.repo.factory import open_repo

    while True:
        async with open_repo() as repo:
            broadcast = await repo.get_broadcast(broadcast_id)
            if not broadcast or broadcast.status != BroadcastStatus.SENDING:
                return
            _, finished = await send_chunk(repo, broadcast, chunk)
            if finished:
                log.info(
                    "Розсилка %s завершена: %s доставлено, %s помилок",
                    broadcast_id, broadcast.sent_count, broadcast.failed_count,
                )
                return
