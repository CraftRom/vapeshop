from __future__ import annotations

import logging

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import keyboards as kb
from bot import texts
from bot import faq
from bot.greeting import is_command_trigger, is_private_only_command, send_greeting
from shop.config import settings
from shop.services.shop_settings import current, get_shop_settings
from shop.repo.factory import open_repo
from shop.services.shop_service import get_or_create_user


log = logging.getLogger(__name__)


class RepositoryMiddleware(BaseMiddleware):
    """Відкриває репозиторій і підтягує користувача на кожен апдейт.

    Хендлери отримують `repo` і не знають, Postgres це чи Firestore.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        async with open_repo() as repo:
            data["repo"] = repo
            if tg_user and not tg_user.is_bot:
                user, is_new = await get_or_create_user(
                    repo, tg_user.id, tg_user.username, tg_user.first_name
                )
                data["user"] = user
                data["is_new_user"] = is_new
            return await handler(event, data)


class PrivateOnlyMiddleware(BaseMiddleware):
    """Бот працює лише в особистому листуванні.

    У групі чи каналі відповідь бачать усі присутні, а хендлери віддають
    приватні дані: профіль показує бонусний рахунок і суму витрат, кошик —
    що саме людина набрала, історія — її замовлення з адресою. Тому все,
    що не приватний чат, обривається тут, до роутерів.

    Адмінський чат — не виняток «пропускати все», а вузька щілина: туди
    проходять лише кнопки статусу замовлень і команди персоналу, і лише від
    людей із admin_id_list.

    Раніше з адмінського чату пропускалося геть усе, і наслідок був такий:
    у групі замовлень сидять і звичайні учасники, а до них доходили приватні
    хендлери. Випадкове «Члвлв» отримувало «Щоб написати оператору, потрібне
    активне замовлення», /shop натикався на age gate замість магазину, і бот
    відповідав на кожну репліку в живій розмові.

    Особисті ідентифікатори адміністраторів як дозвіл на чат сюди не додаємо:
    інакше адміністратор, покликавши /stats у сторонній групі, вивалив би
    туди виручку магазину. Перевіряємо обидві умови разом — і чат той, і
    людина та.
    """

    # Команди персоналу, які мають сенс лише в адмінському чаті.
    ADMIN_COMMANDS = ("/stats",)
    # Префікси кнопок, які менеджери натискають під замовленнями.
    ADMIN_CALLBACKS = ("ao:",)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat = data.get("event_chat")
        if chat is None or chat.type == "private":
            return await handler(event, data)

        # current() — синхронний знімок кешу: репозиторій тут ще не відкрито
        admin_chat_id = current().admin_chat_id
        tg_user = data.get("event_from_user")
        is_staff = bool(tg_user and tg_user.id in current().admin_id_list)
        in_admin_chat = bool(admin_chat_id and chat.id == admin_chat_id)

        if in_admin_chat and is_staff:
            if isinstance(event, CallbackQuery):
                if event.data and event.data.startswith(self.ADMIN_CALLBACKS):
                    return await handler(event, data)
            elif isinstance(event, Message):
                text = event.text or ""
                if any(text.lower().startswith(cmd) for cmd in self.ADMIN_COMMANDS):
                    return await handler(event, data)
            # Решта — звичайна розмова в групі, навіть якщо пише менеджер.
            # Далі йде та сама логіка, що й для будь-якого публічного чату.

        # Натискання кнопки в групі: коротка підказка тому, хто натиснув,
        # без повідомлення в сам чат
        if isinstance(event, CallbackQuery):
            await event.answer(
                "Магазин працює лише в особистому чаті з ботом", show_alert=True
            )
            return None

        if not isinstance(event, Message):
            return None

        text = event.text or event.caption or ""

        # /shop — єдина публічна команда. Відповідаємо завжди: людина
        # свідомо покликала магазин.
        if is_command_trigger(text):
            await send_greeting(event)
            return None

        # Приватна команда в групі (/start, /cart, /profile…). Мовчимо
        # свідомо: /start у групу надсилає за звичкою чи не кожен новачок,
        # і відповідь на кожен такий випадок була б спамом.
        if is_private_only_command(text):
            log.debug("Приватна команда в публічному чаті %s — ігнорую", chat.id)
            return None

        # Реакція на ключові слова — така сама, як у приватному чаті.
        #
        # Раніше бот відповідав лише на пряму згадку, і в групі виглядав
        # мертвим: людина питає «яка доставка», а він мовчить, хоч відповідь
        # знає. Тепер правило спрацьовує від самого питання.
        #
        # У публічний чат ідуть лише загальні правила й лише в стислій формі.
        # Персональне — статус замовлення, бонусний рахунок, реферальне
        # посилання, вміст кошика — не йде туди взагалі: його побачили б усі
        # присутні, включно з випадковими людьми й тими, кого додадуть пізніше.
        mentioned = _mentions_bot(event)

        # Звернулися до іншого бота — не встрягаємо. У групах їх часто кілька,
        # і перехоплювати чужу розмову гірше, ніж змовчати.
        if not mentioned and _mentions_other_bot(text):
            return None

        rule = faq.match(text, current(), public=True)

        # Привітання й подяки — соціальний шум, а не питання. Відповідаємо на
        # них лише коли звернулися прямо: інакше бот вітався б із кожним, хто
        # написав «привіт» у групу, і це знову був би спам.
        if rule and rule.key in SOCIAL_KEYS and not mentioned:
            return None

        if rule:
            # Пряма згадка — відповідаємо завжди: до бота звернулися особисто.
            # Без згадки тримаємо паузу на тему: у розмові про доставку слово
            # «доставка» звучить десять разів поспіль, і десять однакових
            # відповідей — це той самий спам, тільки доречний за змістом.
            if mentioned or _may_speak(chat.id, rule.key, getattr(tg_user, "id", None)):
                await _reply_public(event, rule)
            return None

        # Нічого конкретного. Мовчимо — крім випадку, коли бота покликали
        # явно: залишити пряме звернення без відповіді було б неввічливо.
        if mentioned and _may_speak(chat.id, "fallback", getattr(tg_user, "id", None)):
            await _reply_public(event, None)

        return None


def _mentions_other_bot(text: str) -> bool:
    """Чи адресоване повідомлення іншому боту."""
    import re

    username = (current().bot_username or "").lstrip("@").lower()
    # \w, а не [a-z0-9_]: у тестах і в реальних чатах трапляються згадки
    # кирилицею. Telegram таких імен не видає, але текст із ними приходить,
    # і адресоване не нам повідомлення лишається адресованим не нам.
    for found in re.findall(r"@(\w{3,})", text, flags=re.UNICODE):
        if found.lower() != username:
            return True
    return False


def _mentions_bot(event) -> bool:
    """Чи покликали саме нашого бота."""
    username = (current().bot_username or "").lstrip("@").lower()
    text = (event.text or event.caption or "").lower()
    return bool(username) and f"@{username}" in text


# Пауза для однієї людини на одну тему. Той самий учасник, який тричі
# поспіль перепитує про замовлення, отримає відповідь один раз.
PUBLIC_COOLDOWN = 300

# Нижня межа між будь-якими двома відповідями в чаті. Захист від випадку,
# коли тему підхоплюють кілька людей одночасно: відповідь потрібна кожному,
# але не чергою в один рядок.
CHAT_FLOOR = 15

# Правила, які без прямої згадки не спрацьовують: це ввічливість у розмові
# між людьми, а не запит до магазину.
SOCIAL_KEYS = frozenset({"greeting", "thanks"})
_last_fallback: dict[tuple, float] = {}


def _may_speak(chat_id: int, topic: str, user_id: int | None = None) -> bool:
    """Чи можна відповісти зараз на цю тему в цьому чаті.

    Пауза рахується на трійку «чат + тема + людина», а не на чат цілком.
    Причина видно на живому прикладі: людина питає «як купити», через
    хвилину інша питає те саме — і другій бот мовчав би, хоч вона питає
    вперше. Питання кожного учасника заслуговує на відповідь.

    Тема окремо від теми: питання про доставку не має затикати відповідь
    про оплату, яка прозвучить хвилиною пізніше.
    """
    import time

    now = time.monotonic()

    # Нижня межа на чат: якщо тему підхопили кілька людей одночасно,
    # відповіді підуть, але не суцільним стовпчиком.
    floor_key = (chat_id, "*floor*")
    last_any = _last_fallback.get(floor_key)
    if last_any is not None and now - last_any < CHAT_FLOOR:
        return False

    key = (chat_id, topic, user_id)
    previous = _last_fallback.get(key)
    # Дефолт 0.0 тут був би помилкою: monotonic() відлічує від старту
    # системи, і в перші хвилини після перезавантаження різниця з нулем
    # менша за паузу — бот мовчав би на перше ж звернення в кожному чаті.
    if previous is not None and now - previous < PUBLIC_COOLDOWN:
        return False

    _last_fallback[key] = now
    _last_fallback[floor_key] = now
    # Словник живе в памʼяті процесу й не росте безмежно: чатів у магазину
    # одиниці, а перезапуск просто скидає лічильники.
    return True


async def _reply_public(event, rule) -> None:
    """Відповідь у групу: загальний текст плюс кнопка в особистий чат.

    rule=None — конкретної відповіді немає, шлемо коротку переадресацію.
    """
    from bot import keyboards as kb

    if rule is not None:
        body = (
            faq.render(rule, current(), public=True)
            + "\n\n<i>Замовлення й особисті питання — в особистому чаті.</i>"
        )
    else:
        body = texts.PUBLIC_FALLBACK

    try:
        await event.answer(body, reply_markup=kb.to_private_chat())
    except Exception:
        # У каналі бот може не мати права писати — це не збій застосунку
        log.info("Не вдалося відповісти в публічному чаті", exc_info=True)


class AgeGateMiddleware(BaseMiddleware):
    """Нікотинові товари — 18+. Поки вік не підтверджено, доступний лише age gate.

    Персонал пропускаємо: адміністратор керує замовленнями, а не купує. Інакше
    менеджер, який не заходив у бот як покупець, не міг би ні натиснути кнопку
    статусу в адмін-чаті, ні викликати /stats — а сама група отримувала б
    повідомлення про підтвердження віку.
    """

    ALLOWED_CALLBACKS = ("age:",)

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("user")
        if user is None or user.age_confirmed:
            return await handler(event, data)

        tg_user = data.get("event_from_user")
        if tg_user and tg_user.id in current().admin_id_list:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            if event.data and event.data.startswith(self.ALLOWED_CALLBACKS):
                return await handler(event, data)
            await event.answer("Спочатку підтвердьте вік", show_alert=True)
            return None

        if isinstance(event, Message):
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)
            repo = data.get("repo")
            shop = await get_shop_settings(repo) if repo else None
            min_age = shop.min_age if shop else None
            await event.answer(texts.age_gate(min_age), reply_markup=kb.age_gate())
            return None

        return await handler(event, data)


class BlockedUserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("user")
        if user is not None and user.is_blocked:
            if isinstance(event, CallbackQuery):
                await event.answer("Доступ обмежено", show_alert=True)
            return None
        return await handler(event, data)
