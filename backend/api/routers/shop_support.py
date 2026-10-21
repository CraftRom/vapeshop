"""Customer-owned general support; the same threads as Telegram /ask and CRM."""
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from typing import Annotated
from html.parser import HTMLParser
from pydantic import BaseModel, ConfigDict, Field, field_validator
from api.webapp_auth import require_webapp_user
from shop.repo.factory import get_repo
from shop.services import support_chat
from shop.services.panel_notifications import safe_publish

router = APIRouter()
ID = Annotated[int, Path(gt=0, le=9223372036854775807)]

class SendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    request_id: str = Field(min_length=16, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')

    @field_validator('text')
    @classmethod
    def clean(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Повідомлення не може бути порожнім')
        return value

def thread_out(thread):
    return {key: getattr(thread, key) for key in ('id','status','created_at','last_message_at','closed_at')}

def message_out(message):
    result = {key: getattr(message, key) for key in ('id','thread_id','direction','author','text','created_at','file_kind','file_name')}
    if message.is_automatic:
        class Plain(HTMLParser):
            def handle_data(self, data):
                chunks.append(data)
        chunks = []
        parser = Plain(convert_charrefs=True)
        parser.feed(message.text)
        result['text'] = ''.join(chunks)
    return result

async def own(repo, user, thread_id):
    thread = await repo.get_support_thread(thread_id)
    if thread is None or thread.user_id != user.id:
        raise HTTPException(404, 'Звернення не знайдено')
    return thread

@router.get('/threads')
async def threads(before_id: int | None = Query(None, gt=0, le=9223372036854775807), limit: int = Query(20, ge=1, le=50),
                  user=Depends(require_webapp_user), repo=Depends(get_repo)):
    items = await repo.list_user_support_threads(user.id, before_id, limit)
    return {'items': [thread_out(x) for x in items], 'has_more': len(items) == limit}

@router.post('/threads', status_code=201)
async def start(user=Depends(require_webapp_user), repo=Depends(get_repo)):
    # Only explicit creation/continuation enters support, as does Telegram /ask.
    # Merely reading the list/history has no routing side effects.
    thread, _ = await support_chat.start(repo, user.id)
    return thread_out(thread)

@router.get('/threads/{thread_id}')
async def get(thread_id: ID, user=Depends(require_webapp_user), repo=Depends(get_repo)):
    return thread_out(await own(repo, user, thread_id))

@router.get('/threads/{thread_id}/messages')
async def messages(thread_id: ID, before_id: int | None = Query(None, gt=0, le=9223372036854775807),
                   after_id: int | None = Query(None, ge=0, le=9223372036854775807), limit: int = Query(200, ge=1, le=200),
                   user=Depends(require_webapp_user), repo=Depends(get_repo)):
    thread = await own(repo, user, thread_id)
    if before_id is not None and after_id is not None:
        raise HTTPException(422, 'Оберіть один напрямок історії')
    items = await repo.page_support_messages(thread_id, before_id, after_id, limit)
    return {'thread': thread_out(thread), 'items': [message_out(x) for x in items], 'has_more': len(items) == limit}

@router.post('/threads/{thread_id}/messages', status_code=201)
async def send(thread_id: ID, data: SendIn, user=Depends(require_webapp_user), repo=Depends(get_repo)):
    await own(repo, user, thread_id)
    try:
        saved = await repo.add_support_client_message(thread_id, user, data.text, data.request_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if saved is None:
        raise HTTPException(409, 'Звернення вже завершено. Створіть нове звернення.')
    if not getattr(saved, 'client_replayed', False):
        await safe_publish(repo, 'support.message', f'Нове повідомлення в підтримку · #{thread_id}',
                           data.text, href=f'/support?thread={thread_id}', entity_id=thread_id,
                           actor=user.first_name or user.username or str(user.tg_id))
        from api.routers.support import _bot
        bot = _bot()
        if bot is not None:
            await support_chat._notify_staff(bot, repo, thread_id, user, data.text)
    return message_out(saved)

@router.post('/threads/{thread_id}/close')
async def close(thread_id: ID, user=Depends(require_webapp_user), repo=Depends(get_repo)):
    await own(repo, user, thread_id)
    thread, _ = await repo.close_support_thread(thread_id, closed_by='client',
        closed_by_name=user.first_name or 'Клієнт', close_reason='miniapp')
    if thread is None:
        raise HTTPException(404, 'Звернення не знайдено')
    return thread_out(thread)

@router.get('/threads/{thread_id}/files/{message_id}')
async def file(thread_id: ID, message_id: ID, user=Depends(require_webapp_user), repo=Depends(get_repo)):
    await own(repo, user, thread_id)
    # Reuse Telegram file proxy and its retention/error behavior.
    from api.routers.support import support_file
    return await support_file(thread_id, message_id, repo)
