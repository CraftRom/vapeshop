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
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import Principal, require_sysadmin

router = APIRouter(prefix="/api/logs", tags=["logs"])

# Перелік, а не читання каталогу: ім'я сервісу приходить із запиту й
# підставляється у шлях. Білий список — єдиний надійний захист від
# «../../etc/passwd», і він же документує, що взагалі є в системі.
# security стоїть першим навмисно: у випадному списку панелі він має бути
# на видноті, а не наприкінці. Це окремий потік, а не рівень у спільному
# файлі — подій там на порядки менше, і серед тисяч записів про каталог
# вони губилися б безслідно.
SERVICES = ("security", "api", "bot", "scheduler")

LEVELS = ("debug", "info", "warning", "error", "critical")

# Скільки байтів читаємо з хвоста файлу. 2 МБ — це приблизно 5–8 тисяч
# записів: більше однаково не показати в інтерфейсі, а памʼяті коштує.
TAIL_BYTES = 2 * 1024 * 1024


def _log_path(service: str) -> Path:
    if service not in SERVICES:
        raise HTTPException(404, f"Невідомий сервіс: {service}")
    from shop.paths import logs_dir

    return logs_dir() / f"{service}.log"


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


def _rotated(path: Path) -> list[Path]:
    """Прокручені файли поруч із поточним: api.log.1, api.log.2, …

    Їх легко не помітити: у каталозі лежить п'ять таких файлів, а панель
    показувала розмір лише поточного. Виходило, що журнали «важать 2 МБ»,
    коли насправді займали під шістдесят.
    """
    return sorted(path.parent.glob(f"{path.name}.*")) if path.parent.exists() else []


def _usage(path: Path) -> dict:
    """Скільки місця займає журнал сервісу разом із прокрученими файлами."""
    current = path.stat().st_size if path.exists() else 0
    archived = sum(p.stat().st_size for p in _rotated(path) if p.exists())
    return {
        "sizeBytes": current,
        "rotatedBytes": archived,
        "rotatedFiles": len(_rotated(path)),
        "totalBytes": current + archived,
    }


@router.get("/services")
async def list_services(who: Principal = Depends(require_sysadmin)):
    """Які журнали є, чи вони пишуться і скільки місця займають."""
    from shop.logging_setup import log_backups, log_budget_bytes, log_max_bytes
    from shop.paths import describe, logs_dir

    directory = logs_dir()
    result = []
    for service in SERVICES:
        path = directory / f"{service}.log"
        result.append({"service": service, "exists": path.exists(), **_usage(path)})

    total = sum(item["totalBytes"] for item in result)
    budget = log_budget_bytes()
    return {
        "logDir": str(directory),
        "services": result,
        "levels": list(LEVELS),
        "storage": describe(),
        # Скільки журнали займають зараз і скільки їм відведено. Друге
        # важливіше за перше: воно каже, що місце на диску не скінчиться.
        "usage": {
            "totalBytes": total,
            "budgetBytes": budget,
            "maxBytesPerFile": log_max_bytes(),
            "backupCount": log_backups(),
        },
    }


def _select(
    lines: list[str], *, level: str, event: str, request_id: str,
    since: str, until: str, search: str, limit: int, severity: str = "",
) -> tuple[list[dict], int]:
    """Відбір записів за фільтрами. Найновіші першими.

    Винесено з обробника, бо тими самими фільтрами тепер користується й
    завантаження файлу. Поки відбір жив усередині read_logs, «скачати»
    віддавало весь файл незалежно від того, що людина бачила на екрані —
    і вибране «200 записів» на завантаження не впливало ніяк.
    """
    # Мінімальний рівень, а не точний збіг: коли шукають помилки, критичні
    # теж потрібні. Точний збіг тут був би пасткою — людина обирає «error»
    # і не бачить падіння.
    threshold = LEVELS.index(level.lower()) if level.lower() in LEVELS else -1

    # Критичність події безпеки — окрема шкала від рівня журналу. Невдалий
    # вхід нічого не ламає, тож пишеться як info, але за змістом це подія,
    # про яку треба знати. Тут теж «і вище», а не точний збіг.
    from shop.security_log import SEVERITIES

    severity_floor = (
        SEVERITIES.index(severity.lower()) if severity.lower() in SEVERITIES else -1
    )

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
        if severity_floor >= 0:
            record_severity = str(record.get("severity", "")).lower()
            if (record_severity not in SEVERITIES
                    or SEVERITIES.index(record_severity) < severity_floor):
                continue
        # Збіг за префіксом, а не лише повний: «security.login» знаходить
        # і вдалі входи, і невдалі, і блокування — тобто всю історію входу
        # одним фільтром. Точну назву це не ламає: повний код теж є
        # префіксом самого себе.
        if event:
            name = str(record.get("event", ""))
            if name != event and not name.startswith(event + "."):
                continue
        if request_id and record.get("requestId") != request_id:
            continue
        if needle and needle not in json.dumps(record, ensure_ascii=False).lower():
            continue

        records.append(record)
        if len(records) >= limit:
            break

    return records, scanned


@router.get("")
async def read_logs(
    service: str = Query("api"),
    level: str = Query("", description="Мінімальний рівень"),
    event: str = Query("", description="Точна назва події"),
    request_id: str = Query("", alias="requestId"),
    since: str = Query("", description="Від дати, YYYY-MM-DD"),
    until: str = Query("", description="До дати включно, YYYY-MM-DD"),
    search: str = Query("", description="Підрядок у будь-якому полі"),
    severity: str = Query("", description="Критичність події безпеки і вище"),
    limit: int = Query(200, ge=1, le=2000),
    who: Principal = Depends(require_sysadmin),
):
    """Записи журналу з фільтрами, найновіші першими."""
    path = _log_path(service)
    lines = _read_tail(path)
    records, scanned = _select(
        lines, level=level, event=event, request_id=request_id,
        since=since, until=until, search=search, limit=limit,
        severity=severity,
    )

    return {
        "service": service,
        # Коли записів нема, найчастіше питання не «де вони», а «чи вони
        # взагалі пишуться». Відповідаємо на нього одразу, щоб не гадати.
        "diagnostics": {
            "logDir": str(path.parent),
            "file": str(path),
            "exists": path.exists(),
            "linesInTail": len(lines),
            **_usage(path),
        },
        "records": records,
        "returned": len(records),
        "scanned": scanned,
        "truncated": len(records) >= limit,
    }


@router.get("/{service}/download")
async def download(
    service: str,
    level: str = Query(""),
    event: str = Query(""),
    request_id: str = Query("", alias="requestId"),
    since: str = Query(""),
    until: str = Query(""),
    search: str = Query(""),
    severity: str = Query(""),
    limit: int = Query(200, ge=1, le=2000),
    full: bool = Query(False, description="Віддати файл цілком, без фільтрів"),
    who: Principal = Depends(require_sysadmin),
):
    """Журнал файлом — рівно те, що видно на екрані.

    Раніше звідси завжди приходив увесь файл. Здавалося логічним: качають,
    щоб розібрати jq чи grep, і урізана вибірка була б гіршою за повну.
    Насправді виходило інакше — людина відбирала помилки за конкретну добу,
    натискала «Скачати файл» і отримувала десять мегабайтів усього підряд,
    де відібраного треба було шукати заново. Вибір «скільки записів» на
    файл не впливав ніяк.

    Тепер файл повторює вибірку. Повний файл нікуди не подівся — він за
    параметром full=1, і кнопка на нього в панелі поруч.
    """
    from fastapi.responses import FileResponse, Response

    path = _log_path(service)
    if not path.exists():
        raise HTTPException(404, f"Журнал сервісу {service} ще порожній")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")

    if full:
        return FileResponse(
            path,
            # Латиниця навмисно: кирилицю в назві файлу браузер передає
            # відсотковим кодуванням, і в консолі замість імені видно
            # ланцюг %D0%BF. Файл однаково розбирають jq та grep.
            filename=f"elfar-{service}-{stamp}-full.log",
            media_type="application/x-ndjson",
        )

    records, _ = _select(
        _read_tail(path), level=level, event=event, request_id=request_id,
        since=since, until=until, search=search, limit=limit, severity=severity,
    )
    # Найстаріше вгорі: у файлі, який читатимуть очима або згодовуватимуть
    # jq, природний порядок — хронологічний. На екрані навпаки, бо там
    # цікавить останнє, але для файлу це заважало б.
    body = "\n".join(
        json.dumps(record, ensure_ascii=False) for record in reversed(records)
    )
    return Response(
        content=(body + "\n") if body else "",
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition":
                f'attachment; filename="elfar-{service}-{stamp}.log"',
            # Скільки рядків насправді у файлі — щоб не рахувати вручну,
            # коли фільтр відсіяв більше, ніж очікували.
            "X-Records": str(len(records)),
        },
    )


@router.get("/events")
async def list_events(
    service: str = Query("api"),
    who: Principal = Depends(require_sysadmin),
):
    """Які події трапляються в цьому журналі — для випадного списку.

    Рахуємо на льоту, а не тримаємо перелік у коді: інакше нова подія
    з'явиться в журналі, але не у фільтрі, і знайти її буде нічим.
    """
    from shop.security_log import CATALOG, SEVERITIES, describe

    lines = _read_tail(_log_path(service))
    counts: dict[str, int] = {}
    for line in lines:
        record = _parse(line)
        if record and record.get("event"):
            name = str(record["event"])
            counts[name] = counts.get(name, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: -item[1])

    # Голий код події нічого не каже тому, хто його не писав. Віддаємо
    # разом із підписом: у списку фільтра має стояти «Невдала спроба
    # входу», а не «security.login.failed».
    events = []
    for name, count in ordered[:50]:
        item = {"event": name, "count": count}
        if name.startswith("security."):
            described = describe(name)
            item["title"] = described.title
            item["severity"] = described.severity
        events.append(item)

    result = {"events": events}
    if service == "security":
        # Увесь каталог, а не лише те, що вже трапилось: інакше подію,
        # якої ще не було, неможливо ані знайти, ані навіть дізнатися,
        # що система її вміє помічати.
        result["catalog"] = [
            {"event": e.code, "severity": e.severity,
             "title": e.title, "detail": e.detail}
            for e in sorted(CATALOG.values(),
                            key=lambda e: (SEVERITIES.index(e.severity), e.code))
        ]
        result["severities"] = list(SEVERITIES)
    return result
