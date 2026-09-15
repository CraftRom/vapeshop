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
ITERATIONS = 600_000
SALT_BYTES = 16

MIN_LENGTH = 12

# Популярні паролі не коротші за MIN_LENGTH. Раніше тут стояли восьмисимвольні
# («12345678», «admin123»): після підняття мінімуму до 12 жоден із них уже не
# міг дійти до перевірки, і захист від словника мовчки перестав існувати.
COMMON = frozenset({
    "password1234", "password12345", "qwerty123456", "qwertyuiop12",
    "1q2w3e4r5t6y", "1qaz2wsx3edc", "adminadmin12", "administrator",
    "operator1234", "manager12345", "iloveyou1234", "abcdefghijkl",
})


class WeakPassword(ValueError):
    pass


def validate(password: str) -> None:
    """Мінімальні вимоги. Панель дає доступ до замовлень і клієнтів."""
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"Пароль має бути щонайменше {MIN_LENGTH} символів")
    if password.isdigit():
        raise WeakPassword("Пароль лише з цифр підбирається за секунди")
    if password.lower() in COMMON:
        raise WeakPassword("Такий пароль є в будь-якому словнику для підбору")
    # «aaaaaaaaaaaa» чи «abababababab» формально довгі, але перебираються
    # миттєво — довжина без різноманіття нічого не додає.
    if len(set(password)) <= 2:
        raise WeakPassword("Пароль з одного-двох повторених символів підбирається миттєво")


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
