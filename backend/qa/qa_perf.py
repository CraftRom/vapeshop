"""PERFORMANCE: час відповіді під навантаженням."""
import sys, time, statistics; sys.path.insert(0,"/tmp")
from qa_common import boot, init_data, Report
app, Session, fake = boot("/tmp/qa_perf.db")
from fastapi.testclient import TestClient
c = TestClient(app); r = Report("PERFORMANCE")

A = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"login":"admin","password":"secret"}).json()["access_token"]}
cat = c.post("/api/catalog/categories", json={"name":"К","sort_order":0,"is_active":True}, headers=A).json()
print("наповнення: 200 товарів, 60 клієнтів, 200 замовлень…")
for i in range(200):
    c.post("/api/catalog/products", json={"category_id":cat["id"],"name":f"Товар {i}",
        "description":"опис "*20,"price":str(100+i),"stock":50,"is_active":True}, headers=A)
heads=[]
for i in range(60):
    h = init_data(20000+i); c.post("/api/shop/age-confirm", headers=h); heads.append(h)
    c.post("/api/shop/cart", json={"product_id":1,"delta":2}, headers=h)
for i in range(200):
    h = heads[i % 60]
    c.post("/api/shop/cart", json={"product_id":(i % 50)+1,"delta":1}, headers=h)
    c.post("/api/shop/checkout", json={"contact_surname":"Ш","contact_name":"К",
        "contact_phone":"+380671112233","city":"К","address":"1","payment_method":"cod"}, headers=h)

def bench(label, fn, n=20, budget_ms=900):
    times=[]
    for _ in range(n):
        t0=time.perf_counter(); resp=fn(); times.append((time.perf_counter()-t0)*1000)
        assert resp.status_code == 200, (label, resp.status_code, resp.text[:120])
    p50=statistics.median(times); p95=sorted(times)[int(n*0.95)-1]
    print(f"  {label:34} p50 {p50:7.1f} мс   p95 {p95:7.1f} мс")
    r.check(p95 < budget_ms, f"{label}: p95 у межах {budget_ms} мс", f"{p95:.0f} мс")

print("\n--- панель ---")
bench("список замовлень (200)", lambda: c.get("/api/orders", params={"limit":200}, headers=A))
bench("каталог (200 товарів)", lambda: c.get("/api/catalog/products", headers=A))
bench("статистика", lambda: c.get("/api/stats/summary", headers=A))
bench("розріз по операторах", lambda: c.get("/api/stats/by-operator", headers=A))
bench("непрочитані", lambda: c.get("/api/orders/unread/counts", headers=A))
bench("пошук замовлень", lambda: c.get("/api/orders", params={"search":"К"}, headers=A))
bench("фільтр за датою", lambda: c.get("/api/orders", params={"date_from":"2020-01-01"}, headers=A))

print("\n--- вітрина ---")
H = heads[0]
bench("bootstrap", lambda: c.get("/api/shop/bootstrap", headers=H))
bench("каталог вітрини", lambda: c.get("/api/shop/products", headers=H))
bench("кошик", lambda: c.get("/api/shop/cart", headers=H))
bench("історія замовлень", lambda: c.get("/api/shop/orders", headers=H))
sys.exit(1 if r.done() else 0)
