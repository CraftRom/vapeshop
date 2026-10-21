from __future__ import annotations

import logging
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, Path

from api.auth import Principal, require_staff
from api.schemas import (
    MessageReadIn,
    SupportMessageIn, SupportMessageOut, SupportMessageResult,
    SupportStatsOut, SupportThreadOut, SupportThreadPatch,
)
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services import support_chat

router = APIRouter(dependencies=[Depends(require_staff)])
log = logging.getLogger(__name__)
SupportID = Annotated[int, Path(gt=0, le=2147483647)]


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


@router.get("/stats", response_model=SupportStatsOut)
async def stats(repo: Repository = Depends(get_repo)):
    return await repo.support_stats()


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
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    current = await repo.get_support_thread(thread_id)
    if not current:
        raise HTTPException(404, "Звернення не знайдено")
    # Закрита сесія є історією й ніколи не перевідкривається. Нове
    # звернення створює тільки клієнт явною командою /ask.
    if data.status != "closed":
        raise HTTPException(409, "Закриту сесію не можна перевідкрити. Клієнт має створити нове звернення через /ask.")

    author = who.name or who.login
    thread, changed = await repo.close_support_thread(
        thread_id,
        closed_by="staff",
        closed_by_name=author,
        close_reason="manager",
    )
    if not thread:
        raise HTTPException(404, "Звернення не знайдено")

    # Повторне натискання «Закрити» є idempotent: статус не змінюємо вдруге
    # і не шлемо клієнту дубль повідомлення.
    if changed:
        bot = _bot()
        if bot:
            try:
                from bot import keyboards as bot_keyboards
                await support_chat.notify_closed_by_staff(
                    bot, repo, thread, author, reply_markup=bot_keyboards.main_menu()
                )
            except Exception:
                log.warning("Не вдалося сповістити клієнта про закриття звернення %s", thread_id, exc_info=True)
    return thread


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: int,
    repo: Repository = Depends(get_repo),
):
    thread = await repo.get_support_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Звернення не знайдено")
    if thread.status != "closed":
        raise HTTPException(409, "Спершу закрийте звернення, потім його можна видалити")
    if not await repo.delete_support_thread(thread_id):
        raise HTTPException(404, "Звернення не знайдено")
    return Response(status_code=204)


@router.get("/{thread_id}/messages", response_model=list[SupportMessageOut])
async def messages(
    thread_id: SupportID,
    mark_read: bool = False,
    before_id: int | None = Query(None, gt=0, le=2147483647),
    after_id: int | None = Query(None, ge=0, le=2147483647),
    limit: int | None = Query(None, ge=1, le=200),
    repo: Repository = Depends(get_repo),
):
    if not await repo.get_support_thread(thread_id):
        raise HTTPException(404, "Звернення не знайдено")
    if before_id is not None and after_id is not None:
        raise HTTPException(422, "Оберіть один напрямок історії")
    # Preserve the old 300-message response for clients without cursors/limit.
    if before_id is None and after_id is None and limit is None:
        items = await repo.list_support_messages(thread_id)
    else:
        items = await repo.page_support_messages(thread_id, before_id, after_id, limit or 200)
    if mark_read:
        await repo.mark_support_message_ids_read(thread_id, [item.id for item in items])
        for item in items:
            if item.direction == 'in':
                item.is_read = True
    return items


@router.post("/{thread_id}/messages/read")
async def read_messages(thread_id: SupportID, data: MessageReadIn, repo: Repository = Depends(get_repo)):
    if not await repo.get_support_thread(thread_id):
        raise HTTPException(404, "Звернення не знайдено")
    if any(x > 2147483647 for x in data.message_ids):
        raise HTTPException(422, "ID повідомлення поза допустимим діапазоном")
    return {"marked": await repo.mark_support_message_ids_read(thread_id, data.message_ids)}


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

    if thread.status != "open":
        raise HTTPException(
            409,
            "Це звернення вже закрито. Історія незмінна; нове звернення клієнт створює через /ask.",
        )

    author = who.name or who.login
    # Спочатку атомарно фіксуємо відповідь у ще відкритій сесії. Якщо
    # клієнт або інший менеджер закрив її паралельно, запис не пройде й
    # Telegram-повідомлення не буде відправлено в завершений чат.
    saved = await repo.add_support_message_if_open({
        "thread_id": thread_id,
        "user_id": thread.user_id,
        "direction": "out",
        "author": author,
        "text": data.text,
        "tg_message_id": None,
        "is_read": True,
    })
    if saved is None:
        raise HTTPException(409, "Звернення вже закрито. Оновіть сторінку.")

    delivered = False
    sent = None
    bot = _bot()
    if bot:
        delivered, sent = await support_chat.send_to_client(
            bot, repo, thread, data.text, author
        )

    return SupportMessageResult(
        message=saved,
        delivered=delivered,
        warning=None if delivered else (
            "Повідомлення доступне у Mini App, але Telegram не підтвердив доставку клієнту."
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
    target = await repo.get_support_message(thread_id, message_id)
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
        headers={
            "Content-Disposition":
                f"inline; filename*=UTF-8''{quote((target.file_name or 'file')[:255], safe='')}"
        },
    )
