"""ЖУРНАЛ БЕЗПЕКИ: подія доходить від місця, де сталася, до людини.

Ланцюг тут довгий, і рветься він тихо. Подію записали, але вона не
потрапила в окремий файл. Файл є, але в ньому опинилися й тисячі
звичайних запитів. У панелі подія видно, але голим кодом, якого ніхто не
читає. Або найгірше: тривога записалась, а в канал не пішла — і про
підбір пароля дізналися через тиждень.

Тому набір перевіряє не окремі шматки, а весь шлях: подія → файл →
відбір за фільтром → підпис у панелі → сповіщення в канал.
"""
import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/tmp")

LOG_DIR = tempfile.mkdtemp(prefix="qa_seclog_")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  DASHBOARD_LOGIN="root", DASHBOARD_PASSWORD="Pa$$w0rd123",
                  WEBHOOK_SECRET="hook-secret-value",
                  ELFAR_DATA_ROOT=LOG_DIR, LOG_JSON="1",
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_seclog.db")

from qa_common import Report, seed_operators                # noqa: E402

r = Report("ЖУРНАЛ БЕЗПЕКИ")

import httpx                                                # noqa: E402

from api.auth import create_token                           # noqa: E402
from api.main import app                                    # noqa: E402
from shop.entities import OperatorRole                      # noqa: E402
from shop.repo.factory import open_repo                     # noqa: E402
from shop import security_log as seclog                     # noqa: E402

SYSADMIN = create_token("root", OperatorRole.SYSADMIN, 0, "Root")
MANAGER = create_token("manager", OperatorRole.MANAGER, 7, "Менеджер")


def head(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def read_security() -> list[dict]:
    path = Path(LOG_DIR) / "logs" / "security.log"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


print("\n--- каталог подій ---")
r.check(len(seclog.CATALOG) >= 15, "каталог не порожній", len(seclog.CATALOG))
for code, event in seclog.CATALOG.items():
    if event.severity not in seclog.SEVERITIES:
        r.check(False, f"{code}: невідома критичність", event.severity)
    if not event.title or not event.detail:
        r.check(False, f"{code}: немає підпису або пояснення")
r.check(all(e.severity in seclog.SEVERITIES for e in seclog.CATALOG.values()),
        "у кожної події відома критичність")
r.check(all(e.title and e.detail for e in seclog.CATALOG.values()),
        "у кожної події є підпис і пояснення — інакше в панелі буде "
        "голий код, якого ніхто не читає")
r.check(all(code.startswith("security.") for code in seclog.CATALOG),
        "усі коди в одному просторі імен — на цьому тримається "
        "відбір за префіксом")

print("\n--- невідомий код не зникає мовчки ---")
# Код із друкарською помилкою мусить лишити слід, а не порожній рядок.
unknown = seclog.describe("security.typo.here")
r.check(unknown.title == "security.typo.here", "невідомий код показує сам себе")
r.check("catalog" in unknown.detail.lower(),
        "пояснення підказує, що робити", unknown.detail)


async def scenario():
    from shop.db import init_db
    from shop.logging_setup import setup

    setup("api")
    await init_db()
    async with open_repo() as repo:
        await seed_operators(repo, {
            7: ("manager", "Менеджер", OperatorRole.MANAGER),
        })

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:

        print("\n--- події справді записуються ---")
        await c.post("/api/auth/login",
                     json={"login": "root", "password": "не той"})
        await c.post("/api/auth/login",
                     json={"login": "root", "password": "Pa$$w0rd123"})
        # Менеджер лізе туди, куди його роль не пускає
        await c.get("/api/logs/services", headers=head(MANAGER))
        # Чужий запит на адресу вебхука
        await c.post("/api/telegram/чужий-секрет/777001", json={"update_id": 1})

        for handler in logging.getLogger("security").handlers:
            handler.flush()

        records = read_security()
        codes = {rec.get("event") for rec in records}
        for expected in ("security.login.failed", "security.login.ok",
                         "security.access.denied", "security.webhook.bad_secret"):
            r.check(expected in codes, f"записано: {expected}", sorted(codes))

        print("\n--- у файлі безпеки лише безпека ---")
        # Головна причина заводити окремий файл. Якщо сюди протече хоч
        # частина звичайних запитів, шукати подію знову доведеться серед
        # тисяч рядків — тобто файл не дає нічого.
        strangers = [rec.get("event") for rec in records
                     if not str(rec.get("event", "")).startswith("security.")]
        r.check(not strangers, "жодного стороннього запису", strangers[:5])

        # Дочірні логери піднімають записи вгору, тож будь-який
        # logging.getLogger("security.щось") у чужому коді потрапив би
        # просто у файл безпеки. Фільтр це відсікає — перевіряємо, що він
        # там справді стоїть, а не лише виглядає як стоїть.
        logging.getLogger("security.stranger").warning(
            "не подія безпеки", extra={"event": "stranger.leak"})
        logging.getLogger("security").warning(
            "теж не подія", extra={"event": "direct.leak"})
        for handler in logging.getLogger("security").handlers:
            handler.flush()
        leaked = {rec.get("event") for rec in read_security()}
        r.check("stranger.leak" not in leaked and "direct.leak" not in leaked,
                "чужі записи у файл безпеки не протікають", sorted(leaked))
        r.check(all(rec.get("severity") in seclog.SEVERITIES for rec in records),
                "у кожного запису проставлена критичність")
        r.check(all(rec.get("detail") for rec in records),
                "у кожного запису є пояснення людською мовою")

        print("\n--- події видно і в спільному журналі ---")
        # Дублювання тут навмисне: у спільному журналі подія стоїть поруч
        # із рештою запитів тієї ж секунди, і саме там видно контекст.
        api_log = (Path(LOG_DIR) / "logs" / "api.log").read_text(encoding="utf-8")
        r.check("security.login.failed" in api_log,
                "подія безпеки є і в спільному журналі теж")

        print("\n--- журнал безпеки доступний через панель ---")
        resp = await c.get("/api/logs?service=security&limit=100",
                           headers=head(SYSADMIN))
        r.check(resp.status_code == 200, "журнал безпеки читається",
                resp.status_code)
        got = {rec["event"] for rec in resp.json()["records"]}
        r.check("security.login.failed" in got, "невдалий вхід у вибірці", got)

        resp = await c.get("/api/logs/services", headers=head(SYSADMIN))
        names = [s["service"] for s in resp.json()["services"]]
        r.check("security" in names, "безпека є в переліку журналів", names)
        r.check(names[0] == "security",
                "і стоїть першою — її відкривають частіше за решту", names)

        print("\n--- відбір за критичністю ---")
        resp = await c.get("/api/logs?service=security&severity=alarm&limit=100",
                           headers=head(SYSADMIN))
        alarms = resp.json()["records"]
        r.check(all(rec["severity"] == "alarm" for rec in alarms),
                "у вибірці лише тривоги",
                {rec["severity"] for rec in alarms})
        r.check(any(rec["event"] == "security.webhook.bad_secret" for rec in alarms),
                "чужий запит на вебхук — тривога")

        resp = await c.get("/api/logs?service=security&severity=notice&limit=100",
                           headers=head(SYSADMIN))
        notices = {rec["severity"] for rec in resp.json()["records"]}
        r.check("alarm" in notices,
                "«і вище», а не точний збіг: обравши «варте уваги», "
                "тривоги теж видно", notices)
        r.check("info" not in notices, "довідкові при цьому відсіяні", notices)

        print("\n--- відбір за групою подій ---")
        # Одна ситуація — три різні коди. Без збігу за префіксом довелося б
        # клацати їх поспіль, щоб зрозуміти одну історію.
        resp = await c.get("/api/logs?service=security&event=security.login&limit=100",
                           headers=head(SYSADMIN))
        logins = {rec["event"] for rec in resp.json()["records"]}
        r.check(logins == {"security.login.failed", "security.login.ok"},
                "«security.login» знаходить і вдалі входи, і невдалі", logins)

        resp = await c.get(
            "/api/logs?service=security&event=security.login.ok&limit=100",
            headers=head(SYSADMIN))
        exact = {rec["event"] for rec in resp.json()["records"]}
        r.check(exact == {"security.login.ok"},
                "точна назва так само працює", exact)

        print("\n--- довідник подій для фільтра ---")
        resp = await c.get("/api/logs/events?service=security",
                           headers=head(SYSADMIN))
        body = resp.json()
        r.check(len(body.get("catalog", [])) == len(seclog.CATALOG),
                "віддано весь каталог, а не лише те, що вже трапилось — "
                "інакше подію, якої ще не було, неможливо навіть знайти",
                len(body.get("catalog", [])))
        r.check(all(item.get("title") for item in body["events"]
                    if item["event"].startswith("security.")),
                "у кожної події є підпис для випадного списку")

        print("\n--- файл вивантажується за тими самими фільтрами ---")
        resp = await c.get(
            "/api/logs/security/download?severity=alarm&limit=100",
            headers=head(SYSADMIN))
        lines = [ln for ln in resp.content.decode().splitlines() if ln.strip()]
        r.check(lines, "файл не порожній", len(lines))
        r.check(all(json.loads(ln)["severity"] == "alarm" for ln in lines),
                "у файлі лише те, що відібрано на екрані")

        print("\n--- підбір пароля зупиняється ---")
        # Обмеження в nginx рахує спроби за адресою, тож підбір з десяти
        # адрес його обходить. Тут рахуємо на обліковий запис.
        from shop.services import login_guard
        login_guard.reset()

        limit = login_guard.max_attempts()
        codes = []
        for _ in range(limit + 2):
            resp = await c.post("/api/auth/login",
                                json={"login": "root", "password": "не той"})
            codes.append(resp.status_code)
        r.check(codes[0] == 401, "перші спроби — звичайна відмова", codes[0])
        r.check(codes[-1] == 429, "після перевищення вхід закривається",
                codes[-1])
        r.check(codes.count(429) >= 2,
                "закрито, а не одноразове попередження", codes)

        for handler in logging.getLogger("security").handlers:
            handler.flush()
        blocked = [rec for rec in read_security()
                   if rec.get("event") == "security.login.blocked"]
        r.check(blocked, "блокування записано в журнал безпеки")
        r.check(all(rec.get("severity") == "alarm" for rec in blocked),
                "блокування — тривога, тобто піде в канал")
        r.check(any(rec.get("attempts") for rec in blocked),
                "видно, скільки спроб було поспіль")

        # Правильний пароль під блокуванням теж не пускає: інакше
        # обмеження обходилось би тим самим підбором.
        resp = await c.post("/api/auth/login",
                            json={"login": "root", "password": "Pa$$w0rd123"})
        r.check(resp.status_code == 429,
                "під блокуванням не пускає навіть із вірним паролем",
                resp.status_code)

        # Інший логін не постраждав: блокування іменне, а не спільне.
        resp = await c.post("/api/auth/login",
                            json={"login": "manager", "password": "хиба"})
        r.check(resp.status_code == 401,
                "блокування одного запису не закриває вхід іншим",
                resp.status_code)

        login_guard.reset()
        resp = await c.post("/api/auth/login",
                            json={"login": "root", "password": "Pa$$w0rd123"})
        r.check(resp.status_code == 200, "після зняття вхід працює",
                resp.status_code)

        print("\n--- журнал безпеки закритий для менеджера ---")
        resp = await c.get("/api/logs?service=security", headers=head(MANAGER))
        r.check(resp.status_code == 403,
                "менеджер не читає журнал безпеки", resp.status_code)


asyncio.run(scenario())


print("\n--- відбір сповіщень у канал ---")
# Успішні входи трапляються десятки разів на день. Канал, у якому вони,
# ніхто не читатиме — а разом із ними перестануть читати й тривоги.
from shop.alerts import TelegramSecurityHandler                # noqa: E402

handler = TelegramSecurityHandler("api")


def fake(code: str) -> logging.LogRecord:
    event = seclog.describe(code)
    record = logging.LogRecord("security", logging.INFO, __file__, 1,
                               event.title, (), None)
    record.event = event.code
    record.severity = event.severity
    record.detail = event.detail
    record.security = True
    return record


r.check(not handler.filter(fake("security.login.ok")),
        "успішний вхід у канал не йде")
r.check(handler.filter(fake("security.login.failed")),
        "невдалий вхід — йде")
r.check(handler.filter(fake("security.webhook.bad_secret")),
        "чужий запит на вебхук — йде")

ordinary = logging.LogRecord("api", logging.ERROR, __file__, 1, "збій", (), None)
r.check(not handler.filter(ordinary),
        "звичайні помилки цей обробник не чіпає — для них є свій")

print("\n--- сповіщення читається з телефона ---")
text = handler._compose(fake("security.login.failed"))
r.check("Безпека" in text, "видно, що це подія безпеки")
r.check(seclog.describe("security.login.failed").detail[:20] in text,
        "є пояснення, а не лише код події")
r.check("security.login.failed" in text, "код теж є — для фільтра в панелі")

print("\n--- однакові події згортаються, різні адреси ні ---")
# Сто спроб підбору з одного місця в коді — це одна подія. З десяти
# адрес — уже десять, і згортати їх в одну означало б побачити першу й
# не побачити решти.
a, b = fake("security.login.failed"), fake("security.login.failed")
a.ip, b.ip = "1.2.3.4", "1.2.3.4"
r.check(handler._fingerprint(a) == handler._fingerprint(b),
        "та сама подія з тієї самої адреси — один відбиток")
b.ip = "5.6.7.8"
r.check(handler._fingerprint(a) != handler._fingerprint(b),
        "та сама подія з іншої адреси — інший відбиток")

r.done()
sys.exit(1 if r.fails else 0)
