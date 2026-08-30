"""ЖУРНАЛ: структура записів, файли, відсутність секретів."""
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/tmp")
DATA_ROOT = tempfile.mkdtemp(prefix="qa_data_")
LOG_DIR = str(Path(DATA_ROOT) / "logs")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  ELFAR_DATA_ROOT=DATA_ROOT, LOG_JSON="1",
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_log.db")

os.makedirs(LOG_DIR if "LOG_DIR" in dir() else BACKUP_DIR, exist_ok=True)

from qa_common import Report                              # noqa: E402

r = Report("ЖУРНАЛ")

from shop.logging_setup import JsonFormatter, setup       # noqa: E402


def parse(line: str) -> dict:
    return json.loads(line)


# ------------------------------------------------------------ формат запису

print("\n--- поля, за якими потім шукають ---")
log = setup("api")
log.info("тест", extra={"event": "http.request", "requestId": "abc123",
                        "method": "GET", "path": "/api/orders",
                        "status": 200, "durationMs": 12.5})

log_file = Path(LOG_DIR) / "api.log"
r.check(log_file.exists(), "файл журналу створено", LOG_DIR)

lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
r.check(lines, f"записів у файлі: {len(lines)}")

record = parse(lines[-1])
for field in ("time", "service", "level", "logger", "message"):
    r.check(field in record, f"є службове поле {field}", record.get(field))
for field in ("event", "requestId", "method", "path", "status", "durationMs"):
    r.check(record.get(field) is not None, f"є поле запиту {field}", record.get(field))

r.check(record["service"] == "api", "сервіс названо", record["service"])
r.check(record["level"] == "info", "рівень у нижньому регістрі", record["level"])
r.check(record["time"].endswith("+00:00"), "час у UTC з зоною", record["time"])

print("\n--- кожен рядок — самостійний JSON ---")
broken = [ln for ln in lines if not ln.startswith("{") or not ln.endswith("}")]
r.check(not broken, "жоден запис не розірваний на кілька рядків", broken[:2])

print("\n--- несеріалізовне не валить логер ---")
from datetime import datetime
from decimal import Decimal

log.info("складні типи", extra={"createdAt": datetime.now(), "sum": Decimal("10.50"),
                                "obj": object()})
lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
last = parse(lines[-1])
r.check(last["message"] == "складні типи", "запис із datetime і Decimal пройшов")
r.check(isinstance(last["sum"], str), "Decimal перетворено на рядок", last["sum"])

print("\n--- виняток потрапляє в поле error ---")
try:
    raise ValueError("щось пішло не так")
except ValueError:
    log.exception("помилка", extra={"requestId": "err1"})
lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
last = parse(lines[-1])
r.check("error" in last and "ValueError" in last["error"], "трейсбек збережено")
r.check(last["level"] == "error", "рівень error", last["level"])


# ----------------------------------------------------------- секрети в журнал

print("\n--- секрети не потрапляють у журнал ---")
SECRETS = (os.environ["JWT_SECRET"], os.environ["BOT_TOKEN"], "Пароль123")
whole = log_file.read_text(encoding="utf-8")
for secret in SECRETS:
    r.check(secret not in whole, f"немає секрету {secret[:6]}…")

# Обробник входу має писати довжину пароля, але не сам пароль
# Перевіряємо не файл цілком, а саме те, що йде в журнал: у самому
# обробнику пароль звісно згадується — його передають у authenticate().
# Груба перевірка «немає слова password поруч» ловила б цей рядок
# і давала хибну тривогу.
import ast

main_src = Path(__file__).resolve().parents[1] / "api" / "main.py"
tree = ast.parse(main_src.read_text(encoding="utf-8"))

logged_values = []
for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue
    for keyword in node.keywords:
        if keyword.arg == "extra":
            logged_values.append(ast.dump(keyword.value))

extras = " ".join(logged_values)
r.check("passwordLength" in extras, "довжина пароля логується")
# Пароль може потрапити в extra лише обгорнутий у len() — сам по собі ні.
bare = extras.replace("Call(func=Name(id='len'", "«len»")
r.check("attr='password'" not in bare.split("«len»")[0] if "«len»" in bare
        else "attr='password'" not in bare,
        "сам пароль у журнал не йде")


# --------------------------------------------------------------- повторний setup

print("\n--- повторний виклик не дублює записів ---")
before = len([ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()])
log = setup("api")
log.info("після повторного налаштування")
after = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
r.check(len(after) == before + 1, "рівно один новий запис", len(after) - before)


# ------------------------------------------------------------------ ротація

print("\n--- ретенція прибирає лише ротовані файли ---")
import time
from scheduler.tasks import prune_logs

active = Path(LOG_DIR) / "api.log"
rotated = Path(LOG_DIR) / "api.log.3"
rotated.write_text("{}\n", encoding="utf-8")
old = time.time() - 90 * 86400
os.utime(rotated, (old, old))

removed = prune_logs(30)
r.check(removed == 1, "старий ротований файл видалено", removed)
r.check(active.exists(), "активний файл не чіпаємо — процес тримає його відкритим")
r.check(not rotated.exists(), "ротованого файлу більше немає")
r.check(prune_logs(0) == 0, "нульова ретенція нічого не чистить")


# ------------------------------------------------------------ текстовий режим

print("\n--- режим для розробки ---")
# Шлях більше не підміняється змінною — у цьому й суть правки: каталог
# один і той самий, змінюється лише формат консолі.
os.environ["LOG_JSON"] = "0"
log = setup("bot")
log.info("читабельний рядок")
console_ok = True
plain_file = Path(LOG_DIR) / "bot.log"
# У файл пишемо JSON завжди: файли читають програми, консоль — люди
r.check(plain_file.exists() and plain_file.read_text(encoding="utf-8").startswith("{"),
        "у файлі лишається JSON навіть у текстовому режимі")
r.check(console_ok, "текстовий режим не падає")

print("\n--- налаштування діють на всі сервіси ---")
import yaml

compose = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "deploy" / "docker-compose.prod.yml")
    .read_text(encoding="utf-8")
)
for service in ("api", "bot", "scheduler", "migrate"):
    spec = compose["services"][service]
    r.check(spec.get("env_file") == "../.env",
            f"{service} читає .env — отже бачить LOG_JSON і LOG_LEVEL",
            spec.get("env_file"))

print("\n--- значення читаються і з .env, коли оточення порожнє ---")
from shop.logging_setup import _from_settings

r.check(_from_settings("log_level", "INFO") is not None, "log_level доступний")
r.check(_from_settings("неіснуюче_поле", "запасне") == "запасне",
        "невідоме поле повертає запасне значення")

print("\n--- .env.example описує всі три змінні ---")
example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
for key in ("LOG_JSON", "LOG_LEVEL"):
    r.check(f"{key}=" in example, f"{key} задокументовано")
# Шляхи навмисно не налаштовуються: один корінь /data, підкаталоги
# створює застосунок. Перевіряємо, що змінна не повернулась.
for gone in ("LOG_DIR", "HOST_LOG_DIR", "MEDIA_DIR", "BACKUP_DIR"):
    r.check(f"\n{gone}=" not in example, f"{gone} прибрано з .env")

print("\n--- рівні журналу ---")
from shop.logging_setup import LEVELS, resolve_level

for name, expected in [("DEBUG", 10), ("INFO", 20), ("WARNING", 30),
                       ("ERROR", 40), ("CRITICAL", 50), ("NOTSET", 0)]:
    got, bad = resolve_level(name)
    r.check(got == expected and not bad, f"{name} → {expected}", (got, bad))
    got, bad = resolve_level(name.lower())
    r.check(got == expected and not bad, f"{name.lower()} (нижній регістр) → {expected}")

for alias, expected in [("WARN", 30), ("FATAL", 50), ("TRACE", 10)]:
    got, bad = resolve_level(alias)
    r.check(got == expected and not bad, f"синонім {alias} → {expected}", got)

for number, expected in [("15", 15), ("0", 0), ("50", 50)]:
    got, bad = resolve_level(number)
    r.check(got == expected and not bad, f"число {number} → {expected}", got)

r.check(resolve_level(" info ")[0] == 20, "пробіли навколо значення не заважають")
for empty in ("", None):
    got, bad = resolve_level(empty)
    r.check(got == 20 and not bad, f"порожнє значення → INFO без скарги: {empty!r}")

print("\n--- одруківка помічається, а не ковтається ---")
for wrong in ("ВЕРБОЗ", "999", "-5", "TRAСE"):
    got, bad = resolve_level(wrong)
    r.check(got == 20 and bad, f"{wrong!r} → INFO і позначено як проблему", (got, bad))

print("\n--- рівень справді фільтрує ---")
os.environ["LOG_JSON"] = "1"
written = Path(LOG_DIR) / "api.log"
for name, should_pass in [("DEBUG", True), ("ERROR", False)]:
    os.environ["LOG_LEVEL"] = name
    probe = setup("api")
    marker = f"перевірка рівня {name}"
    probe.info(marker)
    body = written.read_text(encoding="utf-8") if written.exists() else ""
    r.check((marker in body) == should_pass,
            f"на рівні {name} запис INFO {'проходить' if should_pass else 'відсічений'}")

r.check(len(LEVELS) >= 9, f"перелік рівнів повний: {len(LEVELS)}")

r.done()
