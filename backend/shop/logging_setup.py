"""Структуроване логування у файл.

Формат — один JSON на рядок, як у serverless-платформ. Причина не в моді:
рядок виду «2026-08-26 09:30 INFO api: замовлення 42 створено» читає людина,
але його неможливо відфільтрувати за клієнтом, згрупувати за маршрутом чи
порахувати відсоток помилок. JSON дає і те, і те: `docker compose logs`
лишається читабельним через рівень і подію, а `jq` бере будь-яке поле.

Куди пишемо:
  • stdout — його збирає docker, це видно в `docker compose logs`
  • файл у LOG_DIR — переживає перезапуск контейнера й доступний з хоста

Ротація за розміром робиться тут же: без неї один нічний цикл помилок
заповнив би диск, і впав би не лише застосунок, а й Postgres поруч.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Поля, які logging кладе в кожен запис сам. Усе, чого тут немає, —
# наше й має потрапити в JSON.
_STANDARD = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Запис журналу як один рядок JSON."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "service": self.service,
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Усе, що передали через extra=..., лягає в корінь запису поруч
        # зі стандартними полями — так фільтри виглядають однаково для
        # службових і прикладних даних.
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)

        # default=str, бо в extra регулярно потрапляють datetime і Decimal,
        # і падіння логера через несеріалізовне поле — найгірший спосіб
        # дізнатися про помилку.
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Читабельний варіант для консолі під час розробки."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s: %(message)s")


def setup(service: str) -> logging.Logger:
    """Налаштовує логування для сервісу: api, bot або scheduler.

    Викликати один раз на старті процесу. Повторний виклик безпечний —
    старі обробники знімаються, інакше кожен рядок дублювався б.
    """
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    as_json = os.environ.get("LOG_JSON", "1") != "0"

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(JsonFormatter(service) if as_json else TextFormatter())
    root.addHandler(console)

    directory = os.environ.get("LOG_DIR", "")
    if directory:
        try:
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            # Один файл на сервіс: змішувати запити API з апдейтами бота
            # в одному файлі означає щоразу починати розбір із grep.
            handler = logging.handlers.RotatingFileHandler(
                path / f"{service}.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            handler.setFormatter(JsonFormatter(service))
            root.addHandler(handler)
        except OSError as exc:
            # Немає прав на каталог — не привід не запуститись. Пишемо
            # у stdout і кажемо про це прямо.
            root.warning("Файлове логування вимкнено: %s", exc)

    # Ці бібліотеки в режимі INFO друкують кожен HTTP-запит і кожне
    # SQL-звернення — корисно лише під час налагодження.
    for noisy in ("httpx", "httpcore", "aiogram.event", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger(service)
