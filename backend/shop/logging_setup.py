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

# Поля, які logging кладе в кожен запис сам. Усе, чого тут немає, —
# наше й має потрапити в JSON.
_STANDARD = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName",
}

# Скільки місця журнали займають у найгіршому випадку:
#
#   сервісів × (LOG_MAX_MB × (LOG_BACKUPS + 1))
#
# За замовчуванням 3 × 10 × 6 = 180 МБ. Плюс журнал безпеки, у якого копій
# удвічі більше: подій там на порядки менше, тож ті самі мегабайти
# зберігають місяці замість днів. Це стеля, а не поточний розмір:
# більше журнали не з'їдять навіть за нічний цикл помилок. На тісному
# VPS її можна опустити через .env, не чіпаючи код.
#
# Межа була зашита числом просто в коді. Через це ніхто не знав, скільки
# саме місця відведено журналам, і зменшити її на ходу було нічим.
SERVICES_COUNT = 3


def log_max_bytes() -> int:
    """Розмір, після якого файл журналу починається заново."""
    try:
        megabytes = float(os.environ.get("LOG_MAX_MB", "10"))
    except ValueError:
        megabytes = 10
    # Менше мегабайта — і файл прокручується швидше, ніж встигаєш його
    # прочитати: остання година подій зникає, поки дивишся на екран.
    return int(max(1.0, megabytes) * 1024 * 1024)


def log_backups() -> int:
    """Скільки прокручених файлів лишаємо поруч із поточним."""
    try:
        count = int(os.environ.get("LOG_BACKUPS", "5"))
    except ValueError:
        count = 5
    return max(0, count)


def log_budget_bytes() -> int:
    """Стеля, якої журнали не перевищать за жодних обставин."""
    services = SERVICES_COUNT * log_max_bytes() * (log_backups() + 1)
    security = log_max_bytes() * (log_backups() * 2 + 1)
    return services + security


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


# Усі рівні стандартної бібліотеки плюс звичні синоніми.
#
# WARN і FATAL офіційно застарілі, але їх пишуть за звичкою, і мовчки
# ігнорувати їх — значить дати людині журнал не того рівня без пояснень.
LEVELS = {
    "NOTSET": logging.NOTSET,       # 0  — усе, включно з чужими бібліотеками
    "TRACE": logging.DEBUG,         # 10 — синонім DEBUG, звичка з інших мов
    "DEBUG": logging.DEBUG,         # 10
    "INFO": logging.INFO,           # 20
    "WARNING": logging.WARNING,     # 30
    "WARN": logging.WARNING,        # 30
    "ERROR": logging.ERROR,         # 40
    "CRITICAL": logging.CRITICAL,   # 50
    "FATAL": logging.CRITICAL,      # 50
}


def resolve_level(value) -> tuple[int, bool]:
    """Рівень журналу з назви або числа.

    Повертає (рівень, чи_була_проблема). Друге значення потрібне, щоб той,
    хто викликає, міг повідомити про одруківку — сам по собі запасний
    варіант INFO виглядав би як «налаштування не працює».

    Числа приймаються теж: logging їх підтримує, і між DEBUG та INFO
    інколи ставлять 15, щоб приглушити конкретну бібліотеку.
    """
    if value is None or str(value).strip() == "":
        return logging.INFO, False

    raw = str(value).strip().upper()
    if raw in LEVELS:
        return LEVELS[raw], False

    if raw.lstrip("-").isdigit():
        number = int(raw)
        if 0 <= number <= 100:
            return number, False

    return logging.INFO, True


def _from_settings(field: str, fallback):
    """Значення з .env через налаштування, якщо в оточенні його немає.

    Імпорт усередині функції навмисно: shop.config тягне за собою pydantic
    і валідацію, а логування має піднятися навіть тоді, коли конфігурація
    зламана — інакше причину поломки нікуди буде записати.
    """
    try:
        from shop.config import settings

        return getattr(settings, field, fallback)
    except Exception:
        return fallback


def setup(service: str) -> logging.Logger:
    """Налаштовує логування для сервісу: api, bot або scheduler.

    Викликати один раз на старті процесу. Повторний виклик безпечний —
    старі обробники знімаються, інакше кожен рядок дублювався б.
    """
    # Спершу оточення, потім .env через налаштування. Порядок такий, бо в
    # контейнері діють змінні, а при локальному запуску їх в оточенні немає —
    # там значення лежать у .env, і без цього запасного шляху файлове
    # логування мовчки не вмикалося б поза docker.
    level_name = os.environ.get("LOG_LEVEL") or _from_settings("log_level", "INFO")
    level, level_problem = resolve_level(level_name)

    raw_json = os.environ.get("LOG_JSON")
    as_json = raw_json != "0" if raw_json is not None else bool(
        _from_settings("log_json", True)
    )

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    if level_problem:
        # Не мовчимо. Мовчазне падіння на INFO — найгірший варіант: людина
        # виставила DEBUG заради розслідування, отримала звичайний журнал
        # і шукає причину в застосунку, а вона в одруківці.
        root.warning("Невідомий рівень журналу %r — узято INFO", level_name,
                     extra={"event": "log.level.invalid", "requested": str(level_name)})

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(JsonFormatter(service) if as_json else TextFormatter())
    root.addHandler(console)

    # Шлях фіксований: shop.paths — єдине місце, де він визначається.
    try:
        from shop.paths import logs_dir

        path = logs_dir()
    except OSError as exc:
        root.warning("Файлове логування вимкнено: %s", exc)
        path = None

    if path is not None:
        try:
            # Один файл на сервіс: змішувати запити API з апдейтами бота
            # в одному файлі означає щоразу починати розбір із grep.
            handler = logging.handlers.RotatingFileHandler(
                path / f"{service}.log",
                maxBytes=log_max_bytes(),
                backupCount=log_backups(),
                encoding="utf-8",
            )
            handler.setFormatter(JsonFormatter(service))
            root.addHandler(handler)
            # Події безпеки додатково лягають у власний файл. У спільному
            # вони теж лишаються — там їх видно поруч із помилкою, що
            # сталася в ту саму секунду, — але шукати їх треба окремо.
            from shop.security_log import attach as attach_security

            attach_security(path)
        except OSError as exc:
            # Немає прав на каталог — не привід не запуститись. Пишемо
            # у stdout і кажемо про це прямо.
            root.warning("Файлове логування вимкнено: %s", exc)

    # Сповіщення в Telegram про помилки. Підключаємо останнім, щоб воно
    # бачило всі записи, включно з тими, які створять обробники вище.
    if os.environ.get("ALERTS", "1") != "0":
        try:
            from shop.alerts import attach, attach_security_alerts

            attach(service)
            # Події безпеки йдуть тим самим шляхом, що й помилки: у
            # магазині без чергового інженера канал у Telegram — єдине
            # місце, де їх узагалі побачать. Запис у файл, який ніхто не
            # відкриває, від зловмисника не рятує.
            attach_security_alerts(service)
        except Exception:
            root.warning("Сповіщення про помилки не підключені", exc_info=True)

    # Ці бібліотеки в режимі INFO друкують кожен HTTP-запит і кожне
    # SQL-звернення — корисно лише під час налагодження.
    for noisy in ("httpx", "httpcore", "aiogram.event", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger(service)
