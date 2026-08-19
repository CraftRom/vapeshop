"""Точка входу для Vercel.

Vercel перетворює кожен файл у /api на serverless-функцію. Змінна `app`
(ASGI-застосунок) підхоплюється рантаймом @vercel/python автоматично.
Маршрутизацію всіх шляхів сюди задає vercel.json.
"""
import os
import sys

# Код бекенду лежить у сусідній теці — vercel.json тягне її через includeFiles
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Vercel — це serverless: вимикаємо пул з'єднань і init_db на старті
os.environ.setdefault("SERVERLESS", "true")
# На Vercel типова база — Firestore: немає лімітів на з'єднання й холодних
# конектів. Щоб узяти Postgres, задайте DB_BACKEND=sql у змінних оточення.
os.environ.setdefault("DB_BACKEND", "firestore")

# Ключ сервісного акаунта зручніше зберігати як одну змінну, а не файл
_credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
if _credentials and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    _path = "/tmp/gcp-credentials.json"
    with open(_path, "w") as handle:
        handle.write(_credentials)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _path

from api.main import app as _app  # noqa: E402


class RestoreOriginalPath:
    """Повертає початковий шлях запиту, якщо платформа його переписала.

    Схема builds+routes у vercel.json доносить справжній шлях, але конфігурацію
    легко змінити на rewrites — і тоді до застосунку прийде «/api/index»
    замість «/api/auth/login». Замість того щоб покладатися на конкретну
    поведінку платформи, відновлюємо шлях із заголовків, які проксі лишає.
    """

    REWRITTEN = ("/api/index", "/api/index.py", "/api", "")
    HEADERS = (b"x-vercel-original-path", b"x-forwarded-uri", b"x-original-uri")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") in self.REWRITTEN:
            headers = dict(scope.get("headers") or [])
            for name in self.HEADERS:
                value = headers.get(name)
                if value:
                    original = value.decode("latin-1").split("?", 1)[0]
                    if original.startswith("/api/"):
                        scope = dict(scope, path=original, raw_path=original.encode())
                    break
        await self.app(scope, receive, send)


app = RestoreOriginalPath(_app)
