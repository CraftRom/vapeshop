"""Bounded customer chat media, persisted through private Telegram file_id.

Never trust filename/MIME from the browser and never expose Telegram file URLs.
MP4 remains the only browser-uploaded video format: it is broadly playable in
Telegram WebView and can be sent via send_video(supports_streaming=True).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import PurePath
from urllib.parse import quote

from fastapi import HTTPException, UploadFile, Response
from aiogram.types import BufferedInputFile

log = logging.getLogger(__name__)
PHOTO_LIMIT = 8 * 1024 * 1024
VIDEO_LIMIT = 15 * 1024 * 1024  # < Telegram bot download limit; proxy checked independently
PDF_LIMIT = 15 * 1024 * 1024
DOWNLOAD_LIMIT = 20 * 1024 * 1024
_DOWNLOAD_SLOTS = asyncio.Semaphore(3)


def clean_filename(name: str | None, default: str) -> str:
    raw = (name or '').replace('\\', '/')
    raw = PurePath(raw).name
    cleaned = ''.join(c for c in raw if c.isprintable() and c not in '/\\<>:"|?*')[:120].strip(' .')
    return cleaned or default


def photo_mime(blob: bytes) -> str | None:
    if blob.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if blob.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if len(blob) >= 12 and blob[:4] == b'RIFF' and blob[8:12] == b'WEBP':
        return 'image/webp'
    return None


def mp4_signature(blob: bytes) -> bool:
    """MP4/M4V ISO BMFF header; no claim that untrusted media is decoded/safe."""
    if len(blob) < 16 or blob[4:8] != b'ftyp':
        return False
    box_size = int.from_bytes(blob[:4], 'big')
    brand = blob[8:12]
    return 16 <= box_size <= len(blob) and all(32 <= x < 127 for x in brand)


def pdf_signature(blob: bytes) -> bool:
    """Minimal signature check, not a malware scan or full PDF parser."""
    return (len(blob) >= 12 and blob[:5] == b'%PDF-'
            and blob[5:8] in {b'1.0', b'1.1', b'1.2', b'1.3', b'1.4',
                              b'1.5', b'1.6', b'1.7', b'2.0'}
            and b'%%EOF' in blob[-4096:])


async def read_chat_upload(file: UploadFile) -> tuple[bytes, str, str, str]:
    filename = clean_filename(file.filename, 'media')
    stated = (file.content_type or '').split(';', 1)[0].lower().strip()
    # An untrusted MIME is only a hint; actual signature is checked below.
    is_video = stated == 'video/mp4' or (stated == 'application/octet-stream' and filename.lower().endswith('.mp4'))
    is_pdf = stated in {'application/pdf', 'application/x-pdf'} or (
        stated in {'', 'application/octet-stream'} and filename.lower().endswith('.pdf')
    )
    if is_pdf:
        blob = await file.read(PDF_LIMIT + 1)
        if len(blob) > PDF_LIMIT:
            raise HTTPException(413, 'PDF завеликий — максимум 15 МБ')
        if not pdf_signature(blob):
            raise HTTPException(422, 'Файл не є коректним PDF')
        stem = filename.rsplit('.', 1)[0] if '.' in filename else filename
        return blob, 'document', 'application/pdf', clean_filename(stem + '.pdf', 'document.pdf')

    if is_video:
        blob = await file.read(VIDEO_LIMIT + 1)
        if len(blob) > VIDEO_LIMIT:
            raise HTTPException(413, 'Відео завелике — максимум 15 МБ')
        if not mp4_signature(blob):
            raise HTTPException(422, 'Відео має бути у форматі MP4 (H.264/AAC рекомендовано)')
        stem = filename.rsplit('.', 1)[0] if '.' in filename else filename
        return blob, 'video', 'video/mp4', clean_filename(stem + '.mp4', 'video.mp4')

    if stated not in {'image/jpeg', 'image/png', 'image/webp'}:
        raise HTTPException(422, 'Можна надіслати JPEG, PNG, WebP, MP4 або PDF. MOV/WebM конвертуйте у MP4')
    blob = await file.read(PHOTO_LIMIT + 1)
    if len(blob) > PHOTO_LIMIT:
        raise HTTPException(413, 'Фото завелике — максимум 8 МБ')
    if not blob or photo_mime(blob) != stated:
        raise HTTPException(422, 'Вміст файлу не відповідає типу фото')
    from api.routers.media import _canonical_image, _DECODE_SLOTS
    from starlette.concurrency import run_in_threadpool
    async with _DECODE_SLOTS:
        try:
            blob, _, mime = await run_in_threadpool(_canonical_image, blob)
        except HTTPException as exc:
            raise HTTPException(422, exc.detail) from exc
    return blob, 'photo', mime, filename


async def send_media_to_staff(bot, repo, file: UploadFile, caption: str):
    """Send before DB mutation; return Telegram file_id for existing models."""
    from shop.services.shop_settings import get_shop_settings
    from shop.services.notifications import topic_kwargs

    shop = await get_shop_settings(repo)
    if not shop.admin_chat_id:
        raise HTTPException(503, 'Чат команди не налаштований — вкладення не збережено')
    blob, kind, mime, name = await read_chat_upload(file)
    media = BufferedInputFile(blob, filename=name)
    try:
        if kind == 'document':
            sent = await bot.send_document(
                shop.admin_chat_id, media, caption=caption,
                disable_content_type_detection=True,
                **topic_kwargs(shop.chat_topic_id or shop.admin_topic_id),
            )
            file_id = getattr(getattr(sent, 'document', None), 'file_id', None)
        elif kind == 'video':
            sent = await bot.send_video(
                shop.admin_chat_id, media, caption=caption,
                supports_streaming=True,
                **topic_kwargs(shop.chat_topic_id or shop.admin_topic_id),
            )
            file_id = getattr(getattr(sent, 'video', None), 'file_id', None)
        else:
            sent = await bot.send_photo(
                shop.admin_chat_id, media, caption=caption,
                **topic_kwargs(shop.chat_topic_id or shop.admin_topic_id),
            )
            file_id = sent.photo[-1].file_id if getattr(sent, 'photo', None) else None
    except Exception as exc:
        log.warning('Cannot send chat media to staff: %s', type(exc).__name__)
        raise HTTPException(502, 'Telegram не прийняв вкладення — спробуйте ще раз') from exc
    if not file_id:
        raise HTTPException(502, 'Telegram не повернув ідентифікатор вкладення')
    return {'file_id': file_id, 'file_kind': kind, 'file_name': name}


async def send_pdf_to_client(bot, chat_id: int, file: UploadFile, caption: str):
    """Staff-only PDF delivery, authenticated in the owning endpoint."""
    blob, kind, mime, name = await read_chat_upload(file)
    if kind != 'document' or mime != 'application/pdf':
        raise HTTPException(422, 'Оберіть PDF-файл')
    try:
        sent = await bot.send_document(
            chat_id, BufferedInputFile(blob, filename=name), caption=caption,
            disable_content_type_detection=True,
        )
    except Exception as exc:
        log.warning('Cannot send PDF to customer: %s', type(exc).__name__)
        raise HTTPException(502, 'Telegram не прийняв PDF. Перевірте доступність бота.') from exc
    file_id = getattr(getattr(sent, 'document', None), 'file_id', None)
    if not file_id:
        raise HTTPException(502, 'Telegram не повернув ідентифікатор PDF')
    return {'file_id': file_id, 'file_kind': 'document', 'file_name': name}, sent


def inline_mime(kind: str, name: str | None) -> str:
    if kind == 'video':
        suffix = (name or '').lower().rsplit('.', 1)[-1]
        return {'webm': 'video/webm', 'mov': 'video/quicktime'}.get(suffix, 'video/mp4')
    return {'photo': 'image/jpeg', 'voice': 'audio/ogg'}.get(kind, 'application/octet-stream')


async def telegram_chat_file_response(bot, target):
    """Bound the upstream download and media type; all owners checked by caller."""
    if not getattr(target, 'file_id', None):
        raise HTTPException(410, 'Вкладення більше недоступне')
    try:
        async with _DOWNLOAD_SLOTS:
            info = await bot.get_file(target.file_id)
            if getattr(info, 'file_size', None) and info.file_size > DOWNLOAD_LIMIT:
                raise HTTPException(413, 'Файл завеликий для отримання через Telegram (понад 20 МБ)')
            content = await bot.download_file(info.file_path)
            blob = content.read(DOWNLOAD_LIMIT + 1)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning('Telegram attachment unavailable: %s', type(exc).__name__)
        raise HTTPException(502, 'Telegram не віддав вкладення') from exc
    if len(blob) > DOWNLOAD_LIMIT:
        raise HTTPException(413, 'Файл завеликий для перегляду в чаті')
    kind = target.file_kind or 'document'
    name = clean_filename(getattr(target, 'file_name', None), 'file')
    headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
               'Content-Disposition': f"inline; filename*=UTF-8''{quote(name, safe='')}"}
    if kind == 'document' and name.lower().endswith('.pdf'):
        if not pdf_signature(blob):
            raise HTTPException(422, 'Вміст вкладення не відповідає формату PDF')
        # Retain attachment disposition for same-origin API. Authenticated
        # clients create their own blob: URL and use a sandboxed PDF preview.
        mime = 'application/pdf'
    else:
        mime = inline_mime(kind, name)
    if kind == 'document':
        # Download rather than executing untrusted document content in this origin.
        headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(name, safe='')}"
    return Response(content=blob, media_type=mime, headers=headers)
