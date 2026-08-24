"""SECURITY: доступ, ін'єкції, токени, витік секретів."""
import sys, json, base64, time; sys.path.insert(0,"/tmp")
from qa_common import boot, init_data, Report, TOKEN
app, Session, fake = boot("/tmp/qa_sec.db")
from fastapi.testclient import TestClient
import jwt as pyjwt
c = TestClient(app); r = Report("SECURITY")

A = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"login":"admin","password":"secret"}).json()["access_token"]}
c.post("/api/operators", json={"login":"olena","name":"Олена","password":"kvitka2026"}, headers=A)
O = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"login":"olena","password":"kvitka2026"}).json()["access_token"]}
cat = c.post("/api/catalog/categories", json={"name":"К","sort_order":0,"is_active":True}, headers=A).json()
pr = c.post("/api/catalog/products", json={"category_id":cat["id"],"name":"Т","price":"300","stock":9,"is_active":True}, headers=A).json()

print("\n--- Broken Access Control ---")
for path in ["/api/orders","/api/customers","/api/promos","/api/settings","/api/operators","/api/stats/summary"]:
    r.check(c.get(path).status_code in (401,403), f"без токена закрито: {path}", c.get(path).status_code)
r.check(c.get("/api/operators", headers=O).status_code == 403, "оператор не бачить операторів")
r.check(c.put("/api/settings", json={"card_number":"9999"}, headers=O).status_code == 403, "оператор не змінює реквізити")

print("\n--- JWT ---")
raw = A["Authorization"].split()[1]
head, payload, sig = raw.split(".")
tampered = json.loads(base64.urlsafe_b64decode(payload + "=="))
tampered["role"] = "admin"; tampered["sub"] = "hacker"
forged = ".".join([head, base64.urlsafe_b64encode(json.dumps(tampered).encode()).decode().rstrip("="), sig])
r.check(c.get("/api/orders", headers={"Authorization": f"Bearer {forged}"}).status_code == 401, "підміна payload відхилена")
none_alg = pyjwt.encode({"sub":"x","role":"admin","exp":int(time.time())+999}, "", algorithm="none")
r.check(c.get("/api/orders", headers={"Authorization": f"Bearer {none_alg}"}).status_code == 401, "alg=none відхилено")
other = pyjwt.encode({"sub":"x","role":"admin","exp":int(time.time())+999}, "інший-ключ", algorithm="HS256")
r.check(c.get("/api/orders", headers={"Authorization": f"Bearer {other}"}).status_code == 401, "чужий ключ відхилено")
expired = pyjwt.encode({"sub":"admin","role":"admin","exp":int(time.time())-10}, "t"*32, algorithm="HS256")
r.check(c.get("/api/orders", headers={"Authorization": f"Bearer {expired}"}).status_code == 401, "прострочений токен")
# оператор не може підвищити роль зміною свого ж токена
opraw = O["Authorization"].split()[1]
oh, op_, os_ = opraw.split(".")
opay = json.loads(base64.urlsafe_b64decode(op_ + "==")); opay["role"]="admin"
esc = ".".join([oh, base64.urlsafe_b64encode(json.dumps(opay).encode()).decode().rstrip("="), os_])
r.check(c.get("/api/operators", headers={"Authorization": f"Bearer {esc}"}).status_code == 401, "оператор не підвищить роль")

print("\n--- initData ---")
r.check(c.get("/api/shop/config").status_code == 401, "вітрина без підпису закрита")
bad = init_data(1)["X-Telegram-Init-Data"].replace("hash=", "hash=deadbeef")
r.check(c.get("/api/shop/config", headers={"X-Telegram-Init-Data": bad}).status_code == 401, "підроблений підпис")
victim = init_data(7001); c.post("/api/shop/age-confirm", headers=victim)
tampered_id = victim["X-Telegram-Init-Data"].replace("7001", "7002")
r.check(c.get("/api/shop/config", headers={"X-Telegram-Init-Data": tampered_id}).status_code == 401, "підміна tg_id")
r.check(c.get("/api/shop/config", headers=A).status_code == 401, "JWT панелі не працює у вітрині")

print("\n--- ін'єкції ---")
inj = "'; DROP TABLE orders; --"
resp = c.get("/api/orders", params={"search": inj}, headers=A)
r.check(resp.status_code == 200, "SQL-ін'єкція в пошуку не ламає", resp.status_code)
r.check(c.get("/api/orders", headers=A).status_code == 200, "таблиця замовлень ціла")
xss = "<script>alert(1)</script>"
p = c.post("/api/catalog/products", json={"category_id":cat["id"],"name":xss,"price":"1","stock":1,"is_active":True}, headers=A).json()
r.check(p["name"] == xss, "XSS зберігається як текст, не виконується на сервері")
from shop.services.notifications import esc
r.check("<script>" not in esc(xss) and "&lt;script&gt;" in esc(xss), "екранування для Telegram працює")

print("\n--- витік секретів ---")
body = c.get("/api/health").text + c.get("/api/shop/config", headers=victim).text
# Шукаємо саме значення секретів, а не підрядки: "hook" збігається
# зі словом webhook_configured і давав хибне спрацювання
for secret in ["777001:TESTTOKEN", "t"*32, "cron", "hook"]:
    import re as _re
    leaked = _re.search(rf"(?<![\w-]){_re.escape(secret)}(?![\w-])", body)
    r.check(not leaked, f"секрет не в публічній відповіді: {secret[:14]}", leaked and leaked.group(0))
prod = c.get(f"/api/shop/products/{pr['id']}", headers=victim).json()
r.check("photo_file_id" not in prod, "file_id не витікає у вітрину")
ops = c.get("/api/operators", headers=A).json()
r.check(all("password_hash" not in o for o in ops), "хеш пароля не віддається")

print("\n--- службові точки ---")
r.check(c.get("/api/telegram-setup").status_code == 404, "setup без секрета закритий")
r.check(c.get("/api/telegram-detach?token=невірний").status_code == 404, "detach без секрета закритий")
r.check(c.post("/api/telegram/невірний/777001", json={}).status_code == 404, "вебхук із чужим секретом")
r.check(c.post("/api/telegram/hook/999999", json={}).status_code == 409, "вебхук чужого бота")

print("\n--- перебір пароля ---")
codes = {c.post("/api/auth/login", json={"login":"admin","password":f"спроба{i}"}).status_code for i in range(12)}
r.check(codes == {401}, "невірні паролі стабільно 401", codes)
r.check(c.post("/api/auth/login", json={"login":"admin","password":"secret"}).status_code == 200, "правильний пароль після спроб працює")
sys.exit(1 if r.done() else 0)
