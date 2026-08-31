"""Змінні оточення: що де задається і хто має пріоритет."""
import sys; sys.path.insert(0,"/tmp")
from dataclasses import fields as dfields
from qa_common import boot, init_data, Report
app, Session, fake = boot("/tmp/qa_env.db")
from fastapi.testclient import TestClient
c = TestClient(app); r = Report("ENV")

from shop.config import Settings, settings as env
from shop.services.shop_settings import ShopSettings, current

A = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"login":"admin","password":"secret"}).json()["access_token"]}

print("\n--- класифікація ---")
runtime = {f.name for f in dfields(ShopSettings)}
SECRETS = {"bot_token","jwt_secret","dashboard_password","dashboard_login","webhook_secret",
           "cron_secret","redis_url","database_url","postgres_password"}
INFRA = {"serverless","db_pool_size","db_pool_overflow","postgres_host",
         "postgres_port","postgres_user","postgres_db","enable_api_docs","cors_origins",
         "backup_dir","scheduler_interval_seconds","log_dir","log_json","log_level","media_dir"}
unclassified = sorted(set(Settings.model_fields) - runtime - SECRETS - INFRA)
r.check(not unclassified, "кожна змінна віднесена до категорії", unclassified)

print("\n--- панель має пріоритет над оточенням ---")
c.put("/api/settings", json={"public_url":"https://нова.example.com".replace("нова","new"),
                             "bot_username":"newbot"}, headers=A)
r.check(current().public_url == "https://new.example.com", "адреса з панелі перекриває .env",
        current().public_url)
r.check(current().bot_username == "newbot", "імʼя бота з панелі перекриває .env")

print("\n--- звіт про стан сервера ---")
rep = c.get("/api/settings/environment", headers=A)
r.check(rep.status_code == 200, "звіт доступний адміністратору", rep.status_code)
items = {i["key"]: i for i in rep.json()["items"]}
r.check(all({"key","ok","level","note"} <= set(i) for i in items.values()), "структура повна")
r.check(items.get("Адреса сайту", {}).get("ok") is True,
        "звіт бачить адресу, задану в панелі", items.get("Адреса сайту"))
r.check(all(not any(str(v).startswith("777001:") for v in i.values()) for i in items.values()),
        "значень секретів у звіті немає")

print("\n--- права ---")
c.post("/api/operators", json={"login":"olena","name":"О","password":"kvitka2026"}, headers=A)
O = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"login":"olena","password":"kvitka2026"}).json()["access_token"]}
r.check(c.get("/api/settings/environment", headers=O).status_code == 403,
        "менеджер не бачить стану сервера")
r.check(c.get("/api/settings/environment").status_code in (401,403), "без токена закрито")

print("\n--- секрети не редагуються з панелі ---")
for field in ["bot_token","jwt_secret","webhook_secret","cron_secret","database_url"]:
    resp = c.put("/api/settings", json={field: "зламано"}, headers=A)
    changed = getattr(current(), field, None)
    r.check(changed is None, f"{field} не потрапляє в налаштування", changed)

print("\n--- сміття при копіюванні значень ---")
from shop.config import Settings as _S
PASTED = [
    ("bot_token", '"777001:ABC"', "777001:ABC"),
    ("bot_token", " 777001:ABC ", "777001:ABC"),
    ("public_url", "https://www.elfar.pp.ua/", "https://www.elfar.pp.ua"),
    ("bot_username", "@elfar1_bot", "elfar1_bot"),
    ("miniapp_short_name", "/elfar/", "elfar"),
]
for field, raw, expect in PASTED:
    got = getattr(_S(**{field: raw}), field)
    r.check(got == expect, f"{field}: {raw!r} → {expect!r}", repr(got))

# пробіли всередині значень зберігаються
r.check(_S(dashboard_password="  два слова  ").dashboard_password == "два слова",
        "пробіли всередині пароля вціліли")

sys.exit(1 if r.done() else 0)
