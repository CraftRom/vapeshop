"""ЖИТТЄВИЙ ЦИКЛ ПІДТРИМКИ: кожний /ask — окрема завершувана сесія.

Ключові інваріанти:
- одночасно у клієнта максимум одна open-сесія;
- повторний /ask під час open продовжує її, а не плодить дублікати;
- closed ніколи не переходить назад в open;
- повідомлення не створює сесію неявно після її закриття;
- наступний /ask після close створює новий thread і лишає стару історію;
- закриття клієнтом і менеджером мають явного автора/причину.
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

# Мінімальні типи aiogram, достатні для сервісів/клавіатур у цьому QA.
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

if "aiogram.types" not in sys.modules:
    aiogram = types.ModuleType("aiogram")
    aiogram_types = types.ModuleType("aiogram.types")
    for cls in (WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ForceReply):
        setattr(aiogram_types, cls.__name__, cls)
    aiogram.types = aiogram_types
    sys.modules["aiogram"] = aiogram
    sys.modules["aiogram.types"] = aiogram_types

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from api.auth import Principal  # noqa: E402
from api.schemas import SupportThreadOut, SupportThreadPatch  # noqa: E402
from qa_common import Report  # noqa: E402
from shop.entities import OperatorRole, Order, SupportMessage, SupportThread, User  # noqa: E402
from shop.services import order_chat, support_chat  # noqa: E402

r = Report("ПІДТРИМКА")


class Repo:
    def __init__(self):
        self.user = User(
            id=1, tg_id=99001, referral_code="qa12345",
            username="qa_client", first_name="Клієнт", chat_order_id=777,
        )
        self.threads: list[SupportThread] = []
        self.messages: list[SupportMessage] = []
        self.seq = 0
        self.thread_seq = 9

    async def set_chat_order(self, user_id, order_id):
        assert user_id == self.user.id
        self.user.chat_order_id = order_id

    async def get_user(self, user_id):
        return self.user if user_id == self.user.id else None

    async def ensure_support_thread(self, user_id):
        current = await self.get_support_thread_for_user(user_id)
        if current:
            return current
        now = datetime.now(timezone.utc)
        self.thread_seq += 1
        thread = SupportThread(
            id=self.thread_seq, user_id=user_id, status="open",
            created_at=now, updated_at=now, last_message_at=now, user=self.user,
        )
        self.threads.append(thread)
        return thread

    async def get_support_thread_for_user(self, user_id):
        return next(
            (t for t in reversed(self.threads) if t.user_id == user_id and t.status == "open"),
            None,
        )

    async def get_support_thread(self, thread_id):
        thread = next((t for t in self.threads if t.id == thread_id), None)
        if not thread:
            return None
        thread.user = self.user
        thread.unread_count = sum(
            1 for m in self.messages
            if m.thread_id == thread_id and m.direction == "in" and not m.is_read
        )
        return thread

    async def list_support_threads(self, status=None):
        items = [t for t in self.threads if status is None or t.status == status]
        return [await self.get_support_thread(t.id) for t in reversed(items)]

    async def close_support_thread(self, thread_id, *, closed_by, closed_by_name="", close_reason=""):
        thread = await self.get_support_thread(thread_id)
        if not thread:
            return None, False
        if thread.status == "closed":
            return thread, False
        now = datetime.now(timezone.utc)
        thread.status = "closed"
        thread.closed_at = now
        thread.closed_by = closed_by
        thread.closed_by_name = closed_by_name or None
        thread.close_reason = close_reason or None
        thread.updated_at = now
        return thread, True

    async def add_support_message(self, data):
        self.seq += 1
        now = datetime.now(timezone.utc)
        msg = SupportMessage(id=self.seq, created_at=now, **data)
        self.messages.append(msg)
        thread = await self.get_support_thread(data["thread_id"])
        if thread:
            thread.last_message_at = now
            thread.updated_at = now
        return msg

    async def add_support_message_if_open(self, data):
        thread = await self.get_support_thread(data["thread_id"])
        if not thread or thread.status != "open":
            return None
        return await self.add_support_message(data)

    async def list_support_messages(self, thread_id, limit=300):
        return [m for m in self.messages if m.thread_id == thread_id][:limit]

    async def mark_support_read(self, thread_id):
        changed = 0
        for msg in self.messages:
            if msg.thread_id == thread_id and msg.direction == "in" and not msg.is_read:
                msg.is_read = True
                changed += 1
        return changed

    async def support_unread_count(self):
        return sum(1 for m in self.messages if m.direction == "in" and not m.is_read)

    async def support_stats(self):
        return {
            "open": sum(t.status == "open" for t in self.threads),
            "closed": sum(t.status == "closed" for t in self.threads),
            "total": len(self.threads),
            "clients": 1 if self.threads else 0,
            "unread": await self.support_unread_count(),
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

    first, created = await support_chat.start(repo, repo.user.id)
    r.check(created and first.status == "open", "перший /ask створює open-сесію")
    r.check(repo.user.chat_order_id is None, "/ask очищає контекст замовлення")

    same, created_again = await support_chat.start(repo, repo.user.id)
    r.check(not created_again and same.id == first.id and len(repo.threads) == 1,
            "повторний /ask продовжує поточну сесію без дубля")

    saved = await support_chat.save_incoming(repo, repo.user, "Не відкривається кошик")
    r.check(saved is not None and saved.thread_id == first.id,
            "повідомлення записується саме в активну сесію")
    r.check(await repo.support_unread_count() == 1, "вхідне рахується непрочитаним")

    closed, changed = await support_chat.close(
        repo, repo.user.id,
        closed_by="client", closed_by_name="Клієнт", close_reason="done",
    )
    r.check(changed and closed.id == first.id and closed.status == "closed",
            "/done закриває конкретну активну сесію")
    r.check(closed.closed_by == "client" and closed.close_reason == "done" and closed.closed_at,
            "закриття зберігає сторону, причину й час")

    late = await support_chat.save_incoming(repo, repo.user, "запізніле повідомлення")
    r.check(late is None and len(repo.threads) == 1,
            "повідомлення після close не створює нову сесію неявно")

    none_thread, changed_again = await support_chat.close(repo, repo.user.id)
    r.check(none_thread is None and not changed_again,
            "повторний /done без open-сесії є безпечним no-op")

    second, second_created = await support_chat.start(repo, repo.user.id)
    r.check(second_created and second.id != first.id and second.status == "open",
            "наступний /ask створює нову окрему сесію")
    old = await repo.get_support_thread(first.id)
    r.check(old.status == "closed", "старий чат лишається закритою історією")
    r.check(sum(t.status == "open" for t in repo.threads) == 1,
            "у клієнта є рівно одна open-сесія")

    schema = SupportThreadOut.model_validate(old)
    r.check(schema.closed_by == "client" and schema.close_reason == "done",
            "API віддає метадані завершення сесії")

    order = Order(id=42, user_id=repo.user.id, total=Decimal("800"))
    markup = order_chat.contact_options_keyboard([order])
    order_button = markup.inline_keyboard[0][0]
    r.check(order_button.web_app is not None and "?chat=42" in order_button.web_app.url,
            "кнопка замовлення веде в чат конкретного замовлення")
    r.check(markup.inline_keyboard[-1][0].callback_data == "support:start",
            "окремо доступний старт загальної підтримки")

    import api.routers.support as support_api
    support_api._bot = lambda: bot
    principal = Principal("qa", "QA менеджер", OperatorRole.MANAGER, 123)

    result = await support_api.send_message(
        second.id,
        type("Body", (), {"text": "API відповідь"})(),
        principal,
        repo,
    )
    r.check(result.delivered is True and result.message.direction == "out",
            "менеджер може відповідати лише в open-сесію")

    # Закриваємо менеджером без повторного відкриття.
    support_api._bot = lambda: None  # у QA не імпортуємо повний bot.keyboards
    patched = await support_api.patch_thread(
        second.id,
        type("Patch", (), {"status": "closed"})(),
        principal,
        repo,
    )
    r.check(patched.status == "closed" and patched.closed_by == "staff" and patched.close_reason == "manager",
            "закриття менеджером фіксується як staff-дія")

    try:
        await support_api.send_message(
            second.id,
            type("Body", (), {"text": "не можна"})(),
            principal,
            repo,
        )
        blocked = False
    except HTTPException as exc:
        blocked = exc.status_code == 409
    r.check(blocked and (await repo.get_support_thread(second.id)).status == "closed",
            "відповідь у closed-сесію блокується й не перевідкриває її")

    try:
        SupportThreadPatch(status="open")
        schema_blocks_reopen = False
    except ValidationError:
        schema_blocks_reopen = True
    r.check(schema_blocks_reopen, "API-схема не приймає reopen closed→open")

    third, third_created = await support_chat.start(repo, repo.user.id)
    r.check(third_created and third.id not in {first.id, second.id},
            "після manager-close новий /ask створює третю, а не оживляє другу сесію")

    stats = await repo.support_stats()
    r.check(stats["open"] == 1 and stats["closed"] == 2 and stats["total"] == 3,
            "статистика рахує сесії окремо", stats)

    deleted = await support_api.delete_thread(first.id, repo)
    r.check(deleted is not None and await repo.get_support_thread(first.id) is None,
            "ручне видалення доступне тільки для вже закритої історії")


def static_contracts():
    root = pathlib.Path(__file__).resolve().parents[1]
    handler = (root / "bot/handlers/chat.py").read_text()
    service = (root / "shop/services/support_chat.py").read_text()
    repo = (root / "shop/repo/sql.py").read_text()
    api = (root / "api/routers/support.py").read_text()
    migration = (root / "alembic/versions/4b8f0c2d91aa_support_lifecycle.py").read_text()
    dashboard = (root.parent / "dashboard/src/pages/Support.jsx").read_text()

    r.check('@router.message(Command("ask"))' in handler, "/ask зареєстрована")
    r.check('add_support_message_if_open' in service and 'ensure_support_thread(user.id)' not in service,
            "звичайне повідомлення не може створити новий thread")
    r.check('.with_for_update()' in repo and 'IntegrityError' in repo,
            "SQL-шар захищає гонки close/message та паралельні /ask")
    r.check('uq_support_threads_one_open_per_user' in migration and "status = 'open'" in migration,
            "БД гарантує максимум одну open-сесію на клієнта")
    r.check('Закриту сесію не можна перевідкрити' in api and 'add_support_message_if_open' in api,
            "API не має неявного reopen")
    r.check('Відкрити знову' not in dashboard and 'Ця сесія завершена' in dashboard,
            "панель не пропонує перевідкриття закритої історії")


static_contracts()
asyncio.run(scenario())
r.done()
