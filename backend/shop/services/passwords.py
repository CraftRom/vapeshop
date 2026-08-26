"""Зберігання паролів менеджерів.

Використано pbkdf2 зі стандартної бібліотеки, а не bcrypt чи argon2:
нової залежності не додається, а розмір serverless-функції на Vercel і так
близький до межі. Для панелі з десятком облікових записів цього достатньо.

Формат рядка: pbkdf2_sha256$<ітерації>$<сіль_hex>$<хеш_hex>. Кількість
ітерацій зберігається всередині, щоб її можна було підняти в майбутньому,
не ламаючи вже збережені паролі.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 240_000
SALT_BYTES = 16

MIN_LENGTH = 8


class WeakPassword(ValueError):
    pass


def validate(password: str) -> None:
    """Мінімальні вимоги. Панель дає доступ до замовлень і клієнтів."""
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"Пароль має бути щонайменше {MIN_LENGTH} символів")
    if password.isdigit():
        raise WeakPassword("Пароль лише з цифр підбирається за секунди")
    if password.lower() in ("password", "12345678", "qwertyui", "operator", "admin123"):
        raise WeakPassword("Такий пароль є в будь-якому словнику для підбору")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Перевірка сталого часу. Будь-який зіпсований рядок — просто відмова."""
    try:
        algorithm, raw_iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(raw_iterations)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(expected, actual)
