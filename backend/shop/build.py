"""Мітка й автоматичний ідентифікатор збірки (A13).

Потрібні рівно для одного питання: чи той код зараз працює в продакшені,
що лежить у репозиторії. Без них відрізнити «фікс не допоміг» від
«фікс не задеплоївся» можна тільки здогадками.

``BUILD`` — людська назва релізу, її змінюють руками. Сама по собі вона
нічого не гарантує: мітку легко забути оновити. Тому до неї додається
відбиток вмісту робочого коду (SHA-256 відсортованих шляхів і байтів
Python-модулів і міграцій, без тестів і QA). Його обчислює
``python -m shop.build --write`` під час збірки образу й кладе в
``release.json``; без файла (локальний запуск) відбиток рахується при першому
зверненні. Два різні дерева коду з однією міткою отримають різні ID.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

BUILD = "2026-11-24-diagnostics-1.86.1"

BACKEND = Path(__file__).resolve().parents[1]
RELEASE_FILE = Path(__file__).with_name("release.json")
SOURCE_DIRS = ("api", "bot", "maintenance", "scheduler", "shop", "tools", "alembic")
SOURCE_FILES = ("alembic.ini", "requirements-lock.txt")


def source_digest(root: Path = BACKEND) -> str:
    """Deterministic: independent of mtimes, permissions and file order on disk."""
    digest = hashlib.sha256()
    files = [root / name for name in SOURCE_FILES if (root / name).is_file()]
    for directory in SOURCE_DIRS:
        base = root / directory
        if base.is_dir():
            files += [p for p in base.rglob("*") if p.is_file() and p.suffix in {".py", ".ini", ".mako"}
                      and "__pycache__" not in p.parts]
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        if path.resolve() == RELEASE_FILE.resolve():
            continue
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big") + relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def release() -> dict:
    """{label, digest, id, built_at}. Never raises: diagnostics must not break startup."""
    try:
        data = json.loads(RELEASE_FILE.read_text())
        if data.get("label") == BUILD and len(str(data.get("digest", ""))) == 64:
            return {**data, "id": f"{BUILD}+{data['digest'][:12]}"}
    except (OSError, ValueError, TypeError):
        pass
    try:
        value = source_digest()
    except OSError:
        value = "0" * 64
    return {"label": BUILD, "digest": value, "id": f"{BUILD}+{value[:12]}", "built_at": None}


def release_id() -> str:
    return release()["id"]


def write_release_file() -> dict:
    data = {"label": BUILD, "digest": source_digest(), "built_at": datetime.now(timezone.utc).isoformat()}
    RELEASE_FILE.write_text(json.dumps(data, ensure_ascii=False) + "\n")
    release.cache_clear()
    return release()


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        print(write_release_file()["id"])
    else:
        print(release()["id"])
