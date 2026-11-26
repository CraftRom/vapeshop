"""Тимчасові збої long-polling Telegram — попередження, а не помилки.

aiogram пише кожен невдалий getUpdates як ERROR, хоча сам повторює запит.
На VPS це 1–3 записи на добу (502 Bad Gateway, обрив TCP, таймаут, flood
control) з автоматичним відновленням приблизно за хвилину. Як ERROR вони
ховали справжні помилки. Невірний токен, Conflict (другий процес із тим самим
токеном) та інші помилки лишаються ERROR.
"""
from __future__ import annotations

import logging

TRANSIENT = (
    "TelegramServerError",   # 5xx від Telegram, зокрема Bad Gateway
    "TelegramNetworkError",  # обрив, таймаут, недоступний хост
    "TelegramRetryAfter",    # flood control: aiogram чекає й повторює
)
PREFIX = "Failed to fetch updates - "


class TransientPollingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.ERROR:
            message = record.getMessage()
            if message.startswith(PREFIX) and any(message[len(PREFIX):].startswith(kind) for kind in TRANSIENT):
                record.levelno, record.levelname = logging.WARNING, "WARNING"
                record.event = "telegram.polling.transient"
        return True


def install() -> None:
    logger = logging.getLogger("aiogram.dispatcher")
    if not any(isinstance(f, TransientPollingFilter) for f in logger.filters):
        logger.addFilter(TransientPollingFilter())
