"""Heartbeat фонових виконавців (A04).

Перемикач у панелі не запускає Docker-сервіс. Без цього модуля «розсилки
увімкнені» виглядало як «розсилки працюють», навіть коли scheduler не був
запущений зовсім (профіль ``workers`` не вмикається звичайним ``up -d``).

Кожен виконавець періодично перезаписує маленький JSON у спільному томі
``/data/heartbeats``. API читає вік файла: свіжий — виконавець живий. Файл
не містить секретів чи даних клієнтів: лише назву, збірку, pid і час.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from pathlib import Path

from shop.build import release_id

# Максимальний вік heartbeat, після якого виконавець вважається зупиненим.
# Запас ~6-8 інтервалів: короткий GC чи перевантажений диск не дає хибної тривоги.
WORKERS = {
    "scheduler": {"interval": 10, "max_age": 75, "title": "Планувальник"},
    "bot": {"interval": 15, "max_age": 120, "title": "Telegram-бот"},
    "maintenance": {"interval": 5, "max_age": 45, "title": "Виконавець резервних копій"},
}


def heartbeat_dir() -> Path:
    from shop.paths import DATA_ROOT
    return DATA_ROOT / "heartbeats"


def beat(service: str, *, directory: Path | None = None, now: float | None = None) -> None:
    if service not in WORKERS:
        raise ValueError("Невідомий виконавець")
    directory = directory or heartbeat_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"service": service, "build": release_id(), "pid": os.getpid(),
               "at": time.time() if now is None else now}
    temporary = directory / f".{service}.{os.getpid()}.tmp"
    fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o640)
    with os.fdopen(fd, "w") as handle:
        json.dump(payload, handle)
    os.replace(temporary, directory / f"{service}.json")


def state(service: str, *, directory: Path | None = None, now: float | None = None) -> dict:
    """{running, last_seen, age_seconds, build} — без винятків для відсутнього файла."""
    spec = WORKERS[service]
    path = (directory or heartbeat_dir()) / f"{service}.json"
    current = time.time() if now is None else now
    try:
        if path.is_symlink():
            raise OSError
        data = json.loads(path.read_text())
        at = float(data["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return {"service": service, "title": spec["title"], "running": False,
                "last_seen": None, "age_seconds": None, "build": None}
    age = max(0.0, current - at)
    return {"service": service, "title": spec["title"], "running": age <= spec["max_age"],
            "last_seen": at, "age_seconds": round(age), "build": str(data.get("build") or "")[:80]}


def states(*, directory: Path | None = None, now: float | None = None) -> dict[str, dict]:
    return {name: state(name, directory=directory, now=now) for name in WORKERS}


async def pulse(service: str, stop: asyncio.Event, *, directory: Path | None = None) -> None:
    """Фонове завдання: heartbeat до сигналу зупинки. Збій диска не валить процес."""
    interval = WORKERS[service]["interval"]
    while not stop.is_set():
        try:
            await asyncio.to_thread(beat, service, directory=directory)
        except Exception:
            import logging
            logging.getLogger("worker_health").warning(
                "Не вдалося оновити heartbeat %s", service,
                extra={"event": "worker.heartbeat.failed", "worker": service})
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), interval)
