"""Цикл планувальника.

Один процес, один цикл, жодних зовнішніх залежностей на кшталт cron чи
черги завдань. Для магазину з десятками розсилок на місяць окремий брокер
був би зайвою рухомою деталлю, яку теж треба піднімати, моніторити й
відновлювати після падіння.

Період тіку береться з SCHEDULER_INTERVAL_SECONDS (за замовчуванням година).
Точність планування — година, тому прокидатися частіше немає сенсу: це були
б зайві запити до бази цілодобово.

Наслідок, про який варто памʼятати: бекап перевіряється тим самим тіком, і
при годинному інтервалі він спрацює в межах години після заданого часу.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from shop.config import settings
from scheduler.tasks import run_backup_if_due, run_due_broadcasts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("scheduler")

TICK_SECONDS = max(int(settings.scheduler_interval_seconds), 30)


async def tick(state: dict) -> None:
    """Один прохід. Помилка в одному завданні не зупиняє інші."""
    try:
        await run_due_broadcasts()
    except Exception:
        log.exception("Помилка під час перевірки розсилок")

    try:
        await run_backup_if_due(state)
    except Exception:
        log.exception("Помилка під час бекапу")


async def main() -> None:
    log.info(
        "Планувальник запущено: тік кожні %s с, база %s, часова зона %s",
        TICK_SECONDS, settings.db_backend, settings.timezone,
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
