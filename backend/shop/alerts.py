"""Сповіщення про помилки в Telegram.

Єдина точка: усе, що потрапляє в журнал рівнем ERROR і вище — з API, бота
чи планувальника — приходить у гілку адмінського каналу. Окремої системи
моніторингу тут не заводимо: журнал уже збирає всі помилки, лишається
лише переслати їх туди, де їх побачать.

Три речі, без яких таке сповіщення шкодить більше, ніж допомагає:

  • Дедуплікація. Одна поломка бази дає сотні однакових трейсбеків за
    хвилину. Без згортання канал перетворюється на стрічку, у якій нічого
    не видно, і сповіщення починають ігнорувати — саме тоді, коли вони
    потрібні.

  • Обмеження частоти. Telegram не приймає більше ~20 повідомлень на
    хвилину в одну групу, і надлишок повертається помилкою — яка сама
    піде в журнал і спричинить наступну спробу.

  • Захист від рекурсії. Помилка відправки не має логуватись як помилка,
    інакше кожна невдача породжує нову.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import deque

log = logging.getLogger("alerts")

# Скільки секунд мовчати про повторення тієї самої помилки.
DEDUP_WINDOW = 600

# Скільки повідомлень максимум за хвилину. Нижче межі Telegram із запасом:
# впертися в неї означало б втратити саме те сповіщення, яке важливе.
RATE_LIMIT = 10

MAX_TEXT = 3500


class TelegramErrorHandler(logging.Handler):
    """Обробник журналу, що пересилає помилки в гілку каналу."""

    def __init__(self, service: str) -> None:
        super().__init__(level=logging.ERROR)
        self.service = service
        self._seen: dict[str, float] = {}
        self._sent: deque[float] = deque()
        # Прапорець рекурсії: поки відправляємо, власні помилки ігноруємо.
        self._sending = False

    # ---------------------------------------------------------- фільтри

    def _fingerprint(self, record: logging.LogRecord) -> str:
        """Відбиток помилки: місце в коді плюс тип винятку.

        Саме місце, а не текст: у тексті бувають ідентифікатори замовлень
        і час, і тоді кожен повтор виглядав би новою помилкою.
        """
        kind = record.exc_info[0].__name__ if record.exc_info else record.levelname
        raw = f"{record.pathname}:{record.lineno}:{kind}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _is_repeat(self, fingerprint: str, now: float) -> bool:
        previous = self._seen.get(fingerprint)
        if previous is not None and now - previous < DEDUP_WINDOW:
            return True
        self._seen[fingerprint] = now
        # Прибираємо старе, щоб словник не ріс безмежно за тижні роботи.
        if len(self._seen) > 500:
            cutoff = now - DEDUP_WINDOW
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}
        return False

    def _rate_exceeded(self, now: float) -> bool:
        while self._sent and now - self._sent[0] > 60:
            self._sent.popleft()
        if len(self._sent) >= RATE_LIMIT:
            return True
        self._sent.append(now)
        return False

    # ----------------------------------------------------------- формат

    def _compose(self, record: logging.LogRecord) -> str:
        parts = [
            f"🔴 <b>{self.service}</b> · {record.levelname}",
            "",
            f"<b>{_escape(record.getMessage())[:400]}</b>",
        ]

        request_id = getattr(record, "requestId", "")
        if request_id:
            parts.append(f"\nЗапит: <code>{_escape(str(request_id))}</code>")
        for field in ("path", "method", "status", "actor", "event"):
            value = getattr(record, field, "")
            if value not in ("", None):
                parts.append(f"{field}: <code>{_escape(str(value))}</code>")

        if record.exc_info:
            text = logging.Formatter().formatException(record.exc_info)
            # Хвіст трейсбека, а не початок: причина завжди в кінці, а
            # початок — це однаковий стек фреймворка.
            tail = text[-1200:]
            parts.append(f"\n<pre>{_escape(tail)}</pre>")

        return "\n".join(parts)[:MAX_TEXT]

    # ------------------------------------------------------------ вихід

    def emit(self, record: logging.LogRecord) -> None:
        if self._sending:
            return
        try:
            now = time.monotonic()
            fingerprint = self._fingerprint(record)
            if self._is_repeat(fingerprint, now):
                return
            if self._rate_exceeded(now):
                return

            text = self._compose(record)
            loop = asyncio.get_running_loop()
            # Створюємо задачу, а не чекаємо: обробник журналу викликається
            # синхронно з коду, який уже щось робить, і блокувати його
            # мережевим запитом не можна.
            loop.create_task(self._deliver(text))
        except RuntimeError:
            # Немає активного циклу подій — сповіщення пропускаємо. У журнал
            # запис однаково потрапив, а це головне.
            pass
        except Exception:
            pass

    async def _deliver(self, text: str) -> None:
        self._sending = True
        try:
            from shop.config import settings
            from shop.services.shop_settings import current

            shop = current()
            chat_id = shop.admin_chat_id
            topic_id = shop.error_topic_id
            if not chat_id or not settings.bot_token:
                return

            import httpx

            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if topic_id:
                payload["message_thread_id"] = topic_id

            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                    json=payload,
                )
        except Exception:
            # Мовчки: інакше невдала відправка сповіщення про помилку
            # породжує нову помилку, і так по колу.
            pass
        finally:
            self._sending = False


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def attach(service: str) -> TelegramErrorHandler | None:
    """Підключає сповіщення до кореневого журналу."""
    handler = TelegramErrorHandler(service)
    logging.getLogger().addHandler(handler)
    return handler


class TelegramSecurityHandler(TelegramErrorHandler):
    """Сповіщення про події безпеки.

    Успадковує від обробника помилок заради дедуплікації, обмеження
    частоти й захисту від рекурсії — без них будь-яке сповіщення шкодить
    більше, ніж допомагає, і переписувати це вдруге немає сенсу.

    Відрізняється трьома речами. Рівень запису тут ні до чого: невдалий
    вхід нічого не ламає, тож пишеться як INFO, але знати про нього
    треба. Відбір іде за власним рівнем критичності події. Відбиток
    рахується за кодом події й адресою, а не за місцем у коді: сто спроб
    підбору з одного місця в коді — це одна подія, а з різних адрес уже
    сто, і згортати їх в одну не можна.
    """

    def __init__(self, service: str) -> None:
        # NOTSET: рівень запису тут нічого не вирішує, відбір нижче
        logging.Handler.__init__(self, level=logging.NOTSET)
        self.service = service
        self._seen = {}
        self._sent = deque()
        self._sending = False

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "security", False):
            return False
        from shop.security_log import ALERT_FROM, SEVERITIES

        severity = getattr(record, "severity", "notice")
        try:
            return SEVERITIES.index(severity) >= SEVERITIES.index(ALERT_FROM)
        except ValueError:
            return True

    def _fingerprint(self, record: logging.LogRecord) -> str:
        # Код події плюс адреса: підбір з десяти адрес має дати десять
        # сповіщень, а не одне. Логін навмисно не входить — інакше перебір
        # логінів з однієї адреси знову розсипався б на сотні сповіщень.
        raw = f"{getattr(record, 'event', '')}:{getattr(record, 'ip', '')}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _compose(self, record: logging.LogRecord) -> str:
        severity = getattr(record, "severity", "notice")
        mark = {"alarm": "🚨", "notice": "⚠️", "info": "ℹ️"}.get(severity, "⚠️")

        parts = [
            f"{mark} <b>Безпека</b> · {self.service}",
            "",
            f"<b>{_escape(record.getMessage())}</b>",
        ]

        detail = getattr(record, "detail", "")
        if detail:
            # Опис події, а не лише код: сповіщення читають з телефона й
            # найчастіше не ті, хто писав цей код.
            parts.append(f"\n{_escape(detail)}")

        # Порядок полів фіксований і від загального до конкретного: спершу
        # хто й звідки, потім куди саме звертались.
        labels = (
            ("actor", "Хто"),
            ("login", "Логін"),
            ("ip", "Адреса"),
            ("role", "Роль"),
            ("path", "Шлях"),
            ("method", "Метод"),
            ("reason", "Причина"),
            ("attempts", "Спроб поспіль"),
            ("requestId", "Запит"),
        )
        rows = []
        for field, label in labels:
            value = getattr(record, field, "")
            if value not in ("", None):
                rows.append(f"{label}: <code>{_escape(str(value))}</code>")
        if rows:
            parts.append("\n" + "\n".join(rows))

        parts.append(f"\n<code>{_escape(getattr(record, 'event', ''))}</code>")
        return "\n".join(parts)[:MAX_TEXT]

    def emit(self, record: logging.LogRecord) -> None:
        if not self.filter(record):
            return
        super().emit(record)


def attach_security_alerts(service: str) -> TelegramSecurityHandler:
    """Підключає сповіщення про події безпеки."""
    handler = TelegramSecurityHandler(service)
    logging.getLogger("security").addHandler(handler)
    return handler
