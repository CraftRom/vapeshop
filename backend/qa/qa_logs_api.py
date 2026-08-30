"""ЖУРНАЛ У ПАНЕЛІ: доступ, фільтри, захист від обходу шляху."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/tmp")
DATA_ROOT = tempfile.mkdtemp(prefix="qa_data_")
LOG_DIR = str(Path(DATA_ROOT) / "logs")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  DASHBOARD_LOGIN="root", DASHBOARD_PASSWORD="Pa$$w0rd123",
                  ELFAR_DATA_ROOT=DATA_ROOT,
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_logsapi.db")

os.makedirs(LOG_DIR if "LOG_DIR" in dir() else BACKUP_DIR, exist_ok=True)

from qa_common import Report                             # noqa: E402

r = Report("ЖУРНАЛ У ПАНЕЛІ")

import httpx                                             # noqa: E402
from api.auth import create_token                        # noqa: E402
from api.main import app                                 # noqa: E402
from shop.entities import OperatorRole                   # noqa: E402


# Готуємо файл журналу з передбачуваним вмістом
def write_log(service: str, records: list[dict]) -> None:
    path = Path(LOG_DIR) / f"{service}.log"
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


write_log("api", [
    {"time": "2026-08-26T10:00:00+00:00", "service": "api", "level": "info",
     "logger": "api.request", "message": "GET /api/orders → 200",
     "event": "http.request", "requestId": "aaa111", "status": 200, "ip": "1.2.3.4"},
    {"time": "2026-08-26T10:00:01+00:00", "service": "api", "level": "warning",
     "logger": "api.auth", "message": "Невдалий вхід: petro",
     "event": "auth.login.failed", "requestId": "bbb222", "login": "petro"},
    {"time": "2026-08-26T10:00:02+00:00", "service": "api", "level": "error",
     "logger": "api", "message": "Все зламалось", "event": "boom",
     "requestId": "ccc333"},
    "не-JSON рядок, який має бути пропущений",
] and [
    {"time": "2026-08-26T10:00:00+00:00", "service": "api", "level": "info",
     "logger": "api.request", "message": "GET /api/orders → 200",
     "event": "http.request", "requestId": "aaa111", "status": 200, "ip": "1.2.3.4"},
    {"time": "2026-08-26T10:00:01+00:00", "service": "api", "level": "warning",
     "logger": "api.auth", "message": "Невдалий вхід: petro",
     "event": "auth.login.failed", "requestId": "bbb222", "login": "petro"},
    {"time": "2026-08-26T10:00:02+00:00", "service": "api", "level": "error",
     "logger": "api", "message": "Все зламалось", "event": "boom",
     "requestId": "ccc333"},
])
# Битий рядок дописуємо окремо: він має пережитися, а не завалити сторінку
with (Path(LOG_DIR) / "api.log").open("a", encoding="utf-8") as handle:
    handle.write("це не JSON\n")
    handle.write('{"обірваний": \n')

write_log("bot", [
    {"time": "2026-08-26T10:00:00+00:00", "service": "bot", "level": "info",
     "logger": "bot", "message": "Бот запущено", "event": "bot.start"},
])

SYSADMIN = create_token("root", OperatorRole.SYSADMIN, 0, "Root")
ADMIN = create_token("shopadmin", OperatorRole.ADMIN, 5, "Адмін")
MANAGER = create_token("manager", OperatorRole.MANAGER, 7, "Менеджер")


async def scenario():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        def head(token):
            return {"Authorization": f"Bearer {token}"}

        print("\n--- доступ ---")
        for label, token, expected in [("системний адміністратор", SYSADMIN, 200),
                                       ("адміністратор", ADMIN, 403),
                                       ("менеджер", MANAGER, 403)]:
            resp = await client.get("/api/logs?service=api", headers=head(token))
            r.check(resp.status_code == expected,
                    f"{label} → {expected}", resp.status_code)

        resp = await client.get("/api/logs?service=api")
        r.check(resp.status_code in (401, 403), "без токена не пускає", resp.status_code)

        print("\n--- читання ---")
        resp = await client.get("/api/logs?service=api", headers=head(SYSADMIN))
        body = resp.json()
        # Точну кількість не перевіряємо: сам застосунок теж пише в цей
        # файл, і читання журналу лишає в ньому слід. Перевіряємо, що наші
        # записи на місці й у правильному порядку.
        ours = [x for x in body["records"] if x.get("requestId") in
                ("aaa111", "bbb222", "ccc333")]
        r.check(len(ours) == 3, "усі три підготовлені записи знайдено", len(ours))
        r.check([x["requestId"] for x in ours] == ["ccc333", "bbb222", "aaa111"],
                "найновіші першими", [x["requestId"] for x in ours])
        r.check(all(isinstance(x, dict) for x in body["records"]),
                "биті рядки пропущені, а не повалили відповідь")

        print("\n--- фільтр за рівнем ---")
        resp = await client.get("/api/logs?service=api&level=warning", headers=head(SYSADMIN))
        levels = [x["level"] for x in resp.json()["records"]]
        r.check(set(levels) == {"warning", "error"},
                "рівень і вище: warning дає ще й error", levels)

        resp = await client.get("/api/logs?service=api&level=error", headers=head(SYSADMIN))
        r.check([x["level"] for x in resp.json()["records"]] == ["error"],
                "error дає лише error")

        print("\n--- фільтр за подією і запитом ---")
        resp = await client.get("/api/logs?service=api&event=auth.login.failed",
                                headers=head(SYSADMIN))
        r.check(resp.json()["returned"] == 1, "подія знайдена", resp.json()["returned"])
        r.check(resp.json()["records"][0]["login"] == "petro", "поля запису на місці")

        resp = await client.get("/api/logs?service=api&requestId=aaa111", headers=head(SYSADMIN))
        r.check(resp.json()["returned"] == 1, "запит за requestId")

        print("\n--- пошук ---")
        for needle, expected in [("petro", 1), ("1.2.3.4", 1), ("зламалось", 1),
                                 ("НЕМАЄ", 0)]:
            resp = await client.get(f"/api/logs?service=api&search={needle}",
                                    headers=head(SYSADMIN))
            r.check(resp.json()["returned"] == expected,
                    f"пошук {needle!r} → {expected}", resp.json()["returned"])

        print("\n--- ліміт ---")
        resp = await client.get("/api/logs?service=api&limit=1", headers=head(SYSADMIN))
        body = resp.json()
        r.check(body["returned"] == 1 and body["truncated"],
                "ліміт спрацював і позначений", (body["returned"], body["truncated"]))
        resp = await client.get("/api/logs?service=api&limit=0", headers=head(SYSADMIN))
        r.check(resp.status_code == 422, "нульовий ліміт відхилено", resp.status_code)

        print("\n--- інший сервіс ---")
        resp = await client.get("/api/logs?service=bot", headers=head(SYSADMIN))
        r.check(resp.json()["records"][0]["event"] == "bot.start", "журнал бота окремо")

        print("\n--- обхід шляху ---")
        # Найнебезпечніше в усьому ендпоінті: імʼя сервісу підставляється
        # у шлях до файлу. Білий список має тримати будь-яку спробу.
        for evil in ("../../etc/passwd", "..%2f..%2fetc%2fpasswd", "api/../../secret",
                     "", "API", "scheduler.log"):
            resp = await client.get(f"/api/logs?service={evil}", headers=head(SYSADMIN))
            r.check(resp.status_code == 404,
                    f"відхилено: {evil!r}", resp.status_code)

        print("\n--- довідники ---")
        resp = await client.get("/api/logs/services", headers=head(SYSADMIN))
        body = resp.json()
        r.check({s["service"] for s in body["services"]} == {"api", "bot", "scheduler"},
                "перелік сервісів")
        r.check(body["logDir"] == LOG_DIR, "показано каталог журналу")

        resp = await client.get("/api/logs/events?service=api", headers=head(SYSADMIN))
        events = {e["event"] for e in resp.json()["events"]}
        r.check(events == {"http.request", "auth.login.failed", "boom"},
                "події зібрані з файлу", events)

        resp = await client.get("/api/logs/events?service=api", headers=head(MANAGER))
        r.check(resp.status_code == 403, "довідник подій теж закритий")

        print("\n--- журналу немає ---")
        resp = await client.get("/api/logs?service=scheduler", headers=head(SYSADMIN))
        r.check(resp.status_code == 200 and resp.json()["returned"] == 0,
                "відсутній файл — порожньо, а не помилка", resp.status_code)


asyncio.run(scenario())
r.done()
