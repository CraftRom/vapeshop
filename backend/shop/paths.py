"""Де лежать дані застосунку.

Один корінь замість трьох окремих змінних. Раніше журнал, бекапи й медіа
мали кожен свою змінну оточення, і кожна була нагодою помилитися: одна
одруківка в шляху — і застосунок мовчки писав нікуди, а сторінка в панелі
показувала порожньо без пояснень.

Тепер шлях не налаштовується взагалі. Усередині контейнера це завжди
/data, на сервері — тека data поруч із docker-compose. Змінювати там нічого
не треба й не можна: усе, що справді варто налаштовувати — розклад бекапів,
ретенція, рівень журналу — лишається в панелі, у розділах системного
адміністратора.

Підкаталоги створюються самі при першому звертанні. Це навмисно: вимагати
від людини створити теку руками означає рано чи пізно отримати помилку
доступу в найгірший момент.
"""
from __future__ import annotations

import os
from pathlib import Path

# Єдиний виняток: тести ганяються без контейнера, і писати в /data вони
# не можуть. У продакшені змінна не задається ніде — ні в .env.example,
# ні в compose, — тож підмінити шлях випадково неможливо.
DATA_ROOT = Path(os.environ.get("ELFAR_DATA_ROOT", "/data"))


def _ensure(path: Path) -> Path:
    """Каталог, який гарантовано існує.

    Помилку доступу не ковтаємо: якщо писати нікуди, застосунок має
    сказати це вголос, а не вдавати, що все гаразд.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    return _ensure(DATA_ROOT / "logs")


def backups_dir() -> Path:
    return _ensure(DATA_ROOT / "backups")


def media_dir() -> Path:
    return _ensure(DATA_ROOT / "media")


def describe() -> dict:
    """Стан каталогів — для діагностики в панелі."""
    result = {"root": str(DATA_ROOT), "rootExists": DATA_ROOT.exists()}
    for name, factory in (("logs", logs_dir), ("backups", backups_dir), ("media", media_dir)):
        try:
            path = factory()
            result[name] = {
                "path": str(path),
                "exists": True,
                "writable": os.access(path, os.W_OK),
                "files": sum(1 for _ in path.iterdir()),
            }
        except OSError as exc:
            result[name] = {"path": str(DATA_ROOT / name), "exists": False,
                            "writable": False, "error": str(exc)}
    return result
