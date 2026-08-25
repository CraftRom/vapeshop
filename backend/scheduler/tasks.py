"""Завдання планувальника.

Кожне завдання самодостатнє: бере власне зʼєднання з базою, читає чинні
налаштування магазину і саме вирішує, чи його час настав. Так планувальник
лишається тонким циклом, а завдання можна викликати поштучно з тестів.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shop.config import settings
from shop.entities import BroadcastStatus
from shop.repo.factory import open_repo
from shop.services import broadcast as broadcast_service
from shop.services.shop_settings import get_shop_settings

log = logging.getLogger("scheduler")


# --------------------------------------------------------------- розсилки

async def run_due_broadcasts() -> int:
    """Запускає розсилки, чий час настав. Повертає кількість запущених.

    Тихі години перевіряються тут, а не при плануванні: адміністратор може
    змінити їх після того, як розсилку вже поставлено в чергу, і правильним
    є те значення, яке чинне на момент відправки.
    """
    now = datetime.now(timezone.utc)

    async with open_repo() as repo:
        shop = await get_shop_settings(repo)
        due = await repo.due_broadcasts(now)

        if not due:
            return 0

        if shop.in_quiet_hours(now):
            wake = shop.next_active_moment(now)
            log.info(
                "Тихі години: %s розсилок чекають до %s",
                len(due), wake.strftime("%H:%M %d.%m"),
            )
            return 0

        started = []
        for item in due:
            # Статус переводимо одразу й окремим записом: якщо процес упаде
            # між цим і початком відправки, розсилка не піде вдруге з нуля.
            await repo.update_broadcast(item.id, {
                "status": BroadcastStatus.SENDING,
                "sent_count": 0, "failed_count": 0, "cursor_id": 0,
            })
            started.append(item.id)

    for broadcast_id in started:
        log.info("Запускаю заплановану розсилку %s", broadcast_id)
        try:
            await broadcast_service.run_to_completion(
                broadcast_id, chunk=settings.broadcast_chunk
            )
        except Exception:
            # Одна розсилка не має валити планувальник: решта черги
            # має відпрацювати, а причину видно в логах.
            log.exception("Розсилка %s впала", broadcast_id)
            async with open_repo() as repo:
                await repo.update_broadcast(broadcast_id, {"status": BroadcastStatus.FAILED})

    return len(started)


# ---------------------------------------------------------------- бекапи

def _backup_dir() -> Path:
    path = Path(settings.backup_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pg_dump(target: Path) -> None:
    """Знімок бази через pg_dump у стиснутому власному форматі.

    Формат `custom` (-Fc), а не звичайний SQL: він стискається вдвічі й
    дозволяє відновлювати окремі таблиці через pg_restore.
    """
    env = dict(os.environ, PGPASSWORD=settings.postgres_password)
    subprocess.run(
        [
            "pg_dump",
            "-h", settings.postgres_host,
            "-p", str(settings.postgres_port),
            "-U", settings.postgres_user,
            "-d", settings.postgres_db,
            "-Fc", "-f", str(target),
        ],
        check=True, env=env, capture_output=True, timeout=1800,
    )


async def run_backup_if_due(state: dict) -> bool:
    """Один бекап на добу о заданій годині за часом магазину.

    `state` — памʼять між тіками в межах процесу: дата останнього бекапу.
    Перезапуск контейнера скидає її, тому додатково перевіряємо, чи файл
    за сьогодні вже не лежить на диску.
    """
    if not settings.backup_enabled or settings.db_backend != "sql":
        return False

    async with open_repo() as repo:
        shop = await get_shop_settings(repo)

    local = datetime.now(timezone.utc).astimezone(shop.tz)
    if local.hour != shop.backup_hour:
        return False
    if state.get("last_backup_date") == local.date():
        return False

    target = _backup_dir() / f"elfar-{local:%Y-%m-%d}.dump"
    if target.exists():
        state["last_backup_date"] = local.date()
        return False

    started = time.monotonic()
    try:
        _pg_dump(target)
    except subprocess.CalledProcessError as exc:
        log.error("Бекап не вдався: %s", (exc.stderr or b"").decode()[:300])
        target.unlink(missing_ok=True)
        return False
    except FileNotFoundError:
        log.error("pg_dump не знайдено в образі — бекап пропущено")
        return False

    state["last_backup_date"] = local.date()
    size_mb = target.stat().st_size / 1024 / 1024
    log.info("Бекап %s готовий: %.1f МБ за %.0f с", target.name, size_mb, time.monotonic() - started)

    prune_backups(shop.backup_retention_days)
    return True


def prune_backups(retention_days: int) -> int:
    """Прибирає бекапи, старші за ретенцію. Повертає кількість видалених."""
    if retention_days < 1:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0
    for item in _backup_dir().glob("elfar-*.dump"):
        if datetime.fromtimestamp(item.stat().st_mtime, timezone.utc) < cutoff:
            item.unlink(missing_ok=True)
            removed += 1
    if removed:
        log.info("Видалено старих бекапів: %s (ретенція %s днів)", removed, retention_days)
    return removed
