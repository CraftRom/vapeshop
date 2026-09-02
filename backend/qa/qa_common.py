"""Спільний стенд для всіх наборів тестування."""
import asyncio, hashlib, hmac, json, os, time
from urllib.parse import urlencode
TOKEN = "777001:TESTTOKEN"

def boot(db_path):
    # Прибираємо базу від попереднього запуску.
    #
    # Набір, який проходить лише на чистій базі, гірший за відсутній: він
    # падає через власні залишки, і час іде на з'ясування, що зламався
    # тест, а не застосунок. Саме так qa_legal показував «реквізити не
    # порожні», а qa_e2e — «вік уже підтверджено»: у файлі лишалися дані
    # попереднього прогону.
    import pathlib

    for suffix in ("", "-wal", "-shm"):
        pathlib.Path(f"{db_path}{suffix}").unlink(missing_ok=True)

    os.environ.update(BOT_TOKEN=TOKEN, JWT_SECRET="t"*32, DASHBOARD_PASSWORD="secret",
                      CRON_SECRET="cron", WEBHOOK_SECRET="hook", ADMIN_CHAT_ID="-100111",
                      BOT_USERNAME="elfar1_bot", MINIAPP_SHORT_NAME="elfar",
                      PUBLIC_URL="https://www.elfar.pp.ua",
                      DATABASE_URL=f"sqlite+aiosqlite:///{db_path}")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from shop.models import Base
    from shop.repo.sql import SqlRepository
    from shop.repo.factory import get_repo
    from api.main import app
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    async def prep():
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
    asyncio.run(prep())

    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def override():
        async with Session() as s:
            yield SqlRepository(s)
    app.dependency_overrides[get_repo] = override

    class FakeBot:
        def __init__(s): s.sent = []; s._i = 0
        async def send_message(s, cid, text, **kw):
            s._i += 1; s.sent.append((cid, text)); return type("M", (), {"message_id": s._i})()
        async def get_file(s, fid): raise RuntimeError("Telegram недоступний у тесті")
    import api.routers.telegram as tg
    fake = FakeBot()
    tg._instances = lambda: (fake, None)
    return app, Session, fake


def init_data(tg_id, extra=None):
    fields = {"user": json.dumps({"id": tg_id, "first_name": "К"}),
              "auth_date": str(int(time.time()))}
    fields.update(extra or {})
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(fields)}


class Report:
    def __init__(s, title): s.title = title; s.fails = []; s.count = 0
    def check(s, cond, label, detail=""):
        s.count += 1
        print(f"  {'✓' if cond else '✗'} {label}" + ("" if cond else f" — {detail}"))
        if not cond: s.fails.append(label)
    def done(s):
        print(f"\n{s.title}: {s.count - len(s.fails)}/{s.count}")
        for f in s.fails: print("   ✗", f)
        return s.fails


async def seed_operators(repo, people: dict[int, tuple[str, str, object]]) -> None:
    """Створює менеджерів під заздалегідь видані токени.

    Наборам зручно робити токени наперед, одним рядком угорі файлу. Поки
    токен приймався за самим лише підписом, рядка в базі за ним могло не
    бути взагалі — і набори перевіряли доступ від людей, яких не існує.

    Тепер токен звіряється з базою на кожному запиті: вимкнений або
    видалений менеджер втрачає доступ негайно. Тож набір мусить створити
    тих, від чийого імені ходить, — інакше він перевіряє не права ролі,
    а те, що незнайомця не пускають.

    people: {operator_id: (логін, імʼя, роль)}
    """
    from shop.services.passwords import hash_password

    for operator_id, (login, name, role) in people.items():
        if await repo.get_operator(operator_id):
            continue
        # Ідентифікатор задаємо явно, а не покладаємось на порядок вставки:
        # токени виписані вгорі файлу під конкретні номери, і залежність
        # від того, кого створили першим, зламалася б від перестановки
        # двох рядків — мовчки, з перевіркою прав від чужого імені.
        created = await repo.create_operator({
            "id": operator_id,
            "login": login, "name": name, "role": role,
            "password_hash": hash_password("Qa!Passw0rd"), "is_active": True,
        })
        if created.id != operator_id:
            raise RuntimeError(
                f"Менеджер {login} отримав id={created.id}, а токен виписано "
                f"на {operator_id}."
            )
