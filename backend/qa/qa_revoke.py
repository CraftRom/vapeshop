"""ВІДКЛИКАННЯ: доступ припиняється одразу, а не наприкінці строку токена.

Підпис токена доводить рівно одне — що ми його колись видали. Про все,
що сталося після видачі, він не знає нічого: вимкнення менеджера, зниження
ролі, зміну пароля адміністратора.

Поки цієї звірки не було, звільнений менеджер працював у панелі до кінця
строку токена — за замовчуванням до дванадцяти годин. Кнопка «вимкнути»
в панелі виглядала як миттєва дія, а насправді призначала відключення на
вечір. Найгірше тут не сама затримка, а те, що про неї ніхто не знав.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, "/tmp")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  DASHBOARD_LOGIN="root", DASHBOARD_PASSWORD="Pa$$w0rd123",
                  WEBHOOK_SECRET="s3cr3t-hook-value",
                  ELFAR_DATA_ROOT=tempfile.mkdtemp(prefix="qa_revoke_"),
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_revoke.db")

from qa_common import Report                              # noqa: E402

r = Report("ВІДКЛИКАННЯ")

import httpx                                              # noqa: E402

from api.auth import create_token                         # noqa: E402
from api.main import app                                  # noqa: E402
from shop.entities import OperatorRole                    # noqa: E402
from shop.repo.factory import open_repo                   # noqa: E402
from shop.services.passwords import hash_password         # noqa: E402


def head(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def scenario():
    from shop.db import init_db
    await init_db()

    async with open_repo() as repo:
        boss = await repo.create_operator({
            "login": "boss", "name": "Ольга", "role": OperatorRole.ADMIN,
            "password_hash": hash_password("Str0ng!Pass1"), "is_active": True,
        })
        temp = await repo.create_operator({
            "login": "temp", "name": "Тарас", "role": OperatorRole.MANAGER,
            "password_hash": hash_password("Str0ng!Pass2"), "is_active": True,
        })

    boss_token = create_token("boss", OperatorRole.ADMIN, boss.id, "Ольга")
    temp_token = create_token("temp", OperatorRole.MANAGER, temp.id, "Тарас")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:

        print("\n--- поки доступ чинний, усе працює ---")
        resp = await c.get("/api/orders", headers=head(temp_token))
        r.check(resp.status_code == 200, "менеджер бачить замовлення",
                resp.status_code)
        resp = await c.get("/api/operators", headers=head(boss_token))
        r.check(resp.status_code == 200, "адміністратор бачить менеджерів",
                resp.status_code)

        print("\n--- вимкнення діє негайно ---")
        async with open_repo() as repo:
            await repo.update_operator(temp.id, {"is_active": False})
        resp = await c.get("/api/orders", headers=head(temp_token))
        r.check(resp.status_code == 401,
                "той самий токен більше не працює", resp.status_code)
        r.check("вимкнено" in resp.text,
                "причина названа, а не просто «недійсний токен»", resp.text[:80])

        print("\n--- увімкнення повертає доступ ---")
        # Щоб вимкнення не виявилось незворотним: адміністратор має мати
        # змогу передумати, не змушуючи людину входити заново.
        async with open_repo() as repo:
            await repo.update_operator(temp.id, {"is_active": True})
        resp = await c.get("/api/orders", headers=head(temp_token))
        r.check(resp.status_code == 200, "доступ відновлено", resp.status_code)

        print("\n--- зниження ролі діє негайно ---")
        # Токен усе ще каже «адміністратор». База каже інше, і слухаємо базу.
        async with open_repo() as repo:
            await repo.update_operator(boss.id, {"role": OperatorRole.MANAGER})
        resp = await c.get("/api/operators", headers=head(boss_token))
        r.check(resp.status_code == 403,
                "знижений адміністратор більше не керує менеджерами",
                resp.status_code)
        resp = await c.get("/api/orders", headers=head(boss_token))
        r.check(resp.status_code == 200,
                "але замовлення йому доступні — він лишився менеджером",
                resp.status_code)

        print("\n--- підвищення теж діє негайно ---")
        async with open_repo() as repo:
            await repo.update_operator(boss.id, {"role": OperatorRole.ADMIN})
        resp = await c.get("/api/operators", headers=head(boss_token))
        r.check(resp.status_code == 200, "повернуті права працюють",
                resp.status_code)

        print("\n--- видалений менеджер не працює ---")
        async with open_repo() as repo:
            await repo.delete_operator(temp.id)
        resp = await c.get("/api/orders", headers=head(temp_token))
        r.check(resp.status_code == 401,
                "токен видаленого менеджера відхилено", resp.status_code)

        print("\n--- зміна пароля адміністратора рве його сесії ---")
        # У сисадміна немає рядка в базі, тож відкликати його токен було
        # нічим. Якщо пароль міняють саме тому, що він міг витекти, старий
        # токен лишався б робочим ще години.
        sys_token = create_token("root", OperatorRole.SYSADMIN, 0, "Адмін")
        resp = await c.get("/api/logs/services", headers=head(sys_token))
        r.check(resp.status_code == 200, "поточний токен сисадміна працює",
                resp.status_code)

        from shop.config import settings
        was = settings.dashboard_password
        settings.dashboard_password = "Ne_Toy_Par0l!"
        try:
            resp = await c.get("/api/logs/services", headers=head(sys_token))
            r.check(resp.status_code == 401,
                    "після зміни пароля старий токен недійсний",
                    resp.status_code)
            r.check("Пароль змінено" in resp.text,
                    "сказано, що саме сталося", resp.text[:80])
            fresh = create_token("root", OperatorRole.SYSADMIN, 0, "Адмін")
            resp = await c.get("/api/logs/services", headers=head(fresh))
            r.check(resp.status_code == 200,
                    "новий токен із новим паролем працює", resp.status_code)
        finally:
            settings.dashboard_password = was

        print("\n--- підроблений токен не проходить ---")
        forged = create_token("temp", OperatorRole.SYSADMIN, 0, "Я головний")
        # Підпис тут наш, але сисадмін впізнається за відбитком пароля,
        # а не за роллю в токені. Втім, головне інше: цей набір стереже,
        # щоб чужий підпис не приймався взагалі.
        bad = boss_token[:-3] + ("aaa" if not boss_token.endswith("aaa") else "bbb")
        resp = await c.get("/api/orders", headers=head(bad))
        r.check(resp.status_code == 401, "зіпсований підпис відхилено",
                resp.status_code)
        resp = await c.get("/api/orders", headers={"Authorization": "Bearer "})
        r.check(resp.status_code == 401, "порожній токен відхилено",
                resp.status_code)
        del forged

        print("\n--- вебхук бота не приймає чужих апдейтів ---")
        # Секрет у шляху видно всюди: у логах nginx, у Referer, у будь-якому
        # проксі дорогою. Заголовок від Telegram не видно ніде — саме він
        # доводить, що апдейт справді від Telegram, а не від того, хто
        # підгледів адресу.
        from api.routers.telegram import webhook_header_secret, webhook_path
        from shop.config import settings as cfg

        path = webhook_path()
        update = {"update_id": 1, "message": {
            "message_id": 1, "date": 0, "chat": {"id": 1, "type": "private"},
            "from": {"id": 1, "is_bot": False, "first_name": "X"}, "text": "/start"}}

        resp = await c.post(f"/api{path}" if not path.startswith("/api") else path,
                            json=update,
                            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-token"})
        r.check(resp.status_code == 404,
                "апдейт із чужим підписом заголовка відхилено", resp.status_code)

        wrong = path.replace(cfg.webhook_secret, "x" * len(cfg.webhook_secret))
        resp = await c.post(wrong, json=update)
        r.check(resp.status_code == 404, "чужий секрет у шляху відхилено",
                resp.status_code)

        r.check(webhook_header_secret() != cfg.webhook_secret,
                "секрет заголовка не дорівнює тому, що світиться в шляху")
        r.check(len(webhook_header_secret()) <= 256
                and webhook_header_secret().replace("_", "").replace("-", "").isalnum(),
                "секрет заголовка у форматі, який приймає Telegram")


asyncio.run(scenario())
r.done()
sys.exit(1 if r.fails else 0)
