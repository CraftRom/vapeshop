"""Цикл планувальника.

Один процес, один цикл, жодних зовнішніх залежностей на кшталт cron чи
черги завдань. Для магазину з десятками розсилок на місяць окремий брокер
був би зайвою рухомою деталлю, яку теж треба піднімати, моніторити й
відновлювати після падіння.

Період тіку — мінімум між SCHEDULER_INTERVAL_SECONDS і окремим інтервалом
SalesDrive read-side sync. Важкі задачі самі перевіряють, чи настав їх час,
тому частіший легкий tick не запускає бекап або cleanup щохвилини.
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
    forget_old_chat_files, refresh_salesdrive_orders, run_backup_if_due,
    run_due_broadcasts, sync_salesdrive,
)

setup_logging("scheduler")
log = logging.getLogger("scheduler")

# Старі production env можуть містити як SCHEDULER_INTERVAL_SECONDS=3600,
# так і SALESDRIVE_BACKGROUND_REFRESH_SECONDS=60. Загальний scheduler може
# тикати частіше для інших задач, але саме /api/order/list/ не викликаємо
# частіше ніж раз на 120 с — це глобальний бюджет фонового read-side worker.
SALESDRIVE_BACKGROUND_READ_SECONDS = max(
    120, int(settings.salesdrive_background_refresh_seconds)
)
TICK_SECONDS = max(15, min(
    int(settings.scheduler_interval_seconds),
    SALESDRIVE_BACKGROUND_READ_SECONDS,
))


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
    # Черга SalesDrive: усе, що API не зміг відправити одразу.
    try:
        await sync_salesdrive()
    except Exception:
        log.exception("Помилка під час синхронізації з SalesDrive")

    # Зворотний напрямок CRM → Elfar. Не залежить від відкритої картки й
    # страхує webhook: snapshot-и регулярно перечитуються у фоні. Окремий
    # глобальний gate важливий навіть при кількох відкладених ID-вікнах:
    # інакше старий env із 60-секундним tick міг би знову витрачати квоту.
    now_mono = time.monotonic()
    last_crm_read = float(state.get("salesdrive_background_read_at", 0) or 0)
    if now_mono - last_crm_read >= SALESDRIVE_BACKGROUND_READ_SECONDS:
        # Бюджет резервуємо ДО HTTP: навіть 4xx/5xx не повинні запускати
        # повторний background read уже на наступному короткому tick.
        state["salesdrive_background_read_at"] = now_mono
        try:
            await refresh_salesdrive_orders()
        except Exception:
            log.exception("Помилка під час фонового читання SalesDrive")

    # Раз на добу, а не щотіку: запит проходить по всіх виконаних
    # замовленнях, а строк зберігання рахується днями — частіше просто
    # нічого не змінить.
    if time.time() - state.get("files_pruned_at", 0) >= 24 * 3600:
        try:
            await forget_old_chat_files()
            state["files_pruned_at"] = time.time()
        except Exception:
            log.exception("Помилка під час прибирання вкладень")


async def main() -> None:
    log.info(
        "Планувальник запущено: тік кожні %s с, часова зона %s",
        TICK_SECONDS, settings.timezone,
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
