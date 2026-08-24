"""NEGATIVE: навмисно неправильні дані."""
import sys; sys.path.insert(0,"/tmp")
from qa_common import boot, init_data, Report
app, Session, fake = boot("/tmp/qa_neg.db")
from fastapi.testclient import TestClient
c = TestClient(app); r = Report("NEGATIVE")
A = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"login":"admin","password":"secret"}).json()["access_token"]}
cat = c.post("/api/catalog/categories", json={"name":"К","sort_order":0,"is_active":True}, headers=A).json()
pr = c.post("/api/catalog/products", json={"category_id":cat["id"],"name":"Т","price":"300","stock":5,"is_active":True}, headers=A).json()
H = init_data(9101); c.post("/api/shop/age-confirm", headers=H)

print("\n--- порожні та надто довгі значення ---")
r.check(c.post("/api/catalog/categories", json={"name":""}, headers=A).status_code == 422, "порожня назва категорії")
r.check(c.post("/api/catalog/categories", json={"name":"я"*500}, headers=A).status_code == 422, "надто довга назва")
r.check(c.post("/api/catalog/products", json={"category_id":cat["id"],"name":"Т","price":"-5"}, headers=A).status_code == 422, "відʼємна ціна")
r.check(c.post("/api/catalog/products", json={"category_id":cat["id"],"name":"Т","price":"10","stock":-3}, headers=A).status_code == 422, "відʼємний залишок")

print("\n--- неправильні типи ---")
r.check(c.post("/api/catalog/products", json={"category_id":"абв","name":"Т","price":"10"}, headers=A).status_code == 422, "текст замість id")
r.check(c.post("/api/catalog/products", json={"category_id":cat["id"],"name":"Т","price":"дорого"}, headers=A).status_code == 422, "текст замість ціни")
r.check(c.get("/api/orders", params={"limit":"багато"}, headers=A).status_code == 422, "текст замість limit")
r.check(c.get("/api/orders", params={"limit":99999}, headers=A).status_code == 422, "limit понад межу")
r.check(c.get("/api/orders", params={"date_from":"вчора"}, headers=A).status_code == 422, "невалідна дата")

print("\n--- неіснуючі сутності ---")
for path in ["/api/orders/999999", "/api/catalog/products/999999", "/api/promos/999999",
             "/api/operators/999999", "/api/broadcasts/999999"]:
    code = c.get(path, headers=A).status_code
    r.check(code == 404, f"404 для {path}", code)

print("\n--- вітрина ---")
r.check(c.post("/api/shop/cart", json={"product_id":999999,"delta":1}, headers=H).status_code in (200,404,409), "неіснуючий товар у кошик не ламає", c.post("/api/shop/cart", json={"product_id":999999,"delta":1}, headers=H).status_code)
cart = c.get("/api/shop/cart", headers=H).json()
r.check(all(l["product_id"] != 999999 for l in cart["lines"]), "фантомний товар не осів у кошику", cart["lines"])
r.check(c.post("/api/shop/cart", json={"product_id":pr["id"],"delta":10**9}, headers=H).status_code == 422, "величезна кількість відхилена")
r.check(c.post("/api/shop/checkout", json={"contact_name":"К"}, headers=H).status_code == 422, "неповна форма замовлення")
r.check(c.post("/api/shop/checkout", json={"contact_surname":"Ш","contact_name":"К","contact_phone":"+380671112233","city":"К","address":"1","payment_method":"біткоїн"}, headers=H).status_code == 422, "невідомий спосіб оплати")

print("\n--- порожній кошик ---")
c.delete("/api/shop/cart", headers=H)
resp = c.post("/api/shop/checkout", json={"contact_surname":"Ш","contact_name":"К","contact_phone":"+380671112233","city":"К","address":"1","payment_method":"cod"}, headers=H)
r.check(resp.status_code == 400, "порожній кошик не оформлюється", resp.status_code)

print("\n--- дублікати ---")
c.post("/api/promos", json={"code":"DUP","type":"percent","value":"5","is_active":True}, headers=A)
dup = c.post("/api/promos", json={"code":"DUP","type":"percent","value":"5","is_active":True}, headers=A)
r.check(dup.status_code in (409,422), "дубль промокоду відхилено", dup.status_code)
c.post("/api/operators", json={"login":"dupop","password":"kvitka2026"}, headers=A)
r.check(c.post("/api/operators", json={"login":"dupop","password":"kvitka2026"}, headers=A).status_code == 409, "дубль логіна оператора")

print("\n--- зіпсований JSON ---")
r.check(c.post("/api/auth/login", content="{зламано", headers={"Content-Type":"application/json"}).status_code == 422, "невалідний JSON")
sys.exit(1 if r.done() else 0)
