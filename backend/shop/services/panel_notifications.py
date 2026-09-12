"""Події для центру сповіщень панелі керування.

Це не браузерний Push-сервіс. Сервер лише зберігає надійний журнал подій.
Відкрита панель забирає нові записи коротким polling, показує їх у власному
центрі, відтворює різні звуки й, якщо працівник дав дозвіл, піднімає
системне повідомлення браузера.
"""
from __future__ import annotations

import logging

from shop.repo.base import Repository

log = logging.getLogger(__name__)


def preview(text: str, limit: int = 180) -> str:
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


async def publish(
    repo: Repository,
    kind: str,
    title: str,
    body: str = "",
    *,
    href: str | None = None,
    entity_id: int | None = None,
    actor: str | None = None,
) -> dict:
    return await repo.create_panel_notification({
        "kind": kind[:40],
        "title": title[:180],
        "body": preview(body, 800),
        "href": href[:512] if href else None,
        "entity_id": entity_id,
        "actor": actor[:128] if actor else None,
    })


async def safe_publish(repo: Repository, *args, **kwargs) -> dict | None:
    """Подія не має ламати основну бізнес-операцію.

    Якщо центр сповіщень тимчасово недоступний, замовлення/чат/каталог
    однаково мають працювати; причина лишається в журналі.
    """
    # Частина ізольованих сервісних тестів/утиліт використовує мінімальний
    # mock Repository без notification API. Сповіщення — побічний канал,
    # тому відсутність цього необов'язкового методу не повинна засмічувати
    # лог traceback-ами або ламати основну операцію.
    if not callable(getattr(repo, "create_panel_notification", None)):
        return None
    try:
        return await publish(repo, *args, **kwargs)
    except Exception:
        log.warning("Не вдалося створити подію центру сповіщень", exc_info=True)
        return None
