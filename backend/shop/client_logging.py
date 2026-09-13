"""Окремий журнал клієнтської вітрини.

Вітрина виконується у Telegram WebView, тому значна частина помилок ніколи не
потрапляє до Python traceback. Клієнт надсилає лише технічні, заздалегідь
обмежені поля; initData, токени, текст кошика/чату й інші персональні дані сюди
не приймаються.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys

from shop.logging_setup import JsonFormatter, log_backups, log_max_bytes
from shop.paths import logs_dir

_LOGGER_NAME = "storefront.client"
_MARKER = "_elfar_storefront_handler"


def get_logger() -> logging.Logger:
    """Логер у storefront.log, не змішуючи записи з api.log."""
    logger = logging.getLogger(_LOGGER_NAME)
    if any(getattr(h, _MARKER, False) for h in logger.handlers):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(JsonFormatter("storefront"))
    setattr(console, _MARKER, True)
    logger.addHandler(console)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir() / "storefront.log",
            maxBytes=log_max_bytes(),
            backupCount=log_backups(),
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter("storefront"))
        setattr(file_handler, _MARKER, True)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("Файловий журнал вітрини недоступний: %s", exc)

    return logger
