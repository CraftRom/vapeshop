from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.auth import Principal, require_staff
from api.schemas import (
    SupportMessageIn, SupportMessageOut, SupportMessageResult,
    SupportThreadOut, SupportThreadPatch,
)
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services import support_chat

router = APIRouter(dependencies=[Depends(require_staff)])
log = logging.getLogger(__name__)


def _bot():
    try:
        from api.routers.telegram import _instances

        bot, _ = _instances()
        return bot
    except Exception:
        log.warning("Бот недоступний — відповідь підтримки не буде доставлена", exc_info=True)
        return None


@router.get("", response_model=list[SupportThreadOut])
async def list_threads(
    status: str | None = Query("open", pattern=r"^(open|closed|all)$"),
    repo: Repository = Depends(get_repo),
):
    return await repo.list_support_threads(None if status == "all" else status)


@router.get("/unread/count")
async def unread_count(repo: Repository = Depends(get_repo)):
    return {"count": await repo.support_unread_count()}


@router.get("/{thread_id}", response_model=SupportThreadOut)
async def get_thread(thread_id: int, repo: Repository = Depends(get_repo)):
    thread = await repo.get_support_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Звернення не знайдено")
    return thread


@router.patch("/{thread_id}", response_model=SupportThreadOut)
async def patch_thread(
    thread_id: int,
    data: SupportThreadPatch,
    repo: Repository = Depends(get_repo),
):
    thread = await repo.set_support_thread_status(thread_id, data.status)
    if not thread:
        raise HTTPException(404, "Звернення не знайдено")
    return thread


@router.get("/{thread_id}/messages", response_model=list[SupportMessageOut])
async def messages(
    thread_id: int,
    mark_read: bool = False,
    repo: Repository = Depends(get_repo),
):
    if not await repo.get_support_thread(thread_id):
        raise HTTPException(404, "Звернення не знайдено")
    if mark_read:
        await repo.mark_support_read(thread_id)
    return await repo.list_support_messages(thread_id)


@router.post("/{thread_id}/messages", response_model=SupportMessageResult, status_code=201)
async def send_message(
    thread_id: int,
    data: SupportMessageIn,
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    thread = await repo.get_support_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Звернення не знайдено")

    # Відповідь із закритої картки автоматично повертає її в роботу. Це
    # краще, ніж дати менеджеру написати клієнту й лишити чат у «Закритих».
    if thread.status != "open":
        thread = await repo.set_support_thread_status(thread_id, "open")

    author = who.name or who.login
    delivered = False
    sent = None
    bot = _bot()
    if bot and thread:
        delivered, sent = await support_chat.send_to_client(
            bot, repo, thread, data.text, author
        )

    saved = await repo.add_support_message({
        "thread_id": thread_id,
        "user_id": thread.user_id,
        "direction": "out",
        "author": author,
        "text": data.text,
        "tg_message_id": getattr(sent, "message_id", None),
        # Вихідне повідомлення не є «непрочитаним для менеджера».
        "is_read": True,
    })

    return SupportMessageResult(
        message=saved,
        delivered=delivered,
        warning=None if delivered else (
            "Повідомлення збережено, але Telegram не підтвердив доставку клієнту."
        ),
    )


@router.get("/{thread_id}/files/{message_id}")
async def support_file(
    thread_id: int,
    message_id: int,
    repo: Repository = Depends(get_repo),
):
    if not await repo.get_support_thread(thread_id):
        raise HTTPException(404, "Звернення не знайдено")
    messages = await repo.list_support_messages(thread_id)
    target = next((m for m in messages if m.id == message_id), None)
    if not target:
        raise HTTPException(404, "Вкладення не знайдено")
    if not target.file_id:
        raise HTTPException(410, "Вкладення більше недоступне")

    bot = _bot()
    if not bot:
        raise HTTPException(503, "Бот недоступний — файл не отримати")
    try:
        info = await bot.get_file(target.file_id)
        content = await bot.download_file(info.file_path)
    except Exception:
        log.warning("Не вдалося отримати файл підтримки %s", target.file_id, exc_info=True)
        raise HTTPException(502, "Telegram не віддав файл")

    media = {"photo": "image/jpeg", "video": "video/mp4", "voice": "audio/ogg"}
    return Response(
        content=content.read(),
        media_type=media.get(target.file_kind, "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{target.file_name or "file"}"'},
    )
