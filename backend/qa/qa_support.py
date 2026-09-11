"""ЗАГАЛЬНА ПІДТРИМКА: /ask → панель → відповідь у Telegram.

Набір не залежить від БД і мережі: середовище CI може не мати aiosqlite та
aiogram. Перевіряємо сервісний контракт через маленький in-memory repo, а
SQL-шар окремо покриває compile/import і штатні repository-тести середовища
деплою.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

os.environ.update(
    BOT_TOKEN="777001:TESTTOKEN",
    JWT_SECRET="t" * 32,
    ADMIN_CHAT_ID="-100111",
    BOT_USERNAME="elfar1_bot",
    MINIAPP_SHORT_NAME="elfar",
    PUBLIC_URL="https://www.elfar.pp.ua",
)

# Мінімальна сумісність aiogram.types: сервісам потрібні лише структури
# клавіатури, а не Telegram-клієнт.
@dataclass
class WebAppInfo:
    url: str

@dataclass
class InlineKeyboardButton:
    text: str
    callback_data: str | None = None
    web_app: WebAppInfo | None = None
    url: str | None = None

@dataclass
class InlineKeyboardMarkup:
    inline_keyboard: list

@dataclass
class KeyboardButton:
    text: str
    web_app: WebAppInfo | None = None

@dataclass
class ReplyKeyboardMarkup:
    keyboard: list
    resize_keyboard: bool = False
    one_time_keyboard: bool = False

@dataclass
class ForceReply:
    selective: bool = False
    input_field_placeholder: str | None = None

if 'aiogram.types' not in sys.modules:
    aiogram = types.ModuleType('aiogram')
    aiogram_types = types.ModuleType('aiogram.types')
    for cls in (WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ForceReply):
        setattr(aiogram_types, cls.__name__, cls)
    aiogram.types = aiogram_types
    sys.modules['aiogram'] = aiogram
    sys.modules['aiogram.types'] = aiogram_types

from api.auth import Principal  # noqa: E402
from api.schemas import SupportThreadOut  # noqa: E402
from qa_common import Report  # noqa: E402
from shop.entities import (  # noqa: E402
    OperatorRole, Order, SupportMessage, SupportThread, User,
)
from shop.services import order_chat, support_chat  # noqa: E402

r = Report("ПІДТРИМКА")


class Repo:
    def __init__(self):
        self.user = User(id=1, tg_id=99001, referral_code='qa12345',
                         username='qa_client', first_name='Клієнт', chat_order_id=777)
        self.threads = []
        self.messages = []
        self.seq = 0
        self.thread_seq = 9

    async def set_chat_order(self, user_id, order_id):
        assert user_id == self.user.id
        self.user.chat_order_id = order_id

    async def get_user(self, user_id):
        return self.user if user_id == self.user.id else None

    async def ensure_support_thread(self, user_id):
        now = datetime.now(timezone.utc)
        current = next((t for t in reversed(self.threads) if t.user_id == user_id and t.status == 'open'), None)
        if current:
            return current
        self.thread_seq += 1
        thread = SupportThread(id=self.thread_seq, user_id=user_id, status='open',
                               created_at=now, updated_at=now, last_message_at=now, user=self.user)
        self.threads.append(thread)
        return thread

    async def get_support_thread_for_user(self, user_id):
        return next((t for t in reversed(self.threads) if t.user_id == user_id and t.status == 'open'), None)

    async def get_support_thread(self, thread_id):
        thread = next((t for t in self.threads if t.id == thread_id), None)
        if not thread:
            return None
        thread.user = self.user
        thread.unread_count = sum(
            1 for m in self.messages if m.thread_id == thread_id and m.direction == 'in' and not m.is_read
        )
        return thread

    async def list_support_threads(self, status=None):
        items = [t for t in self.threads if status is None or t.status == status]
        return [await self.get_support_thread(t.id) for t in reversed(items)]

    async def set_support_thread_status(self, thread_id, status):
        thread = await self.get_support_thread(thread_id)
        if not thread:
            return None
        thread.status = status
        thread.updated_at = datetime.now(timezone.utc)
        return thread

    async def add_support_message(self, data):
        self.seq += 1
        now = datetime.now(timezone.utc)
        msg = SupportMessage(id=self.seq, created_at=now, **data)
        self.messages.append(msg)
        thread = await self.get_support_thread(data['thread_id'])
        thread.last_message_at = now
        thread.updated_at = now
        return msg

    async def list_support_messages(self, thread_id, limit=300):
        return [m for m in self.messages if m.thread_id == thread_id][:limit]

    async def mark_support_read(self, thread_id):
        changed = 0
        for m in self.messages:
            if m.thread_id == thread_id and m.direction == 'in' and not m.is_read:
                m.is_read = True
                changed += 1
        return changed

    async def support_unread_count(self):
        return sum(1 for m in self.messages if m.direction == 'in' and not m.is_read)

    async def support_stats(self):
        return {
            'open': sum(t.status == 'open' for t in self.threads),
            'closed': sum(t.status == 'closed' for t in self.threads),
            'total': len(self.threads),
            'clients': 1 if self.threads else 0,
            'unread': await self.support_unread_count(),
        }

    async def delete_support_thread(self, thread_id):
        before = len(self.threads)
        self.threads = [t for t in self.threads if t.id != thread_id]
        self.messages = [m for m in self.messages if m.thread_id != thread_id]
        return len(self.threads) != before

    async def set_bot_reachable(self, tg_id, reachable):
        assert tg_id == self.user.tg_id
        self.user.bot_reachable = reachable


class FakeBot:
    def __init__(self):
        self.sent = []
        self._id = 100

    async def send_message(self, chat_id, text, **kwargs):
        self._id += 1
        self.sent.append((chat_id, text, kwargs))
        return type("Sent", (), {"message_id": self._id})()


async def scenario():
    repo = Repo()
    bot = FakeBot()

    thread = await support_chat.start(repo, repo.user.id)
    r.check(repo.user.chat_order_id is None, "/ask очищає старий контекст замовлення", repo.user.chat_order_id)
    r.check(thread.status == 'open', "/ask відкриває звернення")

    # Не передаємо bot: групове службове сповіщення не є частиною доставки
    # клієнт↔панель і потребувало б повного settings-repo.
    await support_chat.save_incoming(repo, repo.user, 'Не відкривається кошик')
    r.check(await repo.support_unread_count() == 1, 'нове звернення рахується непрочитаним')

    mode_menu = support_chat.support_keyboard()
    r.check(len(mode_menu.keyboard) == 1 and len(mode_menu.keyboard[0]) == 1
            and mode_menu.keyboard[0][0].text == '✅ Завершити звернення',
            'у /ask лишається тільки кнопка завершення')

    listed = await repo.list_support_threads('open')
    r.check(listed and listed[0].user.tg_id == 99001,
            'панель отримує звернення разом із клієнтом', listed)
    r.check(listed[0].unread_count == 1, 'у списку є лічильник непрочитаних')

    schema = SupportThreadOut.model_validate(listed[0])
    r.check(schema.user is not None and schema.user.tg_id == 99001,
            'API-схема серіалізує вкладеного клієнта', schema)

    changed = await repo.mark_support_read(thread.id)
    r.check(changed == 1 and await repo.support_unread_count() == 0,
            'відкриття діалогу позначає вхідні прочитаними')

    closed = await support_chat.close(repo, repo.user.id)
    r.check(closed and closed.status == 'closed', '/done закриває звернення')
    reopened = await support_chat.start(repo, repo.user.id)
    r.check(reopened.id != thread.id and reopened.status == 'open',
            'наступний /ask створює новий чат, не чіпаючи закриту історію')
    old = await repo.get_support_thread(thread.id)
    r.check(old and old.status == 'closed', 'закритий чат зберігається окремо')
    stats = await repo.support_stats()
    r.check(stats['open'] == 1 and stats['closed'] == 1 and stats['total'] == 2,
            'статистика рахує відкриті й закриті чати окремо', stats)

    order = Order(id=42, user_id=repo.user.id, total=Decimal('800'))
    markup = order_chat.contact_options_keyboard([order])
    order_button = markup.inline_keyboard[0][0]
    r.check(order_button.web_app is not None and '?chat=42' in order_button.web_app.url,
            'кнопка замовлення відкриває чат конкретного замовлення',
            getattr(order_button.web_app, 'url', None))
    r.check(markup.inline_keyboard[-1][0].callback_data == 'support:start',
            'поруч є окрема кнопка загальної підтримки')

    full = await repo.get_support_thread(reopened.id)
    delivered, sent = await support_chat.send_to_client(
        bot, repo, full, 'Перевірте, будь ласка, ще раз.', 'QA менеджер'
    )
    r.check(delivered and sent is not None, 'відповідь менеджера доставлена')
    r.check(any(cid == 99001 and 'Відповідь менеджера' in text
                for cid, text, _ in bot.sent),
            'відповідь пішла саме конкретному клієнту')

    # API endpoint перевіряємо як звичайну async-функцію. Це ще й гарантує,
    # що результат зберігається після успішної Telegram-доставки.
    import api.routers.support as support_api
    support_api._bot = lambda: bot
    result = await support_api.send_message(
        reopened.id,
        type('Body', (), {'text': 'API відповідь'})(),
        Principal('qa', 'QA менеджер', OperatorRole.MANAGER, 123),
        repo,
    )
    r.check(result.delivered is True, 'API-відповідь передається в Telegram')
    r.check(result.message.direction == 'out', 'API зберігає вихідне повідомлення')
    r.check(any(m.text == 'API відповідь' for m in await repo.list_support_messages(reopened.id)),
            'історія містить відповідь із панелі')

    deleted = await support_api.delete_thread(thread.id, repo)
    r.check(deleted is not None and await repo.get_support_thread(thread.id) is None,
            'закритий чат видаляється лише явною дією менеджера')


def static_contracts():
    root = pathlib.Path(__file__).resolve().parents[1]
    handler = (root / 'bot/handlers/chat.py').read_text()
    commands = (root / 'bot/__main__.py').read_text()
    greeting = (root / 'bot/greeting.py').read_text()
    api_main = (root / 'api/main.py').read_text()
    migration = (root / 'alembic/versions/0c5a6d91e7f2_support_sessions.py').read_text()

    r.check('@router.message(Command("ask"))' in handler, '/ask зареєстрована в боті')
    r.check('F.data == "faq:human"' in handler and 'contact_options_keyboard(orders)' in handler,
            'кнопка «Питання менеджеру» показує замовлення та підтримку')
    r.check('if await support.is_active(repo, user.id)' in handler,
            'активний /ask перехоплює наступні повідомлення')
    r.check('BotCommand(command="ask"' in commands and 'BotCommand(command="done"' in commands,
            'команди /ask і /done є в меню Telegram')
    r.check('/ask' in greeting and 'PRIVATE_ONLY_COMMANDS' in greeting,
            '/ask явно позначена як команда лише для приватного чату')
    keyboards = (root / 'bot/keyboards.py').read_text()
    r.check('🆘 Підтримка' in keyboards and '✅ Завершити звернення' in keyboards,
            'reply-меню має вхід у /ask і єдину кнопку завершення в режимі підтримки')
    r.check('include_router(support.router, prefix="/api/support"' in api_main,
            'API підтримки підключений до FastAPI')
    r.check('unique=False' in migration and 'ix_support_threads_user_status_updated' in migration,
            'міграція дозволяє кілька збережених чатів на одного клієнта')


static_contracts()
asyncio.run(scenario())
r.done()
