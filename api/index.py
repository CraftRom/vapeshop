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

from api.main import app  # noqa: E402

__all__ = ["app"]
