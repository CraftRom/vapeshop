"""КОПІЇ: доступ, перелік, завантаження, запобіжники відновлення."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/tmp")
DATA_ROOT = tempfile.mkdtemp(prefix="qa_data_")
BACKUP_DIR = str(Path(DATA_ROOT) / "backups")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  DASHBOARD_LOGIN="root", DASHBOARD_PASSWORD="Pa$$w0rd123",
                  ELFAR_DATA_ROOT=DATA_ROOT,
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_backups.db")

os.makedirs(LOG_DIR if "LOG_DIR" in dir() else BACKUP_DIR, exist_ok=True)


# Прибираємо базу від попереднього запуску.
#
# Набір, який проходить лише на чистій базі, гірший за відсутній: він
# падає через власні залишки, і час іде на з'ясування, що зламався тест,
# а не застосунок. Саме так qa_legal і qa_e2e показували провал, хоч
# застосунок працював.
import pathlib as _pathlib  # noqa: E402

for _leftover in _pathlib.Path("/tmp").glob("qa_backups*"):
    if _leftover.is_file():
        _leftover.unlink(missing_ok=True)

from qa_common import Report                             # noqa: E402

r = Report("КОПІЇ")

import httpx                                             # noqa: E402
from api.auth import create_token                        # noqa: E402
from api.main import app                                 # noqa: E402
from api.routers.backups import PGDUMP_SIGNATURE, _resolve  # noqa: E402
from shop.entities import OperatorRole                   # noqa: E402

SYSADMIN = create_token("root", OperatorRole.SYSADMIN, 0, "Root")
ADMIN = create_token("shopadmin", OperatorRole.ADMIN, 5, "Адмін")
MANAGER = create_token("manager", OperatorRole.MANAGER, 7, "Менеджер")

# Готуємо два «дампи»: підпис справжній, вміст умовний
(Path(BACKUP_DIR) / "elfar-2026-08-20.dump").write_bytes(PGDUMP_SIGNATURE + b"\x00" * 2000)
(Path(BACKUP_DIR) / "elfar-manual-2026-08-25_1200.dump").write_bytes(
    PGDUMP_SIGNATURE + b"\x00" * 3000)
# Стороннє в каталозі не має потрапляти в перелік
(Path(BACKUP_DIR) / "нотатка.txt").write_text("не дамп", encoding="utf-8")


async def scenario():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        def head(token):
            return {"Authorization": f"Bearer {token}"}

        print("\n--- доступ ---")
        for label, token, expected in [("системний адміністратор", SYSADMIN, 200),
                                       ("адміністратор", ADMIN, 403),
                                       ("менеджер", MANAGER, 403)]:
            resp = await client.get("/api/backups", headers=head(token))
            r.check(resp.status_code == expected, f"перелік: {label} → {expected}",
                    resp.status_code)

        resp = await client.get("/api/backups")
        r.check(resp.status_code in (401, 403), "без токена не пускає", resp.status_code)

        # Найнебезпечніша дія в усьому розділі — вона має бути закрита теж
        resp = await client.post("/api/backups/x.dump/restore",
                                 data={"confirm": "x.dump"}, headers=head(ADMIN))
        r.check(resp.status_code == 403, "відновлення закрите для адміністратора",
                resp.status_code)

        print("\n--- перелік ---")
        resp = await client.get("/api/backups", headers=head(SYSADMIN))
        body = resp.json()
        names = [x["name"] for x in body["items"]]
        r.check(len(names) == 2, "лише файли .dump", names)
        r.check("нотатка.txt" not in names, "стороннє не потрапило в перелік")
        r.check(names[0] == "elfar-manual-2026-08-25_1200.dump",
                "найновіше першим", names[0])
        r.check(body["items"][0]["manual"] is True, "ручний знімок позначений")
        r.check(body["items"][1]["manual"] is False, "автоматичний не позначений")
        r.check(body["totalBytes"] > 5000, "сумарний розмір рахується", body["totalBytes"])
        r.check(body["freeBytes"] > 0, "вільне місце показано")

        print("\n--- скачування ---")
        resp = await client.get("/api/backups/elfar-2026-08-20.dump/download",
                                headers=head(SYSADMIN))
        r.check(resp.status_code == 200, "файл віддається", resp.status_code)
        r.check(resp.content.startswith(PGDUMP_SIGNATURE), "вміст той самий")

        resp = await client.get("/api/backups/elfar-2026-08-20.dump/download",
                                headers=head(MANAGER))
        r.check(resp.status_code == 403, "менеджер не скачає дамп бази")

        print("\n--- вихід за межі каталогу ---")
        # Дамп містить телефони й адреси всіх клієнтів. Імʼя файлу приходить
        # із запиту, тож перевірка тут найважливіша в модулі.
        for evil in ("../../etc/passwd", "..%2f..%2fetc%2fpasswd", "нотатка.txt",
                     "elfar-2026-08-20.dump.bak", "", "../backups/x.dump"):
            resp = await client.get(f"/api/backups/{evil}/download", headers=head(SYSADMIN))
            r.check(resp.status_code in (404, 405, 422),
                    f"відхилено: {evil!r}", resp.status_code)

        print("\n--- завантаження з комп'ютера ---")
        resp = await client.post(
            "/api/backups/upload",
            files={"file": ("свій.dump", PGDUMP_SIGNATURE + b"\x00" * 100,
                            "application/octet-stream")},
            headers=head(SYSADMIN),
        )
        r.check(resp.status_code == 201, "дамп прийнято", resp.status_code)
        uploaded = resp.json()["name"]
        r.check(uploaded.endswith(".dump"), "збережено з правильним розширенням", uploaded)
        r.check("/" not in uploaded and ".." not in uploaded,
                "імʼя знешкоджено", uploaded)

        resp = await client.post(
            "/api/backups/upload",
            files={"file": ("шкідник.dump", "це не дамп".encode("utf-8"), "application/octet-stream")},
            headers=head(SYSADMIN),
        )
        r.check(resp.status_code == 415, "не-дамп відхилено за підписом", resp.status_code)

        print("\n--- підтвердження відновлення ---")
        # Кнопка «так» натискається рефлекторно, тому підтвердження —
        # переписана вручну назва. Перевіряємо, що воно справді потрібне.
        target = "elfar-2026-08-20.dump"
        for wrong in ("", "так", "yes", "elfar-2026-08-20", target.upper()):
            resp = await client.post(f"/api/backups/{target}/restore",
                                     data={"confirm": wrong}, headers=head(SYSADMIN))
            r.check(resp.status_code == 400,
                    f"невірне підтвердження відхилено: {wrong!r}", resp.status_code)

        resp = await client.post(f"/api/backups/{target}/restore",
                                 headers=head(SYSADMIN))
        r.check(resp.status_code == 422, "без поля confirm — 422", resp.status_code)

        print("\n--- видалення ---")
        resp = await client.delete(f"/api/backups/{uploaded}", headers=head(MANAGER))
        r.check(resp.status_code == 403, "менеджер не стирає копії")

        resp = await client.delete(f"/api/backups/{uploaded}", headers=head(SYSADMIN))
        r.check(resp.status_code == 204, "копію стерто", resp.status_code)
        r.check(not (Path(BACKUP_DIR) / uploaded).exists(), "файлу більше немає")

        resp = await client.delete("/api/backups/немає.dump", headers=head(SYSADMIN))
        r.check(resp.status_code == 404, "неіснуючий файл — 404")


print("\n--- перевірка імені окремо ---")
for evil in ("../x.dump", "a/b.dump", "нотатка.txt", "x.dump\x00"):
    try:
        _resolve(evil)
        r.check(False, f"мало бути відхилено: {evil!r}")
    except Exception as exc:
        r.check("404" in str(exc) or "не знайдено" in str(exc),
                f"відхилено на рівні функції: {evil!r}")

asyncio.run(scenario())
r.done()
