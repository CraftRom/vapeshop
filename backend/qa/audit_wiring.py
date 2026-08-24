"""Ревізія комплектності: чи кожна можливість підключена на всіх рівнях."""
import json, pathlib, re, sys

# Корінь проєкту — на два рівні вище цього файлу (backend/qa/…)
root = pathlib.Path(__file__).resolve().parents[2]
fails = []
def check(cond, label, detail=""):
    print(f"  {'✓' if cond else '✗'} {label}" + ("" if cond else f" — {detail}"))
    if not cond: fails.append(label)

def read(p):
    f = root / p
    return f.read_text() if f.exists() else ""

print("=== ФАЙЛИ ===")
must = [
 "vercel.json","firestore.indexes.json","firestore.rules","requirements.txt","api/index.py",
 "backend/shop/entities.py","backend/shop/models.py","backend/shop/config.py","backend/shop/links.py",
 "backend/shop/repo/base.py","backend/shop/repo/sql.py","backend/shop/repo/firestore.py",
 "backend/shop/repo/docstore.py","backend/shop/repo/firestore_store.py",
 "backend/shop/services/shop_service.py","backend/shop/services/shop_settings.py",
 "backend/shop/services/order_chat.py","backend/shop/services/notifications.py",
 "backend/shop/services/wishlist.py","backend/shop/services/passwords.py","backend/shop/services/broadcast.py",
 "backend/api/main.py","backend/api/auth.py","backend/api/schemas.py","backend/api/webapp_auth.py",
 "backend/bot/factory.py","backend/bot/middlewares.py","backend/bot/keyboards.py","backend/bot/texts.py",
 "backend/bot/greeting.py","backend/bot/handlers/chat.py","backend/bot/handlers/group.py",
 "backend/tests_repo.py","backend/tests_contracts.py","backend/qa/run_all.sh",
 "miniapp/package.json","miniapp/vite.config.js","miniapp/index.html","miniapp/Dockerfile","miniapp/nginx.conf",
 "miniapp/src/App.jsx","miniapp/src/api.js","miniapp/src/telegram.js","miniapp/src/styles.css",
 "miniapp/src/screens/Catalog.jsx","miniapp/src/screens/Checkout.jsx","miniapp/src/screens/Profile.jsx",
 "miniapp/src/screens/Chat.jsx","miniapp/src/screens/ProductPage.jsx","miniapp/src/screens/Wishlists.jsx",
 "dashboard/src/App.jsx","dashboard/src/api.js","dashboard/src/pages/OrderPage.jsx",
 "dashboard/src/pages/Operators.jsx","dashboard/src/pages/Settings.jsx","dashboard/src/pages/Overview.jsx",
 "deploy/docker-compose.prod.yml","deploy/nginx/app.conf","docs/DEPLOY.md","docs/VERCEL.md",
]
missing = [m for m in must if not (root/m).exists()]
check(not missing, f"усі {len(must)} ключових файлів на місці", missing)

print("\n=== РОУТЕРИ API ===")
main = read("backend/api/main.py")
for r in ["catalog","orders","customers","promos","broadcasts","stats","operators",
          "settings as settings_router","shop as shop_router","cron","telegram"]:
    check(r.split()[0] in main, f"роутер підключено: {r.split()[0]}")

print("\n=== БОТ ===")
factory = read("backend/bot/factory.py")
for h in ["group","admin","start","catalog","cart","checkout","profile","chat"]:
    check(f"{h}.router" in factory, f"хендлер зареєстровано: {h}")
for m in ["PrivateOnlyMiddleware","RepositoryMiddleware","BlockedUserMiddleware","AgeGateMiddleware"]:
    check(m in factory, f"мідлвар: {m}")
check("bot_id()" in factory, "адреса вебхука містить ідентифікатор бота")

print("\n=== МАРШРУТИ VERCEL ===")
vj = json.loads(read("vercel.json"))
srcs = [r.get("src") for r in vj["routes"] if "src" in r]
for s in ["/api/(.*)", "/app", "/app/", "/app/(.+)"]:
    check(s in srcs, f"маршрут {s}")
check(any(b["src"].startswith("miniapp") for b in vj["builds"]), "вітрина збирається на Vercel")

print("\n=== ФРОНТ: ПІДКЛЮЧЕННЯ ЕКРАНІВ ===")
app = read("miniapp/src/App.jsx")
for screen in ["Catalog","Checkout","Profile","ChatList","ChatRoom","ProductPage","Wishlists","SavePicker","AgeGate"]:
    check(screen in app, f"вітрина використовує {screen}")
dash = read("dashboard/src/App.jsx")
for page in ["Orders","OrderPage","Catalog","Customers","Promos","Broadcasts","Operators","Settings","Overview"]:
    check(page in dash, f"панель використовує {page}")

print("\n=== КЛІЄНТИ API ===")
mapi = read("miniapp/src/api.js")
# Фото товару вітрина тягне прямим fetch із заголовком підпису, а не через
# клієнт api — інакше не додати X-Telegram-Init-Data до <img>
for m in ["bootstrap","config","categories","products","cart","checkout","promo/check","profile","chat","wishlists"]:
    check(m in mapi, f"вітрина вміє: {m}")
dapi = read("dashboard/src/api.js")
for m in ["operators","settings","messages","sendMessage","unread","byOperator","purge","fileUrl"]:
    check(m in dapi, f"панель вміє: {m}")

print("\n=== СТИЛІ (клас використано → має існувати) ===")
for pack, css_path, srcs_glob in [("вітрина","miniapp/src/styles.css","miniapp/src"),
                                  ("панель","dashboard/src/styles.css","dashboard/src")]:
    css = read(css_path)
    used = set()
    for f in (root/srcs_glob).rglob("*.jsx"):
        for m in re.findall(r'className="([^"{}]+)"', f.read_text()):
            used.update(m.split())
        # У шаблонних рядках беремо лише статичну частину до ${…}:
        # решта — вирази, а не імена класів
        for m in re.findall(r'className=\{`([^`]*)`\}', f.read_text()):
            static = re.sub(r'\$\{[^}]*\}', ' ', m)
            used.update(w for w in static.split() if re.fullmatch(r'[a-z][a-z0-9-]*', w))
    used = {c for c in used if re.fullmatch(r'[a-z][a-z0-9-]*', c)}
    absent = sorted(c for c in used if not re.search(rf'\.{re.escape(c)}\b', css))
    check(not absent, f"{pack}: усі класи описані в CSS", absent[:12])

print("\n=== МІГРАЦІЇ Й ІНДЕКСИ ===")
migs = sorted((root/"backend/alembic/versions").glob("*.py"))
check(len(migs) == 6, f"міграцій: {len(migs)}")
idx = json.loads(read("firestore.indexes.json"))["indexes"]
check(len(idx) >= 25, f"індексів Firestore: {len(idx)}")
cols = {i["collectionGroup"] for i in idx}
for c in ["orders","products","categories","users","order_messages","carts","broadcasts","promo_uses"]:
    check(c in cols, f"індекси для колекції {c}")

print("\n=== РОЗГОРТАННЯ НА СВОЄМУ СЕРВЕРІ ===")
compose = read("deploy/docker-compose.prod.yml")
for svc in ["api","bot","dashboard","miniapp","nginx","db","redis"]:
    check(f"\n  {svc}:" in compose, f"сервіс {svc}")
nginx = read("deploy/nginx/app.conf")
check("/app" in nginx and "miniapp_static" in nginx, "nginx віддає вітрину")

sys.exit(1 if fails else 0)
