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
from shop.worker_health import states

STATES = ("disabled", "not_configured", "no_worker", "ready")


def _module(key, title, status, detail, worker=None):
    assert status in STATES
    return {"key": key, "title": title, "status": status, "detail": detail, "worker": worker}


def _needs(worker_states, worker, key, title, ready_detail, absent_detail):
    running = worker_states[worker]["running"]
    return _module(key, title, "ready" if running else "no_worker",
                   ready_detail if running else absent_detail, worker)


def promo_controller_configured() -> bool:
    return bool(os.environ.get("PROMO_CONTROLLER_TOKEN", "").strip())


async def module_report(repo, *, heartbeat_directory=None, now=None) -> dict:
    shop = await get_shop_settings(repo)
    workers = states(directory=heartbeat_directory, now=now)
    no_scheduler = ("Планувальник не запущений. Запустіть його: cd deploy && "
                    "docker compose --env-file ../.env -f docker-compose.prod.yml up -d scheduler")
    modules = [
        _needs(workers, "scheduler", "scheduled_broadcasts", "Заплановані розсилки",
               "Планувальник запускає розсилки в призначений час.",
               no_scheduler + ". Ручна «Надіслати зараз» працює, заплановані — ні."),
    ]
    if not shop.backup_enabled:
        modules.append(_module("auto_backups", "Щоденні резервні копії", "disabled",
                               "Вимкнено в налаштуваннях.", "scheduler"))
    else:
        modules.append(_needs(workers, "scheduler", "auto_backups", "Щоденні резервні копії",
                              "Копія створюється раз на добу в заданий час.", no_scheduler + "."))
    modules.append(_needs(workers, "scheduler", "housekeeping", "Обслуговування даних",
                          "Прибирання журналів, старих копій і прострочених токенів раз на добу.",
                          no_scheduler + "."))
    modules.append(_needs(workers, "maintenance", "backup_jobs", "Копії з панелі",
                          "Виконавець приймає запити на копію з панелі.",
                          "Виконавець maintenance не подає heartbeat: запит копії з панелі чекатиме."))
    if not settings.bot_token:
        modules.append(_module("telegram_bot", "Telegram-бот", "not_configured",
                               "BOT_TOKEN не задано: бот і Telegram-оформлення вимкнені.", "bot"))
    else:
        modules.append(_needs(workers, "bot", "telegram_bot", "Telegram-бот",
                              "Бот отримує повідомлення в режимі polling.",
                              "Процес бота не подає heartbeat. Запустіть сервіс bot."))
    if not shop.salesdrive_enabled:
        modules.append(_module("salesdrive", "SalesDrive CRM", "disabled", "Вимкнено в налаштуваннях.", "scheduler"))
    elif not shop.salesdrive_ready:
        modules.append(_module("salesdrive", "SalesDrive CRM", "not_configured",
                               "Бракує домену або ключа форми SalesDrive.", "scheduler"))
    else:
        modules.append(_needs(workers, "scheduler", "salesdrive", "SalesDrive CRM",
                              "Відправка йде одразу; повтори й фонове читання — у планувальнику.",
                              "Нові заявки відправляються одразу, але повтори після збою й фонове "
                              "читання не працюватимуть без планувальника."))
    modules.append(_module(
        "promo_domains", "Домени промосторінок",
        "ready" if promo_controller_configured() else "not_configured",
        "Контролер промодоменів налаштований." if promo_controller_configured() else
        "PROMO_CONTROLLER_TOKEN не задано: редактор і перегляд працюють, підключення власного "
        "домену недоступне.", None))
    return {"modules": modules,
            "workers": [workers[name] for name in workers]}
