"""Зберігання зображень на власному сервері.

Раніше картинку можна було лише вказати посиланням на чужий хостинг. Це
працює рівно доти, доки той хостинг живий: коли він зникає, каталог
залишається без фото, і дізнаєтесь ви про це від клієнта.

Файли лягають у MEDIA_DIR, віддає їх nginx напряму — застосунок у цьому
не бере участі, бо перекладати мегабайти через Python немає сенсу.
"""
from __future__ import annotations

import hashlib
import asyncio
import os
import tempfile
import warnings
from io import BytesIO
from PIL import Image, ImageSequence, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.auth import Principal, require_staff

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
Image.MAX_IMAGE_PIXELS = 20_000_000
_DECODE_SLOTS = asyncio.Semaphore(2)


def _media_dir() -> Path:
    """Каталог медіа. Шлях фіксований — див. shop.paths."""
    from shop.paths import media_dir

    return media_dir()



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


def _canonical_image(raw: bytes) -> tuple[bytes, str, str]:
    """Decode bounded raster images, discard EXIF/comments and appended payloads."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=["JPEG", "PNG", "GIF", "WEBP"]) as image:
                fmt = image.format
                width, height = image.size
                count = getattr(image, "n_frames", 1)
                if width > 8192 or height > 8192 or width * height > 20_000_000 or count > 100 or width * height * count > 32_000_000:
                    raise ValueError("image limits")
                frames, durations = [], []
                for frame in ImageSequence.Iterator(image):
                    frame.load()
                    clean = Image.new("RGB" if fmt == "JPEG" else "RGBA", frame.size)
                    clean.paste(frame.convert(clean.mode))
                    frames.append(clean)
                    durations.append(max(10, min(60000, int(frame.info.get("duration", 100)))))
                output = BytesIO()
                if count > 1 and fmt in ("GIF", "WEBP"):
                    frames[0].save(output, format=fmt, save_all=True, append_images=frames[1:], duration=durations, loop=0)
                else:
                    frames[0].save(output, format=fmt)
                content = output.getvalue()
                if len(content) > MAX_BYTES:
                    raise ValueError("encoded size")
                extension, mime = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "GIF": ("gif", "image/gif"), "WEBP": ("webp", "image/webp")}[fmt]
                return content, extension, mime
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(415, "Зображення пошкоджене або перевищує межі: 20 Мп, 8192 px, 100 кадрів / 32 Мп сумарно")


def _store_image(target: Path, content: bytes) -> bool:
    if target.is_symlink():
        raise HTTPException(400, "Неприпустимий файл")
    if target.exists():
        return True
    fd, temporary = tempfile.mkstemp(prefix=".image-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return False


@router.post("", status_code=201)
async def upload(file: UploadFile = File(...), who: Principal = Depends(require_staff)):
    chunks, total = [], 0
    while chunk := await file.read(256 * 1024):
        total += len(chunk)
        if total > MAX_BYTES:
            raise HTTPException(413, "Файл більший за 8 МБ")
        chunks.append(chunk)
    async with _DECODE_SLOTS:
        content, extension, mime = await run_in_threadpool(_canonical_image, b"".join(chunks))
        name = _safe_name(file.filename or "", hashlib.sha256(content).hexdigest(), extension)
        target = _media_dir() / name
        reused = await run_in_threadpool(_store_image, target, content)
    return {**_describe(target), "mime": mime, "reused": reused}


@router.get("")
async def library(
    limit: int = 100,
    who: Principal = Depends(require_staff),
):
    """Уже завантажені зображення, найновіші першими."""
    directory = _media_dir()
    files = [p for p in directory.iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"} and not p.name.startswith(".")]
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
