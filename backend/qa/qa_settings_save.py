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

from qa_common import Report                              # noqa: E402

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
invisible = incoming - outgoing
r.check(not invisible,
        "усе, що приймається, повертається назад", sorted(invisible))


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

        print("\n--- зміни переживають перечитування ---")
        # Кеш налаштувань живе в памʼяті процесу. Якщо він не скидається
        # при записі, панель показуватиме нове, а бот працюватиме зі старим.
        from shop.services.shop_settings import current, get_shop_settings
        from shop.repo.factory import open_repo

        await client.put("/api/settings", json={"shop_name": "Після кешу"},
                         headers=head(SYSADMIN))
        async with open_repo() as repo:
            fresh = await get_shop_settings(repo)
        r.check(fresh.shop_name == "Після кешу", "репозиторій бачить нове значення",
                fresh.shop_name)
        r.check(current().shop_name == "Після кешу", "кеш оновлено", current().shop_name)

        print("\n--- права ---")
        # Інфраструктура закрита навіть від адміністратора магазину: помилка
        # в токені бота чи розкладі бекапів кладе весь магазин.
        for field in sorted(INFRA_FIELDS)[:5]:
            if field not in ShopSettingsIn.model_fields:
                continue
            value = sample(field, ShopSettingsIn.model_fields[field])
            resp = await client.put("/api/settings", json={field: value},
                                    headers=head(ADMIN))
            r.check(resp.status_code == 403, f"адміністратор не змінює {field}",
                    resp.status_code)

        for field in sorted(OPERATOR_FIELDS - INFRA_FIELDS)[:3]:
            if field not in ShopSettingsIn.model_fields:
                continue
            value = sample(field, ShopSettingsIn.model_fields[field])
            resp = await client.put("/api/settings", json={field: value},
                                    headers=head(MANAGER))
            r.check(resp.status_code == 200, f"менеджер змінює {field}",
                    resp.status_code)

        resp = await client.put("/api/settings", json={"shop_name": "Чуже"},
                                headers=head(MANAGER))
        r.check(resp.status_code == 403, "менеджер не змінює назву магазину",
                resp.status_code)

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
