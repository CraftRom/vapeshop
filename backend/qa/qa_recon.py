"""РОЗВІДКА: відсічення сканерів не зачіпає справжніх маршрутів.

Правило в nginx закриває зʼєднання для шляхів, якими сканери шукають
файли налаштувань і SSRF-проксі. Написане воно регуляркою, а регулярка —
рівно той вид коду, який тихо починає ловити зайве.

Ціна помилки несиметрична. Пропущений сканер це шум у журналі. Зачеплений
власний маршрут — це мовчазна відмова: nginx закриває зʼєднання без
відповіді, у журналі застосунку нічого немає, бо запит до нього не дійшов,
і шукати причину доведеться в конфізі веб-сервера.

Тому набір бере справжній перелік маршрутів із застосунку й перевіряє
кожен. Не список, виписаний руками, — саме той, що зареєстрований у
FastAPI: новий маршрут потрапляє під перевірку сам, без нагадувань.
"""
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/tmp")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  DASHBOARD_LOGIN="root", DASHBOARD_PASSWORD="Pa$$w0rd123",
                  ELFAR_DATA_ROOT=tempfile.mkdtemp(prefix="qa_recon_"),
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_recon.db")

from qa_common import Report                              # noqa: E402

r = Report("РОЗВІДКА")

from api.main import app                                  # noqa: E402

root = Path(__file__).resolve().parents[2]
conf = (root / "deploy/nginx/app.conf.template").read_text()

# Витягуємо саме той шаблон, що поїде на сервер, а не його копію в тесті:
# копія розійшлася б із конфігом при першій же правці й перевіряла б не те.
patterns = re.findall(r"location ~\*\s+(\^/api/.+?)\s*\{\n", conf)
r.check(len(patterns) == 2,
        "правило відсічення є в обох блоках — і HTTP, і HTTPS", len(patterns))
r.check(len(set(patterns)) == 1,
        "обидва блоки відсікають однаково — інакше по HTTP пролізе те, "
        "що закрите по HTTPS")

# nginx ~* — регістронезалежно; у конфізі \\. екранується для nginx так само,
# як у Python, тож шаблон переноситься без переписування.
blocked = re.compile(patterns[0], re.IGNORECASE)


def is_blocked(path: str) -> bool:
    return blocked.search(path) is not None


print("\n--- жоден справжній маршрут не відсікається ---")
# Через app.openapi(), а не app.routes: у цій версії FastAPI підключені
# роутери лежать в обгортці, і плаский обхід бачив лише чотири маршрути
# з сімдесяти. Тест мовчки перевіряв би майже порожній перелік.
routes = sorted(p for p in app.openapi().get("paths", {}) if p.startswith("/api/"))
r.check(len(routes) > 40, "маршрути зчитано з застосунку", len(routes))

for path in routes:
    # Підставляємо у шаблони правдоподібні значення: {order_id} → 42.
    # Порожній шлях після підстановки перевіряв би не те, що ходить у прод.
    concrete = re.sub(r"\{[^}]+\}", "42", path)
    if is_blocked(concrete):
        r.check(False, f"маршрут {path} закритий правилом відсічення", concrete)
r.check(not any(is_blocked(re.sub(r"\{[^}]+\}", "42", p)) for p in routes),
        f"усі {len(routes)} маршрутів проходять")

print("\n--- заплановані шляхи лишаються вільними ---")
# Ці два сканер теж перебирав, але вони заплановані. Якщо колись правило
# розширять, тест нагадає, що воно вбʼє свій же майбутній маршрут.
for path in ("/api/image", "/api/image/42", "/api/download",
             "/api/download/receipt-42.pdf"):
    r.check(not is_blocked(path), f"зарезервовано: {path}")

print("\n--- те, чим ходили сканери, відсікається ---")
# Взято з журналу за 2 вересня: 140 запитів за 67 секунд з однієї адреси.
for path in (
    "/api/.env", "/api/.env.local", "/api/.aws/credentials",
    "/api/config", "/api/config.json", "/api/config.env",
    "/api/env", "/api/v1/env", "/api/v1/credentials",
    "/api/graphql", "/api/fetch", "/api/v1/fetch", "/api/proxy",
    "/api/preview", "/api/file", "/api/account",
    "/api/openapi.json", "/api/v1/config", "/api/v2/config",
    "/api/v1/settings", "/api/v2/settings",
    "/api/v1/status/config", "/api/v1/status/flags",
    "/api/vendor/phpunit/phpunit/src/Util/PHP/eval-stdin.php",
    "/api/src/.env", "/api/shared/config/.env",
):
    r.check(is_blocked(path), f"відсічено: {path}")

print("\n--- регістр не рятує сканера ---")
for path in ("/api/.ENV", "/api/Config.Json", "/api/V1/Credentials"):
    r.check(is_blocked(path), f"відсічено попри регістр: {path}")

print("\n--- сусідні шляхи не зачеплені ---")
# Найнебезпечніший клас помилки: шаблон без якоря починає ловити все,
# у чому трапилось потрібне слово.
for path in (
    "/api/shop/config",            # конфіг вітрини — не /api/config
    "/api/settings",               # справжній розділ панелі
    "/api/settings/environment",   # починається не з env
    "/api/logs/api/download",      # завантаження журналу
    "/api/media",                  # завантаження зображень
    "/api/telegram/webhook",       # вебхук бота
    "/api/auth/login",
    "/api/orders/42/messages",
):
    r.check(not is_blocked(path), f"не зачеплено: {path}")

r.done()
sys.exit(1 if r.fails else 0)
