"""Юридичні документи: реквізити, попередження про неповноту, версії."""
import sys; sys.path.insert(0,"/tmp")
from qa_common import boot, init_data, Report
app, Session, fake = boot("/tmp/qa_legal.db")
from fastapi.testclient import TestClient
c = TestClient(app); r = Report("LEGAL")

A = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"login":"admin","password":"secret"}).json()["access_token"]}
H = init_data(6001)

print("\n--- поки реквізити не задані ---")
cfg = c.get("/api/shop/config", headers=H).json()
r.check("seller" in cfg, "конфіг несе блок продавця", list(cfg)[:8])
# У блоці є ще вік і валюта — вони мають дефолти, тож перевіряємо
# саме реквізити продавця
blanks = {k: v for k, v in cfg["seller"].items() if k.startswith("SELLER_")}
r.check(all(not v for v in blanks.values()), "реквізити продавця порожні за замовчуванням", blanks)

print("\n--- адміністратор заповнює ---")
resp = c.put("/api/settings", json={
    "seller_name":"ФОП Галицький Дмитро", "seller_code":"1234567890",
    "seller_address":"м. Хмельницький, вул. Прикладна, 1",
    "seller_email":"shop@elfar.pp.ua", "seller_phone":"+380671112233"}, headers=A)
r.check(resp.status_code == 200, "реквізити збережено", resp.text[:120])
cfg = c.get("/api/shop/config", headers=H).json()
r.check(cfg["seller"]["SELLER_NAME"] == "ФОП Галицький Дмитро", "назва дійшла до вітрини", cfg["seller"])
r.check(cfg["seller"]["SELLER_EMAIL"] == "shop@elfar.pp.ua", "пошта дійшла")

print("\n--- оператор не змінює реквізити ---")
c.post("/api/operators", json={"login":"olena","name":"Олена","password":"kvitka2026"}, headers=A)
O = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"login":"olena","password":"kvitka2026"}).json()["access_token"]}
r.check(c.put("/api/settings", json={"seller_name":"Хтось інший"}, headers=O).status_code == 403,
        "реквізити продавця — лише адміністратор")

print("\n--- вік у документах ---")
c.put("/api/settings", json={"min_age":21}, headers=A)
cfg = c.get("/api/shop/config", headers=H).json()
r.check(cfg["min_age"] == 21, "вік для оферти береться з налаштувань", cfg["min_age"])
sys.exit(1 if r.done() else 0)
