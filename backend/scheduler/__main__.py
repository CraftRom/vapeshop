"""Цикл планувальника.

Один процес керує кількома незалежними фоновими контурами. Важливо, що
частота одного контуру більше не визначає частоту всіх інших: резервне
читання SalesDrive може бути рідким через API-квоти, але це не повинно
затримувати розсилки, retry CRM-записів чи прибирання.

``SCHEDULER_INTERVAL_SECONDS`` тепер задає лише частоту пробудження процесу.
Для сумісності зі старими production env (де стояло 3600) tick обмежено
15 секундами; кожне важче завдання має власний monotonic gate нижче.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import signal

from shop.config import settings
from shop.logging_setup import setup as setup_logging
from scheduler.tasks import (
    refresh_salesdrive_orders, run_backup_if_due, run_due_broadcasts,
    run_housekeeping, sync_salesdrive,
)

setup_logging("scheduler")
log = logging.getLogger("scheduler")

# Старі production env можуть містити як SCHEDULER_INTERVAL_SECONDS=3600,
# так і SALESDRIVE_BACKGROUND_REFRESH_SECONDS=60. Перший більше не має права
# робити всі фонові процеси годинними, а другий — витрачати CRM read quota.
SALESDRIVE_BACKGROUND_READ_SECONDS = max(
    180, int(settings.salesdrive_background_refresh_seconds)
)
TICK_SECONDS = max(5, min(int(settings.scheduler_interval_seconds), 15))

# Власні cadence-и. Усі значення — нижні межі: задача може фактично
# запускатися трохи пізніше (до одного TICK_SECONDS), але ніколи частіше.
BROADCAST_CHECK_SECONDS = 15
SALESDRIVE_WRITE_RETRY_SECONDS = 30
BACKUP_CHECK_SECONDS = 300
HOUSEKEEPING_SECONDS = 24 * 3600


def _due(state: dict, key: str, interval: float, *, now: float | None = None) -> bool:
    """Атомарно резервує наступний запуск monotonic-задачі.

    Gate виставляється *до* I/O. Якщо HTTP/БД впали, наступний короткий tick
    не створить шторм повторних запитів. ``time.monotonic`` не залежить від
    переведення системного годинника; після рестарту задачі чесно виконаються
    одразу, що є бажаним recovery-поведінкою.
    """
    current = time.monotonic() if now is None else now
    next_at = float(state.get(key, 0) or 0)
    if current < next_at:
        return False
    state[key] = current + max(1.0, float(interval))
    return True


async def tick(state: dict) -> None:
    """Один прохід. Помилка в одному завданні не зупиняє інші."""
    now_mono = time.monotonic()

    if _due(state, "broadcast_check_next_at", BROADCAST_CHECK_SECONDS, now=now_mono):
        try:
            await run_due_broadcasts()
        except Exception:
            log.exception("Помилка під час перевірки розсилок")

    # Черга SalesDrive: усе, що API не зміг відправити одразу. Вона не
    # прив'язана до read-side quota і має доганяти короткі збої швидше.
    if _due(state, "salesdrive_write_retry_next_at", SALESDRIVE_WRITE_RETRY_SECONDS, now=now_mono):
        try:
            await sync_salesdrive()
        except Exception:
            log.exception("Помилка під час синхронізації з SalesDrive")

    # Перевірка «чи настав час добового backup» легка, але все одно не має
    # читати shop settings кожні 15 секунд.
    if _due(state, "backup_check_next_at", BACKUP_CHECK_SECONDS, now=now_mono):
        try:
            await run_backup_if_due(state)
        except Exception:
            log.exception("Помилка під час бекапу")

    # Зворотний напрямок CRM → Elfar. Не залежить від відкритої картки й
    # страхує webhook: snapshot-и регулярно перечитуються у фоні. Окремий
    # глобальний gate важливий навіть при кількох відкладених ID-вікнах:
    # інакше старий env із 60-секундним tick міг би знову витрачати квоту.
    if _due(state, "salesdrive_background_read_next_at", SALESDRIVE_BACKGROUND_READ_SECONDS, now=now_mono):
        try:
            result = await refresh_salesdrive_orders()
            # При outage/backpressure не молотимо CRM з тією ж частотою.
            # Webhook лишається основним live-каналом, read worker — страховка.
            if result.get("failed"):
                state["salesdrive_background_read_next_at"] = time.monotonic() + min(
                    1800, max(300, SALESDRIVE_BACKGROUND_READ_SECONDS * 2)
                )
            elif result.get("skipped") == "api_disconnected":
                state["salesdrive_background_read_next_at"] = time.monotonic() + 300
        except Exception:
            log.exception("Помилка під час фонового читання SalesDrive")
            state["salesdrive_background_read_next_at"] = time.monotonic() + min(
                1800, max(300, SALESDRIVE_BACKGROUND_READ_SECONDS * 2)
            )

    # Retention не залежить від успішності/увімкнення backup. Раніше log
    # pruning виконувався лише після успішного pg_dump, тому при вимкнених
    # бекапах журнали росли безмежно.
    if _due(state, "housekeeping_next_at", HOUSEKEEPING_SECONDS, now=now_mono):
        try:
            await run_housekeeping()
        except Exception:
            log.exception("Помилка під час housekeeping")
            # Добове завдання після тимчасової помилки не повинно чекати ще
            # 24 години. Година достатньо рідка, щоб не створити retry storm,
            # але достатньо коротка для відновлення retention того ж дня.
            state["housekeeping_next_at"] = time.monotonic() + 3600


async def main() -> None:
    log.info(
        "Планувальник запущено: тік %sс, CRM-read %sс, retry %sс, timezone %s",
        TICK_SECONDS, SALESDRIVE_BACKGROUND_READ_SECONDS,
        SALESDRIVE_WRITE_RETRY_SECONDS, settings.timezone,
    )

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Без цього docker compose down чекав би десять секунд і вбивав
        # процес посеред розсилки. Курсор би вцілів, але половина порції
        # поїхала б повторно при наступному запуску.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stopping.set)

    state: dict = {}
    while not stopping.is_set():
        await tick(state)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stopping.wait(), timeout=TICK_SECONDS)

    log.info("Планувальник зупинено")


if __name__ == "__main__":
    asyncio.run(main())
