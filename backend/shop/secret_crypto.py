"""Шифрування інтеграційних секретів, які лежать у БД.

Формат має явний префікс, тому старі plaintext-значення читаються сумісно,
а після наступного збереження переходять у зашифрований вигляд.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"


def _fernet():
    from shop.config import settings
    raw = (settings.data_encryption_key or "").strip()
    return Fernet(raw.encode("ascii")) if raw else None


def encrypt_secret(value: str) -> str:
    value = value or ""
    if not value or value.startswith(PREFIX):
        return value
    f = _fernet()
    if f is None:
        return value  # локальна розробка; production-check забороняє такий режим
    return PREFIX + f.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    value = value or ""
    if not value.startswith(PREFIX):
        return value
    f = _fernet()
    if f is None:
        raise RuntimeError("DATA_ENCRYPTION_KEY потрібен для розшифрування секретів")
    try:
        return f.decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Зашифрований секрет пошкоджений або ключ не збігається") from exc
