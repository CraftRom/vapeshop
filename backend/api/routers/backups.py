"""Резервні копії бази з панелі.

Досі бекапи існували лише на диску сервера: щоб їх побачити, треба було
зайти по SSH. Для власника магазину це означало, що бекапи або є, або їх
нема — перевірити ніяк, поки не знадобляться.

Доступ лише системному адміністраторові. Дамп бази — це весь магазин
цілком: клієнти, телефони, адреси, історія замовлень. Віддавати його
тому, хто веде каталог, немає жодних причин.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from api.auth import Principal, require_sysadmin
from shop.config import settings

router = APIRouter(prefix="/api/backups", tags=["backups"])

# Формат pg_dump -Fc починається з підпису PGDMP. Перевіряємо його, а не
# розширення: файл із веб-форми може називатися як завгодно, і покласти
# на місце дампа щось інше означало б зламати відновлення в найгірший
# момент — коли база вже впала.
PGDUMP_SIGNATURE = b"PGDMP"

# Максимальний розмір завантаження. Дамп магазину на десятки тисяч
# замовлень — це одиниці мегабайтів; сотня означає, що щось не те.
MAX_UPLOAD = 200 * 1024 * 1024

NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.dump$")


def backup_dir() -> Path:
    """Каталог копій. Шлях фіксований — див. shop.paths."""
    from shop.paths import backups_dir

    return backups_dir()


def _resolve(name: str) -> Path:
    """Шлях до дампа з перевіркою імені.

    Імʼя приходить із запиту, тож звіряємо його з шаблоном і додатково
    переконуємось, що результат не вийшов за межі каталогу. Одного шаблону
    замало: символічне посилання всередині каталогу теж вивело б назовні.
    """
    if not NAME_RE.fullmatch(name):
        raise HTTPException(404, "Файл не знайдено")
    directory = backup_dir()
    target = directory / name
    if not target.is_file() or target.resolve().parent != directory.resolve():
        raise HTTPException(404, "Файл не знайдено")
    return target


def _describe(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "sizeBytes": stat.st_size,
        "createdAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        # Ручні знімки називаються elfar-manual-*, автоматичні — elfar-<дата>.
        # Розрізняти корисно: автоматичні прибирає ретенція, ручні лишаються.
        "manual": "manual" in path.name,
    }


def _pg_env() -> dict:
    return dict(os.environ, PGPASSWORD=settings.postgres_password)


def _pg_args(tool: str) -> list[str]:
    return [
        tool,
        "-h", settings.postgres_host,
        "-p", str(settings.postgres_port),
        "-U", settings.postgres_user,
        "-d", settings.postgres_db,
    ]


@router.get("")
async def index(who: Principal = Depends(require_sysadmin)):
    """Перелік копій, найновіші першими."""
    directory = backup_dir()
    items = [_describe(p) for p in directory.glob("*.dump") if p.is_file()]
    items.sort(key=lambda item: item["createdAt"], reverse=True)

    total = sum(item["sizeBytes"] for item in items)
    free = shutil.disk_usage(directory).free

    return {
        "items": items,
        "total": len(items),
        "totalBytes": total,
        "freeBytes": free,
        "directory": str(directory),
        "retentionDays": settings.backup_retention_days,
    }


@router.post("/create", status_code=201)
async def create(who: Principal = Depends(require_sysadmin)):
    """Позаплановий знімок просто зараз."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    target = backup_dir() / f"elfar-manual-{stamp}.dump"

    try:
        result = subprocess.run(
            _pg_args("pg_dump") + ["-Fc", "-f", str(target)],
            check=False, env=_pg_env(), capture_output=True, timeout=1800,
        )
    except FileNotFoundError:
        raise HTTPException(500, "pg_dump відсутній в образі") from None

    if result.returncode != 0:
        target.unlink(missing_ok=True)
        raise HTTPException(500, (result.stderr or b"").decode()[:300] or "pg_dump не впорався")

    # Порожній дамп гірший за його відсутність: він виглядає як бекап,
    # але нічого не відновить.
    if target.stat().st_size < 1000:
        target.unlink(missing_ok=True)
        raise HTTPException(500, "Дамп вийшов підозріло малим — перевірте базу")

    return _describe(target)


@router.get("/{name}/download")
async def download(name: str, who: Principal = Depends(require_sysadmin)):
    """Віддає файл дампа."""
    path = _resolve(name)
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.delete("/{name}", status_code=204)
async def remove(name: str, who: Principal = Depends(require_sysadmin)):
    _resolve(name).unlink()


@router.post("/upload", status_code=201)
async def upload(
    file: UploadFile = File(...),
    who: Principal = Depends(require_sysadmin),
):
    """Завантаження дампа з комп'ютера — щоб перенести базу на новий сервер."""
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Файл більший за 200 МБ")
    if not data.startswith(PGDUMP_SIGNATURE):
        raise HTTPException(
            415,
            "Це не дамп pg_dump у форматі custom. "
            "Потрібен файл, створений як pg_dump -Fc",
        )

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(file.filename or "upload").stem)[:40]
    target = backup_dir() / f"elfar-upload-{safe}-{stamp}.dump"
    target.write_bytes(data)
    return _describe(target)


@router.post("/{name}/restore")
async def restore(
    name: str,
    confirm: str = Form(...),
    who: Principal = Depends(require_sysadmin),
):
    """Відновлення бази з копії.

    Вимагаємо ввести імʼя файлу вручну. Це не формальність: операція
    незворотна й затирає поточні дані, а кнопка «так» у діалозі
    натискається рефлекторно. Переписування імені змушує подивитись,
    що саме відновлюється.

    Перед відновленням знімаємо запобіжний дамп: якщо файл виявиться
    старішим, ніж думали, повернутись буде куди.
    """
    path = _resolve(name)
    if confirm.strip() != name:
        raise HTTPException(
            400,
            "Для підтвердження введіть назву файлу точно так, як вона показана",
        )

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    safety = backup_dir() / f"elfar-before-restore-{stamp}.dump"
    subprocess.run(
        _pg_args("pg_dump") + ["-Fc", "-f", str(safety)],
        check=False, env=_pg_env(), capture_output=True, timeout=1800,
    )

    result = subprocess.run(
        _pg_args("pg_restore") + ["--clean", "--if-exists", "--no-owner", str(path)],
        check=False, env=_pg_env(), capture_output=True, timeout=3600,
    )

    # pg_restore повертає ненульовий код і на нешкідливих зауваженнях
    # («об'єкт не існує» при --clean на чистій базі). Розрізняємо їх за
    # текстом: справжня помилка згадує саме error.
    stderr = (result.stderr or b"").decode()
    fatal = [line for line in stderr.splitlines() if "error:" in line.lower()]
    if fatal:
        raise HTTPException(
            500,
            "Відновлення не вдалося: " + fatal[0][:200] +
            f". Стан до спроби збережено як {safety.name}",
        )

    return {
        "restored": name,
        "safetyCopy": safety.name,
        "warnings": len(stderr.splitlines()),
        "note": "Перезапустіть API і бота, щоб вони перечитали дані",
    }
