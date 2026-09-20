"""Нормалізація Telegram-ідентичності для контактних форм.

Telegram ``username`` і ``first_name`` — різні поля. Handle ніколи не є
ПІБ одержувача й не повинен автоматично потрапляти в накладну/CRM.
"""
from __future__ import annotations

import re

_HANDLE_RE = re.compile(r"(?<![\w.])@[A-Za-z0-9_]{5,32}(?![A-Za-z0-9_])")


def normalize_person_name(value: str | None) -> str:
    return " ".join(str(value or "").split())


def contains_telegram_handle(value: str | None) -> bool:
    clean = normalize_person_name(value)
    return bool(clean and (clean.startswith("@") or _HANDLE_RE.search(clean)))


def safe_telegram_first_name(first_name: str | None, username: str | None = None) -> str | None:
    clean = normalize_person_name(first_name)
    if not clean or contains_telegram_handle(clean):
        return None
    handle = normalize_person_name(username).lstrip("@").casefold()
    # Захист від зіпсованого/legacy payload, де username поклали у first_name
    # без @. Порівнюємо лише характерні handle-и; звичайне ім'я, яке
    # випадково дорівнює простому username, не відкидаємо.
    if handle and ("_" in handle or any(ch.isdigit() for ch in handle)) and clean.casefold() == handle:
        return None
    return clean
