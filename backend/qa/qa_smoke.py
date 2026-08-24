"""SMOKE: чи система взагалі жива."""
import sys; sys.path.insert(0,"/tmp")
from qa_common import boot, init_data, Report
app, Session, fake = boot("/tmp/qa_smoke.db")
from fastapi.testclient import TestClient
c = TestClient(app)
r = Report("SMOKE")

h = c.get("/api/health")
r.check(h.status_code == 200, "health відповідає", h.status_code)
r.check("status" in h.json(), "health несе статус", h.json())

login = c.post("/api/auth/login", json={"login":"admin","password":"secret"})
r.check(login.status_code == 200, "вхід у панель", login.status_code)
A = {"Authorization": f"Bearer {login.json()['access_token']}"}

for name, path in [("замовлення","/api/orders"), ("каталог","/api/catalog/products"),
                   ("категорії","/api/catalog/categories"), ("клієнти","/api/customers"),
                   ("промокоди","/api/promos"), ("розсилки","/api/broadcasts"),
                   ("оператори","/api/operators"), ("налаштування","/api/settings"),
                   ("статистика","/api/stats/summary"), ("оператори-статистика","/api/stats/by-operator"),
                   ("непрочитані","/api/orders/unread/counts")]:
    resp = c.get(path, headers=A)
    r.check(resp.status_code == 200, f"панель: {name}", f"{resp.status_code} {resp.text[:80]}")

H = init_data(9001)
for name, path in [("конфіг","/api/shop/config"), ("bootstrap","/api/shop/bootstrap")]:
    resp = c.get(path, headers=H)
    r.check(resp.status_code == 200, f"вітрина: {name}", resp.status_code)

upd = {"update_id":1,"message":{"message_id":1,"date":0,"chat":{"id":9001,"type":"private"},
       "from":{"id":9001,"is_bot":False,"first_name":"К"},"text":"/start"}}
resp = c.post("/api/telegram/hook/777001", json=upd)
r.check(resp.status_code == 200, "бот приймає апдейт", resp.status_code)

# Документація навмисно вимикається в продакшні — перевіряємо лише узгодженість
import api.main as _m
_expect = 200 if _m._docs_on else 404
r.check(c.get("/openapi.json").status_code == _expect, "OpenAPI відповідає режиму docs")
sys.exit(1 if r.done() else 0)
