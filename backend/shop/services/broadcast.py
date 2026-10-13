"""Leased queue with durable recipient attempts and conservative retry policy."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from shop.entities import Broadcast
from shop.repo.base import Repository
from shop.repo.factory import open_repo
from shop.telegram import send_broadcast_once

log = logging.getLogger("broadcast")
RATE_PER_SECOND = 25
MAX_RATE_PER_SECOND = 30
CONCURRENCY = 8
LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 10
MAX_ATTEMPTS = 3


async def send_chunk(repo: Repository, broadcast: Broadcast, size: int) -> tuple[int, bool]:
    """Atomically claim before reading the current cursor, even for direct callers."""
    owner = uuid.uuid4().hex
    current = await repo.claim_broadcast(broadcast.id, owner, LEASE_SECONDS)
    if current is None:
        return 0, False
    lost = asyncio.Event()

    async def heartbeat():
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                async with open_repo() as lease_repo:
                    if not await lease_repo.heartbeat_broadcast(current.id, owner, LEASE_SECONDS):
                        lost.set()
                        return
            except Exception:
                lost.set()  # fail closed: no further network requests
                log.exception("Heartbeat розсилки %s не збережено", current.id)
                return

    task = asyncio.create_task(heartbeat())
    pending_at = []
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def deliver(user_id, tg_id):
        async with semaphore:
            if lost.is_set():
                return
            async with open_repo() as delivery_repo:
                attempt = await delivery_repo.begin_broadcast_delivery(current.id, owner, user_id, tg_id)
            if attempt["action"] == "lost":
                lost.set()
                return
            if attempt["action"] == "wait":
                pending_at.append(attempt["next_attempt_at"])
                return
            if attempt["action"] != "send":
                return
            result = await send_broadcast_once(tg_id, current.text, current.photo_url,
                                                current.button_text, current.button_url)
            status = result.status
            next_at = None
            if status == "retry":
                if attempt["attempts"] >= MAX_ATTEMPTS:
                    status = "failed"
                else:
                    next_at = datetime.now(timezone.utc) + timedelta(seconds=result.retry_after)
            async with open_repo() as delivery_repo:
                saved = await delivery_repo.finish_broadcast_delivery(
                    current.id, owner, user_id, status, result.error, next_at)
            if not saved:
                lost.set()
            elif next_at:
                pending_at.append(next_at)

    try:
        from shop.services.shop_settings import get_shop_settings
        shop = await get_shop_settings(repo)
        rate = min(max(int(shop.broadcast_rate_per_second or RATE_PER_SECOND), 1), MAX_RATE_PER_SECOND)
        size = max(1, min(int(size), 1000))
        recipients = await repo.segment_recipients(current.segment or {}, current.cursor_id, size)
        # End the read transaction before other sessions start short write transactions.
        # Repository reads do not commit; a no-op heartbeat commits and fences ownership.
        if not await repo.heartbeat_broadcast(current.id, owner, LEASE_SECONDS):
            return 0, False
        for start in range(0, len(recipients), rate):
            if lost.is_set():
                return 0, False
            began = time.monotonic()
            # Wait for every task, including after one fails: none may outlive release.
            outcomes = await asyncio.gather(*(deliver(uid, tg) for uid, tg in recipients[start:start + rate]),
                                            return_exceptions=True)
            exceptions = [x for x in outcomes if isinstance(x, BaseException)]
            if exceptions:
                raise exceptions[0]
            await asyncio.sleep(max(0, 1.0 - (time.monotonic() - began)))
        if lost.is_set():
            return 0, False
        if pending_at:
            await repo.release_broadcast(current.id, owner, next_attempt_at=min(pending_at))
            return 0, False  # cursor stays before retry recipients; journal skips terminal results
        finished = len(recipients) < size
        ok = await repo.release_broadcast(current.id, owner,
            cursor_id=recipients[-1][0] if recipients else current.cursor_id, finished=finished)
        if not ok:
            return 0, False
        refreshed = await repo.get_broadcast(current.id)
        broadcast.cursor_id = refreshed.cursor_id
        broadcast.sent_count = refreshed.sent_count
        broadcast.failed_count = refreshed.failed_count
        broadcast.unknown_count = refreshed.unknown_count
        broadcast.status = refreshed.status
        return len(recipients), finished
    except asyncio.CancelledError:
        # Leave lease and in-flight journal intact for restart recovery.
        raise
    except Exception:
        # Unknown in-flight attempts are recovered only AFTER the lease expires.
        # Keeping the lease also prevents a tight scheduler retry loop during outage.
        log.exception("Виконавець розсилки %s зупинився; очікує recovery", current.id)
        try:
            async with open_repo() as error_repo:
                await error_repo.release_broadcast(current.id, owner,
                    error="Збій виконавця; автоматичне відновлення після завершення оренди",
                    next_attempt_at=datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS))
        except Exception:
            log.exception("Не вдалося зберегти стан recovery розсилки %s", current.id)
        return 0, False
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def run_to_completion(broadcast_id: int, chunk: int = 100) -> bool:
    """Manual and scheduled jobs share the same durable claim/recovery path."""
    worked = False
    while True:
        async with open_repo() as repo:
            broadcast = await repo.get_broadcast(broadcast_id)
            if not broadcast:
                return worked
            count, finished = await send_chunk(repo, broadcast, chunk)
        worked |= count > 0 or finished
        if finished or count == 0:
            return worked
