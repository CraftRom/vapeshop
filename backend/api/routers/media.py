"""Зберігання зображень на власному сервері.

Раніше картинку можна було лише вказати посиланням на чужий хостинг. Це
працює рівно доти, доки той хостинг живий: коли він зникає, каталог
залишається без фото, і дізнаєтесь ви про це від клієнта.

Файли лягають у MEDIA_DIR, віддає їх nginx напряму — застосунок у цьому
не бере участі, бо перекладати мегабайти через Python немає сенсу.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.auth import Principal, require_staff
from shop.config import settings

router = APIRouter(prefix="/api/media", tags=["media"])

# Тільки зображення й тільки ті формати, які точно показує Telegram.
# Перевіряємо не за розширенням у назві, а за вмістом: розширення пише
# той, хто вантажить, і йому не можна вірити.
SIGNATURES = {
    b"\xff\xd8\xff": ("jpg", "image/jpeg"),
    b"\x89PNG\r\n\x1a\n": ("png", "image/png"),
    b"GIF87a": ("gif", "image/gif"),
    b"GIF89a": ("gif", "image/gif"),
    b"RIFF": ("webp", "image/webp"),  # уточнюється нижче
}

MAX_BYTES = 8 * 1024 * 1024


def _media_dir() -> Path:
    path = Path(settings.media_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sniff(head: bytes) -> tuple[str, str]:
    """Формат за вмістом файлу. Повертає (розширення, MIME)."""
    for signature, (extension, mime) in SIGNATURES.items():
        if head.startswith(signature):
            if signature == b"RIFF":
                # RIFF — контейнер не лише для WebP: там може бути звук
                # або відео. Формат уточнює мітка на 8-му байті.
                if head[8:12] != b"WEBP":
                    continue
            return extension, mime
    raise HTTPException(
        415,
        "Підтримуються лише зображення: JPEG, PNG, GIF або WebP. "
        "Формат визначається за вмістом файлу, а не за назвою",
    )


def _safe_name(original: str, digest: str, extension: str) -> str:
    """Ім'я файлу: читабельна основа плюс хеш вмісту.

    Хеш потрібен, щоб повторне завантаження того самого файлу не плодило
    копій, а різні файли з однаковою назвою не затирали одне одного.
    Основа лишається читабельною, щоб у переліку було видно, що це.
    """
    stem = Path(original or "").stem[:40]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-").lower()
    return f"{stem or 'image'}-{digest[:12]}.{extension}"


def _public_url(name: str) -> str:
    return f"/media/{name}"


def _describe(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "url": _public_url(path.name),
        "sizeBytes": stat.st_size,
        "uploadedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


@router.post("", status_code=201)
async def upload(
    file: UploadFile = File(...),
    who: Principal = Depends(require_staff),
):
    """Завантаження зображення. Доступно всім, хто веде каталог."""
    head = await file.read(16)
    extension, mime = _sniff(head)

    # Читаємо порціями й обриваємо на межі: інакше вісім мегабайтів межі
    # не означали б нічого, бо файл уже був би цілком у памʼяті.
    digest = hashlib.sha256()
    digest.update(head)
    chunks = [head]
    total = len(head)

    while True:
        chunk = await file.read(256 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_BYTES:
            raise HTTPException(
                413, f"Файл більший за {MAX_BYTES // 1024 // 1024} МБ"
            )
        digest.update(chunk)
        chunks.append(chunk)

    if total < 100:
        raise HTTPException(400, "Файл порожній або пошкоджений")

    name = _safe_name(file.filename or "", digest.hexdigest(), extension)
    target = _media_dir() / name

    # Файл із таким вмістом уже є — просто повертаємо посилання. Так
    # повторне завантаження тієї самої картинки не засмічує диск.
    if not target.exists():
        with target.open("wb") as handle:
            for chunk in chunks:
                handle.write(chunk)

    return {**_describe(target), "mime": mime, "reused": target.stat().st_size == total
            and len(chunks) == 0}


@router.get("")
async def library(
    limit: int = 100,
    who: Principal = Depends(require_staff),
):
    """Уже завантажені зображення, найновіші першими."""
    directory = _media_dir()
    files = [p for p in directory.iterdir() if p.is_file() and not p.name.startswith(".")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    total_bytes = sum(p.stat().st_size for p in files)
    return {
        "files": [_describe(p) for p in files[: max(1, min(limit, 500))]],
        "total": len(files),
        "totalBytes": total_bytes,
    }


@router.delete("/{name}", status_code=204)
async def remove(name: str, who: Principal = Depends(require_staff)):
    """Видалення файлу.

    Ім'я приходить із запиту й підставляється у шлях, тому перевіряємо
    його окремо: будь-який роздільник каталогів означає спробу вийти за
    межі сховища.
    """
    if "/" in name or "\\" in name or name.startswith(".") or ".." in name:
        raise HTTPException(400, "Неприпустиме ім'я файлу")

    target = _media_dir() / name
    # resolve() на випадок символьних посилань: сам рядок може бути
    # чистим, а вести файл усе одно назовні.
    if not target.resolve().is_relative_to(_media_dir().resolve()):
        raise HTTPException(400, "Неприпустиме ім'я файлу")
    if not target.exists():
        raise HTTPException(404, "Файл не знайдено")

    target.unlink()
    return None
