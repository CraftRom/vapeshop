"""Розсилка порціями.

Один код на обидва сценарії:
  • власний сервер — фонове завдання крутить порції поспіль до кінця;
  • планувальник (`python -m scheduler`) бере розсилки, чий час настав,
    і докручує їх тим самим кодом.

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

RATE_PER_SECOND = 25       # запасне значення, якщо налаштування недоступні
CONCURRENCY = 8            # паралельні відправки в межах порції
# Telegram пропускає близько 30 повідомлень на секунду на бота. Вище цієї
# межі починаються 429 з Retry-After, і сумарно розсилка йде повільніше,
# ніж якби ми з самого початку трималися нижче.
MAX_RATE_PER_SECOND = 30


async def send_chunk(repo: Repository, broadcast: Broadcast, size: int) -> tuple[int, bool]:
    """Надсилає до `size` повідомлень. Повертає (оброблено, чи завершено)."""
    recipients = await repo.segment_recipients(broadcast.segment or {}, broadcast.cursor_id, size)

    if not recipients:
        await repo.update_broadcast(broadcast.id, {
            "status": BroadcastStatus.SENT,
            "finished_at": datetime.now(timezone.utc),
        })
        return 0, True

    # Темп береться з налаштувань магазину, а не з константи: у різних
    # ботів різні ліміти, і підбирати їх редеплоєм — надто дорого.
    from shop.services.shop_settings import get_shop_settings

    shop = await get_shop_settings(repo)
    rate = min(max(int(shop.broadcast_rate_per_second or RATE_PER_SECOND), 1), MAX_RATE_PER_SECOND)

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
    for start in range(0, len(recipients), rate):
        batch = recipients[start:start + rate]
        outcomes = await asyncio.gather(*(deliver(tg_id) for _, tg_id in batch))
        sent += sum(outcomes)
        failed += len(outcomes) - sum(outcomes)
        if start + rate < len(recipients):
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
