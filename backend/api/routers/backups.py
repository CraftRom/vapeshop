"""Резервні копії бази з панелі.

Досі бекапи існували лише на диску сервера: щоб їх побачити, треба було
зайти по SSH. Для власника магазину це означало, що бекапи або є, або їх
нема — перевірити ніяк, поки не знадобляться.

Доступ лише системному адміністраторові. Дамп бази — це весь магазин
цілком: клієнти, телефони, адреси, історія замовлень. Віддавати його
тому, хто веде каталог, немає жодних причин.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from shop.services.backup_jobs import configured_store
from shop.backup_files import (BackupBusy, BackupError, SIGNATURE, backup_lock,
    staging_file, unique_name, publish)

from shop import security_log as security
from api.auth import Principal, require_sysadmin
from shop.config import settings

router = APIRouter(prefix="/api/backups", tags=["backups"])

# Формат pg_dump -Fc починається з підпису PGDMP. Перевіряємо його, а не
# розширення: файл із веб-форми може називатися як завгодно, і покласти
# на місце дампа щось інше означало б зламати відновлення в найгірший
# момент — коли база вже впала.
PGDUMP_SIGNATURE = SIGNATURE

# Browser transfer budget; larger archives use the host recovery workflow.
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
    if target.is_symlink() or not target.is_file() or target.resolve().parent != directory.resolve():
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
        "manual": "manual" in path.name or path.name.startswith("elfar-job-"),
    }


@router.get("")
async def index(who: Principal = Depends(require_sysadmin)):
    """Перелік копій, найновіші першими."""
    directory = backup_dir()
    items = [_describe(p) for p in directory.glob("*.dump") if p.is_file() and not p.is_symlink()]
    items.sort(key=lambda item: item["createdAt"], reverse=True)

    total = sum(item["sizeBytes"] for item in items)
    free = shutil.disk_usage(directory).free

    from shop.db import storage_report

    from shop.repo.factory import open_repo
    from shop.services.shop_settings import get_shop_settings
    async with open_repo() as repo:
        shop = await get_shop_settings(repo)
    return {
        "restoreMode": "server",
        "items": items,
        "total": len(items),
        "totalBytes": total,
        "freeBytes": free,
        "directory": str(directory),
        "retentionDays": shop.backup_retention_days,
        "database": await storage_report(),
    }


@router.post("/create", status_code=201)
async def create(who: Principal = Depends(require_sysadmin)):
    """Позаплановий знімок просто зараз."""
    raise HTTPException(409, 'Оновіть dashboard: створення копій тепер виконується через фонове завдання.')


class BackupJobIn(BaseModel):
    client_key: str = Field(min_length=16, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')


@router.post('/jobs', status_code=202)
async def enqueue_job(data: BackupJobIn, who: Principal = Depends(require_sysadmin)):
    try:
        job = await run_in_threadpool(configured_store().enqueue, data.client_key, who.login)
        security.record('security.backup.requested', actor=who.login, reason=job['id'])
        return job
    except BackupBusy as exc:
        raise HTTPException(409, str(exc)) from None
    except (BackupError, OSError, ValueError):
        raise HTTPException(503, 'Не вдалося зберегти завдання. Повторіть той самий запит.') from None


@router.get('/jobs')
async def jobs(who: Principal = Depends(require_sysadmin)):
    try:
        store = configured_store()
        return {'jobs': await run_in_threadpool(store.recent), 'worker': store.worker_state()}
    except (BackupError, OSError):
        raise HTTPException(503, 'Журнал завдань недоступний. Перевірте диск і права доступу.') from None


@router.get('/jobs/{job_id}')
async def job_status(job_id: str, who: Principal = Depends(require_sysadmin)):
    try:
        return await run_in_threadpool(configured_store().read, job_id)
    except FileNotFoundError:
        raise HTTPException(404, 'Завдання не знайдено') from None
    except (BackupError, OSError):
        raise HTTPException(503, 'Журнал завдання недоступний') from None


@router.get("/{name}/download")
async def download(name: str, who: Principal = Depends(require_sysadmin)):
    """Віддає файл дампа."""
    path = _resolve(name)
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.delete("/{name}", status_code=204)
async def remove(name: str, who: Principal = Depends(require_sysadmin)):
    _resolve(name).unlink()
    security.record("security.backup.deleted", actor=who.login, reason=name)


@router.post("/upload", status_code=201)
async def upload(
    file: UploadFile = File(...),
    who: Principal = Depends(require_sysadmin),
):
    """Завантаження дампа з комп'ютера — щоб перенести базу на новий сервер."""
    directory = backup_dir()
    try:
        with backup_lock(directory), staging_file(directory) as temporary:
            total = 0
            with temporary.open('wb') as handle:
                while chunk := await file.read(256 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD:
                        raise HTTPException(413, 'Файл більший за 64 МіБ. Великі копії передавайте через сервер.')
                    handle.write(chunk)
            with temporary.open('rb') as handle:
                if handle.read(len(SIGNATURE)) != SIGNATURE:
                    raise HTTPException(415, 'Потрібна копія pg_dump у форматі custom (pg_dump -Fc)')
            # Uploaded archives are stored, not executed. Restore validates their
            # full contents in an isolated database before changing the target.
            target = await run_in_threadpool(publish, temporary, directory / unique_name('elfar-upload'))
    except BackupBusy as exc:
        raise HTTPException(409, str(exc)) from None
    security.record('security.backup.uploaded', actor=who.login, reason=target.name)
    return _describe(target)


@router.post("/{name}/restore")
async def restore(
    name: str,
    confirm: str = Form(...),
    who: Principal = Depends(require_sysadmin),
):
    _resolve(name)
    if confirm.strip() != name:
        raise HTTPException(
            400,
            "Для підтвердження введіть назву файлу точно так, як вона показана",
        )

    # A request cannot stop its own API and all other database writers safely.
    # Keep the old route fail-closed for already open tabs and API clients.
    security.record('security.backup.restore.blocked', actor=who.login, reason=name)
    raise HTTPException(409, 'Відновлення виконується на сервері через deploy/restore.sh після зупинки процесів запису. У браузері базу не змінено.')
