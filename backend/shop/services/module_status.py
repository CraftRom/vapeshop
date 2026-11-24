"""Стан модулів: «увімкнено» ≠ «працює» (A04, A09).

Кожен модуль отримує один із станів:

* ``disabled`` — вимкнено в налаштуваннях; нічого не очікується;
* ``not_configured`` — увімкнено або потрібне, але бракує ключа/адреси;
* ``no_worker`` — налаштовано, але виконавець (scheduler/bot/maintenance) не подає heartbeat;
* ``ready`` — налаштовано й виконавець живий.

Нічого не надсилає назовні й не розкриває ключів: лише наявність налаштувань
і вік heartbeat. Реальні виклики провайдерів — окрема діагностика інтеграцій.
"""
from __future__ import annotations

import os

from shop.config import settings
from shop.services.shop_settings import get_shop_settings
from shop.worker_health import heartbeat_dir, states

STATES = ("disabled", "not_configured", "no_worker", "ready")


def _module(key, title, status, detail, worker=None):
    assert status in STATES
    return {"key": key, "title": title, "status": status, "detail": detail, "worker": worker}


def heartbeat_problem(directory=None):
    """Why no worker can report itself, if the shared directory is the cause.

    The API runs as the same user as the workers; when it cannot write the
    heartbeat directory, neither can they, and every worker looks stopped
    although its container runs (owner root after a deploy via sudo).
    """
    directory = directory or heartbeat_dir()
    if not directory.is_dir():
        return f"Каталог {directory} відсутній"
    if not os.access(directory, os.W_OK | os.X_OK):
        return (f"Каталог {directory} недоступний для запису процесам магазину "
                f"(власник uid {directory.stat().st_uid}). Запустіть deploy.sh: крок data-init поверне права")
    return None


def _needs(worker_states, worker, key, title, ready_detail, absent_detail, cause=None):
    running = worker_states[worker]["running"]
    detail = ready_detail if running else (f"{cause}. {absent_detail}" if cause else absent_detail)
    return _module(key, title, "ready" if running else "no_worker", detail, worker)


def promo_controller_configured() -> bool:
    return bool(os.environ.get("PROMO_CONTROLLER_TOKEN", "").strip())


async def module_report(repo, *, heartbeat_directory=None, now=None) -> dict:
    shop = await get_shop_settings(repo)
    workers = states(directory=heartbeat_directory, now=now)
    cause = heartbeat_problem(heartbeat_directory) if not all(w["running"] for w in workers.values()) else None
    no_scheduler = ("Планувальник не подає heartbeat. Перевірте: cd deploy && "
                    "docker compose --env-file ../.env -f docker-compose.prod.yml ps scheduler; "
                    "запуск — bash deploy.sh або ... up -d scheduler")
    modules = [
        _needs(workers, "scheduler", "scheduled_broadcasts", "Заплановані розсилки",
               "Планувальник запускає розсилки в призначений час.",
               no_scheduler + ". Ручна «Надіслати зараз» працює, заплановані — ні.", cause=cause),
    ]
    if not shop.backup_enabled:
        modules.append(_module("auto_backups", "Щоденні резервні копії", "disabled",
                               "Вимкнено в налаштуваннях.", "scheduler"))
    else:
        modules.append(_needs(workers, "scheduler", "auto_backups", "Щоденні резервні копії",
                              "Копія створюється раз на добу в заданий час.", no_scheduler + ".", cause=cause))
    modules.append(_needs(workers, "scheduler", "housekeeping", "Обслуговування даних",
                          "Прибирання журналів, старих копій і прострочених токенів раз на добу.",
                          no_scheduler + ".", cause=cause))
    modules.append(_needs(workers, "maintenance", "backup_jobs", "Копії з панелі",
                          "Виконавець приймає запити на копію з панелі.",
                          "Виконавець maintenance не подає heartbeat: запит копії з панелі чекатиме.", cause=cause))
    if not settings.bot_token:
        modules.append(_module("telegram_bot", "Telegram-бот", "not_configured",
                               "BOT_TOKEN не задано: бот і Telegram-оформлення вимкнені.", "bot"))
    else:
        modules.append(_needs(workers, "bot", "telegram_bot", "Telegram-бот",
                              "Бот отримує повідомлення в режимі polling.",
                              "Процес бота не подає heartbeat. Запустіть сервіс bot.", cause=cause))
    if not shop.salesdrive_enabled:
        modules.append(_module("salesdrive", "SalesDrive CRM", "disabled", "Вимкнено в налаштуваннях.", "scheduler"))
    elif not shop.salesdrive_ready:
        modules.append(_module("salesdrive", "SalesDrive CRM", "not_configured",
                               "Бракує домену або ключа форми SalesDrive.", "scheduler"))
    else:
        modules.append(_needs(workers, "scheduler", "salesdrive", "SalesDrive CRM",
                              "Відправка йде одразу; повтори й фонове читання — у планувальнику.",
                              "Нові заявки відправляються одразу, але повтори після збою й фонове "
                              "читання не працюватимуть без планувальника.", cause=cause))
    modules.append(_module(
        "promo_domains", "Домени промосторінок",
        "ready" if promo_controller_configured() else "not_configured",
        "Контролер промодоменів налаштований." if promo_controller_configured() else
        "PROMO_CONTROLLER_TOKEN не задано: редактор і перегляд працюють, підключення власного "
        "домену недоступне.", None))
    return {"modules": modules, "heartbeat_problem": cause,
            "workers": [workers[name] for name in workers]}
