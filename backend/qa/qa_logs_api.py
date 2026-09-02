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

from qa_common import Report, seed_operators                             # noqa: E402

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
    # Токени видані на менеджерів 5 і 7. Відколи перепустка звіряється з
    # базою при кожному зверненні, їх треба справді створити — інакше
    # набір перевіряв би не права ролі, а те, що незнайомця не пускають.
    from shop.db import init_db
    from shop.repo.factory import open_repo

    await init_db()
    async with open_repo() as _repo:
        await seed_operators(_repo, {
            5: ("shopadmin", "Адмін", OperatorRole.ADMIN),
            7: ("manager", "Менеджер", OperatorRole.MANAGER),
        })

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
        r.check({s["service"] for s in body["services"]}
                == {"security", "api", "bot", "scheduler"},
                "перелік сервісів", [s["service"] for s in body["services"]])
        r.check(body["logDir"] == LOG_DIR, "показано каталог журналу")

        resp = await client.get("/api/logs/events?service=api", headers=head(SYSADMIN))
        events = {e["event"] for e in resp.json()["events"]}
        # Події безпеки дублюються і в спільний журнал теж — там їх видно
        # поруч із рештою запитів тієї ж хвилини. Тому перевіряємо
        # входження, а не точну рівність: набір сам породжує їх, коли
        # перевіряє відмови в доступі.
        r.check({"http.request", "auth.login.failed", "boom"} <= events,
                "події зібрані з файлу", events)

        resp = await client.get("/api/logs/events?service=api", headers=head(MANAGER))
        r.check(resp.status_code == 403, "довідник подій теж закритий")

        print("\n--- скачування файлу ---")
        resp = await client.get("/api/logs/api/download", headers=head(SYSADMIN))
        r.check(resp.status_code == 200, "файл віддається", resp.status_code)
        r.check(b"http.request" in resp.content, "вміст той самий")
        r.check("attachment" in resp.headers.get("content-disposition", ""),
                "браузер збереже файл, а не відкриє")

        print("\n--- файл повторює вибірку на екрані ---")
        # Раніше «скачати» завжди віддавало весь файл: вибрана кількість
        # записів і фільтри на нього не впливали ніяк, і людина отримувала
        # десять мегабайтів там, де відібрала три рядки.
        resp = await client.get("/api/logs/api/download?limit=1", headers=head(SYSADMIN))
        lines = [ln for ln in resp.content.decode().splitlines() if ln.strip()]
        r.check(len(lines) == 1, "у файлі рівно стільки рядків, скільки вибрано",
                len(lines))
        r.check(resp.headers.get("x-records") == "1",
                "кількість названа в заголовку", resp.headers.get("x-records"))

        resp = await client.get("/api/logs/api/download?level=error",
                                headers=head(SYSADMIN))
        lines = [ln for ln in resp.content.decode().splitlines() if ln.strip()]
        r.check(len(lines) == 1 and "boom" in lines[0],
                "фільтр рівня діє й на файл", lines)

        resp = await client.get("/api/logs/api/download?search=petro",
                                headers=head(SYSADMIN))
        body = resp.content.decode()
        r.check("petro" in body and "boom" not in body,
                "пошук діє й на файл")

        # У файлі час має рости згори вниз: його читають очима або
        # згодовують jq, і зворотний порядок там заважав би.
        resp = await client.get("/api/logs/api/download?limit=100",
                                headers=head(SYSADMIN))
        times = [json.loads(ln)["time"]
                 for ln in resp.content.decode().splitlines() if ln.strip()]
        r.check(times == sorted(times), "у файлі хронологічний порядок", times)

        print("\n--- повний файл нікуди не подівся ---")
        resp = await client.get("/api/logs/api/download?full=1", headers=head(SYSADMIN))
        r.check(b"\xd1\x86\xd0\xb5 \xd0\xbd\xd0\xb5 JSON" in resp.content,
                "full=1 віддає файл цілком, включно з битими рядками")
        r.check("-full.log" in resp.headers.get("content-disposition", ""),
                "у назві видно, що файл повний",
                resp.headers.get("content-disposition"))

        print("\n--- скільки місця займають журнали ---")
        resp = await client.get("/api/logs/services", headers=head(SYSADMIN))
        usage = resp.json().get("usage") or {}
        r.check(usage.get("totalBytes", 0) > 0, "сумарний розмір названо",
                usage.get("totalBytes"))
        r.check(usage.get("budgetBytes", 0) >= usage.get("totalBytes", 0),
                "стеля не менша за зайняте", usage)
        r.check(usage.get("maxBytesPerFile", 0) > 0 and "backupCount" in usage,
                "видно, за яких налаштувань працює прокрутка", usage)

        # Прокручені файли рахуються разом із поточним: без цього панель
        # показувала «2 МБ» там, де на диску лежало під шістдесят.
        (Path(LOG_DIR) / "api.log.1").write_text("x" * 5000, encoding="utf-8")
        resp = await client.get("/api/logs/services", headers=head(SYSADMIN))
        api_row = next(s for s in resp.json()["services"] if s["service"] == "api")
        r.check(api_row["rotatedFiles"] == 1, "прокручений файл помічено",
                api_row)
        r.check(api_row["totalBytes"] == api_row["sizeBytes"] + api_row["rotatedBytes"],
                "у сумі враховано і поточний, і прокручений", api_row)
        (Path(LOG_DIR) / "api.log.1").unlink()

        for token, label in [(ADMIN, "адміністратор"), (MANAGER, "менеджер")]:
            resp = await client.get("/api/logs/api/download", headers=head(token))
            r.check(resp.status_code == 403, f"{label} не скачає журнал", resp.status_code)

        for evil in ("../../etc/passwd", "API", "api.log"):
            resp = await client.get(f"/api/logs/{evil}/download", headers=head(SYSADMIN))
            r.check(resp.status_code == 404, f"відхилено: {evil!r}", resp.status_code)

        resp = await client.get("/api/logs/scheduler/download", headers=head(SYSADMIN))
        r.check(resp.status_code == 404, "порожній журнал — 404, а не битий файл")

        print("\n--- журналу немає ---")
        resp = await client.get("/api/logs?service=scheduler", headers=head(SYSADMIN))
        r.check(resp.status_code == 200 and resp.json()["returned"] == 0,
                "відсутній файл — порожньо, а не помилка", resp.status_code)


asyncio.run(scenario())
r.done()
