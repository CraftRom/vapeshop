"""Читання журналу для панелі.

Доступ лише системному адміністраторові: у записах є IP клієнтів, логіни,
шляхи запитів і тексти помилок. Це не те, що варто відкривати кожному,
хто керує каталогом.

Читаємо файли з кінця. Журнал росте до десяти мегабайтів, і завантажувати
його цілком заради останньої сотні рядків означало б з'їдати памʼять
контейнера рівно тоді, коли щось уже пішло не так і його читають.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import Principal, require_sysadmin

router = APIRouter(prefix="/api/logs", tags=["logs"])

# Перелік, а не читання каталогу: ім'я сервісу приходить із запиту й
# підставляється у шлях. Білий список — єдиний надійний захист від
# «../../etc/passwd», і він же документує, що взагалі є в системі.
SERVICES = ("api", "bot", "scheduler")

LEVELS = ("debug", "info", "warning", "error", "critical")

# Скільки байтів читаємо з хвоста файлу. 2 МБ — це приблизно 5–8 тисяч
# записів: більше однаково не показати в інтерфейсі, а памʼяті коштує.
TAIL_BYTES = 2 * 1024 * 1024


def _log_path(service: str) -> Path:
    if service not in SERVICES:
        raise HTTPException(404, f"Невідомий сервіс: {service}")
    directory = os.environ.get("LOG_DIR", "")
    if not directory:
        raise HTTPException(
            503,
            "Файлове логування вимкнено: не задано LOG_DIR. "
            "Журнал доступний лише через docker compose logs",
        )
    return Path(directory) / f"{service}.log"


def _read_tail(path: Path) -> list[str]:
    """Останні рядки файлу без завантаження його цілком."""
    if not path.exists():
        return []

    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > TAIL_BYTES:
            handle.seek(size - TAIL_BYTES)
            # Перший рядок після зсуву майже напевно обрізаний посередині —
            # відкидаємо його, інакше отримаємо биту половину JSON.
            handle.readline()
        chunk = handle.read()

    return chunk.decode("utf-8", errors="replace").splitlines()


def _day_start(value: str) -> str:
    """«2026-08-26» → межа, з якої починається доба."""
    value = value.strip()
    if not value:
        return ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise HTTPException(422, f"Дата має бути у форматі РРРР-ММ-ДД, отримано: {value}")
    return f"{value}T00:00:00"


def _day_end(value: str) -> str:
    """«2026-08-26» → межа, якою доба закінчується, включно."""
    value = value.strip()
    if not value:
        return ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise HTTPException(422, f"Дата має бути у форматі РРРР-ММ-ДД, отримано: {value}")
    return f"{value}T23:59:59.999999+99:99"


def _parse(line: str) -> dict | None:
    """Рядок журналу як словник. Небитий JSON — обов'язкова умова.

    Сторонні бібліотеки інколи пишуть у stdout повз наш обробник, і такі
    рядки в файл не потрапляють. Але якщо колись потраплять — краще їх
    тихо пропустити, ніж завалити всю сторінку.
    """
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        record = json.loads(line)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


@router.get("/services")
async def list_services(who: Principal = Depends(require_sysadmin)):
    """Які журнали є і чи вони взагалі пишуться."""
    directory = os.environ.get("LOG_DIR", "")
    result = []
    for service in SERVICES:
        entry = {"service": service, "exists": False, "sizeBytes": 0}
        if directory:
            path = Path(directory) / f"{service}.log"
            if path.exists():
                entry["exists"] = True
                entry["sizeBytes"] = path.stat().st_size
        result.append(entry)
    return {"logDir": directory, "services": result, "levels": list(LEVELS)}


@router.get("")
async def read_logs(
    service: str = Query("api"),
    level: str = Query("", description="Мінімальний рівень"),
    event: str = Query("", description="Точна назва події"),
    request_id: str = Query("", alias="requestId"),
    since: str = Query("", description="Від дати, YYYY-MM-DD"),
    until: str = Query("", description="До дати включно, YYYY-MM-DD"),
    search: str = Query("", description="Підрядок у будь-якому полі"),
    limit: int = Query(200, ge=1, le=2000),
    who: Principal = Depends(require_sysadmin),
):
    """Записи журналу з фільтрами, найновіші першими."""
    path = _log_path(service)
    lines = _read_tail(path)

    # Мінімальний рівень, а не точний збіг: коли шукають помилки, критичні
    # теж потрібні. Точний збіг тут був би пасткою — людина обирає «error»
    # і не бачить падіння.
    threshold = LEVELS.index(level.lower()) if level.lower() in LEVELS else -1

    # Межі доби рахуємо один раз, а не для кожного запису. Порівнюємо рядки
    # ISO-дат: вони сортуються лексикографічно так само, як хронологічно,
    # тож розбирати кожен час у datetime заради фільтра нема потреби.
    since_key = _day_start(since)
    until_key = _day_end(until)

    needle = search.lower()
    records = []
    scanned = 0

    # З кінця: найновіше цікавить першим, і на великому файлі це дозволяє
    # зупинитися, щойно набрали потрібну кількість.
    for line in reversed(lines):
        record = _parse(line)
        if record is None:
            continue
        scanned += 1

        record_time = str(record.get("time", ""))
        if since_key and record_time < since_key:
            # Записи йдуть від нових до старих: щойно вийшли за нижню межу,
            # далі буде тільки старіше. Зупиняємось, а не перебираємо файл
            # до кінця — на десяти мегабайтах різниця відчутна.
            break
        if until_key and record_time > until_key:
            continue

        if threshold >= 0:
            record_level = str(record.get("level", "")).lower()
            if record_level not in LEVELS or LEVELS.index(record_level) < threshold:
                continue
        if event and record.get("event") != event:
            continue
        if request_id and record.get("requestId") != request_id:
            continue
        if needle and needle not in json.dumps(record, ensure_ascii=False).lower():
            continue

        records.append(record)
        if len(records) >= limit:
            break

    return {
        "service": service,
        # Коли записів нема, найчастіше питання не «де вони», а «чи вони
        # взагалі пишуться». Відповідаємо на нього одразу, щоб не гадати.
        "diagnostics": {
            "logDir": os.environ.get("LOG_DIR", ""),
            "file": str(path),
            "exists": path.exists(),
            "sizeBytes": path.stat().st_size if path.exists() else 0,
            "linesInTail": len(lines),
        },
        "records": records,
        "returned": len(records),
        "scanned": scanned,
        "truncated": len(records) >= limit,
    }


@router.get("/events")
async def list_events(
    service: str = Query("api"),
    who: Principal = Depends(require_sysadmin),
):
    """Які події трапляються в цьому журналі — для випадного списку.

    Рахуємо на льоту, а не тримаємо перелік у коді: інакше нова подія
    з'явиться в журналі, але не у фільтрі, і знайти її буде нічим.
    """
    lines = _read_tail(_log_path(service))
    counts: dict[str, int] = {}
    for line in lines:
        record = _parse(line)
        if record and record.get("event"):
            name = str(record["event"])
            counts[name] = counts.get(name, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: -item[1])
    return {"events": [{"event": n, "count": c} for n, c in ordered[:50]]}
