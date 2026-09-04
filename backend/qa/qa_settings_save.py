"""НАЛАШТУВАННЯ: кожне поле справді зберігається й повертається.

Найпідступніший різновид помилки в налаштуваннях — тиха. Людина міняє
значення, бачить «Збережено», а через тиждень з'ясовує, що воно ніколи не
діяло: поле є у формі, але загубилося дорогою до бази або назад.

Тому перевіряємо не окремі поля, а всі одразу й автоматично: перелік
береться зі схеми, а не переписується руками. Нове поле потрапляє під
перевірку саме, без правки цього файлу.
"""
import asyncio
import dataclasses
import os
import sys
import tempfile

sys.path.insert(0, "/tmp")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  DASHBOARD_LOGIN="root", DASHBOARD_PASSWORD="Pa$$w0rd123",
                  ELFAR_DATA_ROOT=tempfile.mkdtemp(prefix="qa_settings_"),
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_settings.db")

from qa_common import Report, seed_operators                              # noqa: E402

r = Report("НАЛАШТУВАННЯ")

import httpx                                              # noqa: E402
from api.auth import create_token                         # noqa: E402
from api.main import app                                  # noqa: E402
from api.routers.settings import INFRA_FIELDS, OPERATOR_FIELDS  # noqa: E402
from api.schemas import ShopSettingsIn, ShopSettingsOut    # noqa: E402
from shop.entities import OperatorRole                    # noqa: E402
from shop.services.shop_settings import ShopSettings      # noqa: E402

SYSADMIN = create_token("root", OperatorRole.SYSADMIN, 0, "Root")
ADMIN = create_token("shopadmin", OperatorRole.ADMIN, 5, "Адмін")
MANAGER = create_token("manager", OperatorRole.MANAGER, 7, "Менеджер")


# ------------------------------------------------------- цілісність переліків

print("\n--- схеми узгоджені між собою ---")
incoming = set(ShopSettingsIn.model_fields)
outgoing = set(ShopSettingsOut.model_fields)
stored = {f.name for f in dataclasses.fields(ShopSettings)}

r.check(not (incoming - stored),
        "усе, що приймається, є в моделі налаштувань", sorted(incoming - stored))

# Поле, яке можна записати, але не можна прочитати назад, — це поле, яке
# ніхто ніколи не перевірить. Форма покаже дефолт замість збереженого.
#
# Виняток один і названий поіменно, а не шаблоном «усе зі словом key»:
# ключ Нової пошти створює накладні від імені магазину, тож віддавати
# його назад не можна. Замість значення панель читає ознаку
# novaposhta_connected. Поіменний перелік потрібен саме для того, щоб
# наступний секрет потрапляв сюди свідомо, а не за збігом у назві.
WRITE_ONLY = {"novaposhta_api_key"}

invisible = incoming - outgoing - WRITE_ONLY
r.check(not invisible,
        "усе, що приймається, повертається назад (крім секретів)",
        sorted(invisible))

# Зворотний бік винятку: секрет справді має бути невидимим. Без цієї
# перевірки досить прибрати рядок вище — і ключ поїде в панель.
r.check(not (WRITE_ONLY & outgoing),
        "секрети не потрапляють у відповідь", sorted(WRITE_ONLY & outgoing))
r.check("novaposhta_connected" in outgoing,
        "замість ключа віддається ознака «підключено»")

# Прочитати й зберегти без змін — те, що робить панель щоразу.
#
# Саме тут ховалась поломка, якої не бачив жоден із наборів: відповідь
# містить похідну ознаку novaposhta_connected, панель шле форму назад
# цілком, а перелік дозволених полів на записі — поіменний. Зайве ім'я
# відхиляло весь запит, і системний адміністратор не міг зберегти нічого.
# Перевірки нижче ганяли рукописні тіла запитів і тому проходили.
READ_ONLY = outgoing - incoming
r.check(bool(READ_ONLY),
        "у відповіді є похідні поля, яких немає на записі", sorted(READ_ONLY))


def sample(name: str, field):
    """Значення, відмінне від типового, щоб зміна була помітна."""
    annotation = str(field.annotation)
    if "bool" in annotation:
        return True
    if name == "min_age":
        return 21
    if name == "admin_ids":
        return "111,222"
    if name == "admin_chat_id":
        return -1001234567890
    if "Decimal" in annotation:
        # API віддає Decimal рядком — так JSON не втрачає точності на
        # відсотках і сумах. Порівнюємо в тому ж вигляді.
        return "7.0"
    if "int" in annotation:
        # Межі різні: година 0–23, порція від 10, вік від 18. Беремо
        # значення з нижньої межі поля, якщо вона задана.
        low = getattr(next((mm for mm in field.metadata
                            if hasattr(mm, "ge")), None), "ge", None)
        return max(int(low), 7) if low is not None else 7
    if "float" in annotation:
        return 7.0
    if name == "timezone":
        return "Europe/Warsaw"
    if name in ("public_url",):
        return "https://example-shop.test"
    if name in ("bot_username", "miniapp_short_name"):
        return "probe_bot"
    if name == "currency":
        return "PLN"
    return f"проба-{name}"


async def scenario():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        def head(token):
            return {"Authorization": f"Bearer {token}"}

        from shop.db import init_db

        await init_db()


        print("\n--- кожне поле зберігається ---")
        failed = []
        for name, field in ShopSettingsIn.model_fields.items():
            value = sample(name, field)
            resp = await client.put("/api/settings", json={name: value},
                                    headers=head(SYSADMIN))
            if resp.status_code != 200:
                failed.append((name, resp.status_code, resp.text[:80]))
                continue

            back = await client.get("/api/settings", headers=head(SYSADMIN))
            got = back.json().get(name)
            if name not in outgoing:
                continue
            if got != value:
                failed.append((name, "повернулось інше", f"{got!r} замість {value!r}"))

        r.check(not failed, f"перевірено полів: {len(ShopSettingsIn.model_fields)}",
                failed[:3])

        print("\n--- кілька полів одразу ---")
        batch = {"shop_name": "Пакетна назва", "min_age": 21, "bonus_enabled": True}
        resp = await client.put("/api/settings", json=batch, headers=head(SYSADMIN))
        r.check(resp.status_code == 200, "пакетне збереження", resp.status_code)
        back = (await client.get("/api/settings", headers=head(SYSADMIN))).json()
        for key, value in batch.items():
            r.check(back.get(key) == value, f"пакет: {key}", back.get(key))

        print("\n--- прочитати й зберегти без змін ---")
        # Рівно те, що робить панель: показала форму, людина натиснула
        # «Зберегти». Жоден із наборів цього не робив — усі надсилали
        # рукописні тіла запитів, — і тому пропустив поломку, через яку
        # системний адміністратор не міг зберегти нічого взагалі.
        shown = (await client.get("/api/settings", headers=head(SYSADMIN))).json()
        again = await client.put("/api/settings", json=shown, headers=head(SYSADMIN))
        r.check(again.status_code != 422,
                "відповідь із налаштуваннями приймається назад без правок",
                (again.status_code, again.text[:160]))

        # Якщо колись доведеться відхилити похідне поле — воно має
        # відхилятись поодинці, а не разом з усім запитом.
        editable = {k: v for k, v in shown.items() if k in set(ShopSettingsIn.model_fields)}
        resaved = await client.put("/api/settings", json=editable, headers=head(SYSADMIN))
        r.check(resaved.status_code == 200,
                "збереження без похідних полів проходить", resaved.status_code)

        print("\n--- кожна роль зберігає свої розділи ---")
        # Панель показує ролі лише її розділи, але на збереження раніше
        # йшли ВСІ поля форми. Бекенд перевіряє права поіменно й
        # відхиляє запит цілком — тож менеджер не міг зберегти нічого, а
        # адміністратор спотикався об інфраструктурні поля. Ззовні це
        # виглядало як «налаштування не працюють».
        #
        # Перевіряємо саме те, що робить панель: беремо відповідь, лишаємо
        # поля своєї ролі й надсилаємо назад.
        # Облікові записи мають існувати в базі: токен живий лише поки
        # живий оператор — так влаштована відкликуваність доступу.
        from shop.repo.factory import open_repo as _open

        async with _open() as _seed_repo:
            await seed_operators(_seed_repo, {
                5: ("shopadmin", "Адмін", OperatorRole.ADMIN),
                7: ("manager", "Менеджер", OperatorRole.MANAGER),
            })

        shown = (await client.get("/api/settings", headers=head(SYSADMIN))).json()
        writable = set(ShopSettingsIn.model_fields)

        for role, allowed, label in [
            (MANAGER, OPERATOR_FIELDS - INFRA_FIELDS, "менеджер"),
            (ADMIN, writable - INFRA_FIELDS, "адміністратор"),
            (SYSADMIN, writable, "системний адміністратор"),
        ]:
            payload = {k: v for k, v in shown.items() if k in allowed}
            resp = await client.put("/api/settings", json=payload, headers=head(role))
            r.check(resp.status_code == 200,
                    f"{label}: зберігає свої розділи",
                    (resp.status_code, resp.text[:120]))
            r.check(bool(payload), f"{label}: розділи для запису взагалі є",
                    len(payload))

        print("\n--- зміни переживають перечитування ---")
        # Кеш налаштувань живе в памʼяті процесу. Якщо він не скидається
        # при записі, панель показуватиме нове, а бот працюватиме зі старим.
        from shop.services.shop_settings import current, get_shop_settings
        from shop.repo.factory import open_repo

        async with open_repo() as _repo:
            await seed_operators(_repo, {
                5: ("shopadmin", "Адмін", OperatorRole.ADMIN),
                7: ("manager", "Менеджер", OperatorRole.MANAGER),
            })

        await client.put("/api/settings", json={"shop_name": "Після кешу"},
                         headers=head(SYSADMIN))
        async with open_repo() as repo:
            fresh = await get_shop_settings(repo)
        r.check(fresh.shop_name == "Після кешу", "репозиторій бачить нове значення",
                fresh.shop_name)
        r.check(current().shop_name == "Після кешу", "кеш оновлено", current().shop_name)

        print("\n--- права: кожне поле, а не вибірка ---")
        # Перевіряємо весь перелік, бо саме тут вибіркова перевірка
        # безглузда: одне забуте поле — і адміністратор магазину міняє
        # токен бота, а помітять це, коли бот замовкне.
        leaked_admin, leaked_manager = [], []
        for field in sorted(INFRA_FIELDS):
            if field not in ShopSettingsIn.model_fields:
                continue
            value = sample(field, ShopSettingsIn.model_fields[field])
            for token, bucket in ((ADMIN, leaked_admin), (MANAGER, leaked_manager)):
                resp = await client.put("/api/settings", json={field: value},
                                        headers=head(token))
                if resp.status_code != 403:
                    bucket.append((field, resp.status_code))

        r.check(not leaked_admin,
                f"адміністратор не змінює жодне з {len(INFRA_FIELDS)} інфраструктурних",
                leaked_admin[:3])
        r.check(not leaked_manager,
                "менеджер не змінює жодне інфраструктурне", leaked_manager[:3])

        print("\n--- менеджер обмежений своїм ---")
        allowed = OPERATOR_FIELDS - INFRA_FIELDS
        forbidden_for_manager = []
        for field in sorted(set(ShopSettingsIn.model_fields) - allowed):
            value = sample(field, ShopSettingsIn.model_fields[field])
            resp = await client.put("/api/settings", json={field: value},
                                    headers=head(MANAGER))
            if resp.status_code == 200:
                forbidden_for_manager.append(field)
        r.check(not forbidden_for_manager,
                "менеджеру недоступне все поза його переліком",
                forbidden_for_manager[:3])

        for field in sorted(allowed):
            if field not in ShopSettingsIn.model_fields:
                continue
            value = sample(field, ShopSettingsIn.model_fields[field])
            resp = await client.put("/api/settings", json={field: value},
                                    headers=head(MANAGER))
            r.check(resp.status_code == 200, f"менеджер змінює {field}",
                    resp.status_code)

        print("\n--- системний адміністратор може все ---")
        blocked = []
        for field in sorted(ShopSettingsIn.model_fields):
            value = sample(field, ShopSettingsIn.model_fields[field])
            resp = await client.put("/api/settings", json={field: value},
                                    headers=head(SYSADMIN))
            if resp.status_code != 200:
                blocked.append((field, resp.status_code))
        r.check(not blocked, "жодне поле не закрите від власника .env",
                blocked[:3])

        print("\n--- сміття відхиляється ---")
        for payload, label in [
            ({"min_age": 5}, "вік нижче межі"),
            ({"min_age": "багато"}, "вік рядком"),
            ({"timezone": "Марс/Олімп"}, "неіснуюча зона"),
            ({"невідоме_поле": 1}, "невідоме поле"),
        ]:
            resp = await client.put("/api/settings", json=payload, headers=head(SYSADMIN))
            r.check(resp.status_code in (400, 422),
                    f"{label} → відхилено", resp.status_code)


asyncio.run(scenario())
r.done()
