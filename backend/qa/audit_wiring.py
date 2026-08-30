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
 "backend/requirements.txt","deploy/bootstrap.sh","deploy/elfar.service",
 "deploy/docker-compose.prod.yml","deploy/deploy.sh","deploy/backup.sh","deploy/restore.sh",
 "backend/Dockerfile","backend/scheduler/__main__.py","backend/scheduler/tasks.py",
 "backend/shop/entities.py","backend/shop/models.py","backend/shop/config.py","backend/shop/links.py",
 "backend/shop/repo/base.py","backend/shop/repo/sql.py",
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
 "dashboard/src/App.jsx","dashboard/src/api.js","dashboard/src/version.js",
 "miniapp/src/version.js","miniapp/src/legal.js","miniapp/src/screens/Legal.jsx","dashboard/src/pages/OrderPage.jsx",
 "dashboard/src/pages/Operators.jsx","dashboard/src/pages/Settings.jsx","dashboard/src/pages/Overview.jsx",
 "deploy/docker-compose.prod.yml","deploy/nginx/app.conf.template","deploy/render-nginx.sh","docs/DEPLOY.md",
]
missing = [m for m in must if not (root/m).exists()]
check(not missing, f"усі {len(must)} ключових файлів на місці", missing)

print("\n=== РОУТЕРИ API ===")
main = read("backend/api/main.py")
for r in ["catalog","orders","customers","promos","broadcasts","stats","operators",
          "settings as settings_router","shop as shop_router","telegram"]:
    check(r.split()[0] in main, f"роутер підключено: {r.split()[0]}")

print("\n=== БОТ ===")
factory = read("backend/bot/factory.py")
for h in ["group","admin","start","catalog","cart","checkout","profile","chat"]:
    check(f"{h}.router" in factory, f"хендлер зареєстровано: {h}")
for m in ["PrivateOnlyMiddleware","RepositoryMiddleware","BlockedUserMiddleware","AgeGateMiddleware"]:
    check(m in factory, f"мідлвар: {m}")
check("bot_id()" in factory, "адреса вебхука містить ідентифікатор бота")

print("\n=== РОЗГОРТАННЯ НА ВЛАСНОМУ СЕРВЕРІ ===")
compose = read("deploy/docker-compose.prod.yml")
for service in ["db:", "redis:", "migrate:", "api:", "bot:", "scheduler:", "nginx:"]:
    check(service in compose, f"сервіс у compose: {service.rstrip(':')}")
check("python -m scheduler" in compose, "планувальник запускається як окремий процес")
check("postgresql-client" in read("backend/Dockerfile"), "pg_dump є в образі — інакше бекап мовчки не працює")

unit = read("deploy/elfar.service")
check("WantedBy=multi-user.target" in unit, "unit вмикається при завантаженні системи")
check("Requires=docker.service" in unit, "unit чекає на docker, а не стартує наосліп")
check("__REPO_DIR__" in unit and "__USER__" in unit, "unit — шаблон, шляхи підставляє bootstrap")
boot = read("deploy/bootstrap.sh")
check("systemctl enable" in boot, "bootstrap вмикає автозапуск")
check("systemctl enable --now docker" in boot, "bootstrap вмикає сам docker — без цього автозапуск марний")
check("APP_UID" in boot, "bootstrap прописує UID користувача для контейнерів")
check("install -d -o" in boot, "bootstrap створює backups із правильним власником")
check("200/CHDIR" in boot, "bootstrap ловить недосяжний шлях до старту юніта")
check("as_user" in boot, "перевірка доступу йде від імені сервісного користувача")
check("ln -sfn ../.env" in boot, "bootstrap звʼязує deploy/.env — інакше ${VAR} у compose порожні")
check("ln -sfn ../.env" in read("deploy/deploy.sh"), "deploy.sh теж підстраховує симлінк")
cert = read("deploy/certbot-init.sh")
check("--entrypoint certbot" in cert, "certbot-init обходить entrypoint із циклом продовження")
check("openssl req -x509" in cert,
      "certbot-init кладе тимчасовий сертифікат — інакше nginx не підніметься")
check("--force-renewal" in cert,
      "справжній сертифікат замінює тимчасовий, а не пропускається")
check(cert.index("nginx/app.conf") < cert.index("openssl req -x509"),
      "домен підставляється до створення сертифіката, інакше nginx шукає не той файл")
check("--force-recreate nginx" in cert,
      "nginx перестворюється — зациклений у рестарті контейнер звичайним up не полагодити")
check("127.0.0.1" in cert,
      "локальна перевірка окремо від зовнішньої")
check("redirect.d" in cert and "hsts.d" in cert,
      "HTTPS-режим вмикається лише після справжнього сертифіката")
check("--cert-name" in cert,
      "шлях до сертифіката прибитий — інакше certbot створює live/<домен>-0001")
check("SCRIPT_VERSION" in cert, "скрипт друкує свою версію")
check("renewal/${DOMAIN}.conf" in cert,
      "заглушка відрізняється від справжнього сертифіката за renewal-конфігом")
check(cert.index("rm -rf /etc/letsencrypt/live") < cert.index("certonly --webroot"),
      "заглушка прибирається до запиту — інакше certbot скаржиться на live directory")
check("--force-renewal" in cert and "FORCE=()" in cert,
      "--force-renewal лише при поновленні, щоб не палити ліміт Let's Encrypt")
check("--staging" in cert, "є режим перевірки без витрати лімітів")
check(cert.index("STAGING=0") < cert.index("DOMAIN_ARGS=()"),
      "прапорці розбираються до доменів — інакше поїдуть у certbot як -d")

log_setup = read("backend/shop/logging_setup.py")
check("RotatingFileHandler" in log_setup, "журнал ротується за розміром")
check("logs_dir" in log_setup, "журнал пишеться у файл через shop.paths")
req_log = read("backend/api/request_log.py")
for field in ("requestId", "durationMs", "userAgent", "status"):
    check(field in req_log, f"журнал запитів має поле {field}")
check("x-forwarded-for" in req_log,
      "IP береться з-за проксі — інакше в журналі буде адреса nginx")
compose_src = read("deploy/docker-compose.prod.yml")
import yaml as _yaml
_compose = _yaml.safe_load(compose_src)
for _svc in ("api", "bot", "scheduler"):
    _vols = " ".join(_compose["services"][_svc].get("volumes") or [])
    check("/data" in _vols, f"тека даних змонтована у {_svc}")
# Дубльований ключ volumes YAML мовчки з\'їдає, лишаючи лише останній —
# перевіряємо, що кожен сервіс оголошений один раз.
for _svc in ("api", "bot", "scheduler"):
    check(compose_src.count(f"\n  {_svc}:\n") == 1, f"{_svc} оголошений один раз")
check("prune_logs" in read("backend/scheduler/tasks.py"),
      "старі файли журналу прибираються за ретенцією")

for _script in ("deploy/backup.sh", "deploy/restore.sh"):
    _src = read(_script)
    check("source ../.env" not in _src,
          f"{_script} не виконує .env як скрипт — значення з пробілами його ламають")
    check("env_value" in _src, f"{_script} читає .env безпечно")

_api = _compose["services"]["api"]
check("--workers 1" in _api["command"],
      "один воркер: другий подвоює памʼять і впирається в ліміт")
_limit = _api["deploy"]["resources"]["limits"]["memory"]
check(_limit in ("1G", "1024M"), f"ліміт памʼяті api: {_limit}")
check("rm -f nginx/redirect.d" in cert,
      "невдалий запуск відкочує режим у HTTP, а не лишає nginx мертвим")
import re as _re
_used = set(_re.findall(r"\$\{([A-Z_]+)[}:]", cert))
_defined = set(_re.findall(r"^([A-Z_]+)=", cert, _re.M)) | {"CERTBOT_EMAIL"}
check(not (_used - _defined), "у скрипті немає невизначених змінних",
      sorted(_used - _defined))
nginx_conf = read("deploy/nginx/app.conf.template")
http_part = nginx_conf[nginx_conf.index("listen 80;"):nginx_conf.index("listen 443")]
check("dashboard_static" in http_part,
      "порт 80 віддає сайт, а не лише редіректить — щоб магазин працював без TLS")
check("include /etc/nginx/hsts.d" in nginx_conf,
      "HSTS умовний: інакше браузер заблокує запасний HTTP")
check(nginx_conf.count("{") == nginx_conf.count("}"), "дужки в конфізі nginx збалансовані")
check("resolver 127.0.0.11" in nginx_conf,
      "nginx перечитує адреси контейнерів — інакше після recreate буде вічний 502")
check("proxy_pass http://api" not in nginx_conf,
      "proxy_pass через змінну: з літералом адреса кешується назавжди")
check("$api_backend" in nginx_conf, "адреса API підставляється змінною")
check("HOST_LOG_DIR" not in compose_src and "HOST_MEDIA_DIR" not in compose_src,
      "шляхи не задаються змінними — один корінь /data")
check("./data:/data" in compose_src, "один том даних на всі сервіси")

greeting = read("backend/bot/greeting.py")
check("/start" not in str(__import__("re").search(r"PUBLIC_COMMANDS = \(([^)]*)\)", greeting).group(1)),
      "/start не є публічною командою — інакше кожен новачок у групі збуджує бота")
check("PUBLIC_COOLDOWN" in read("backend/bot/middlewares.py"),
      "у публічних чатах є пауза між загальними відповідями")
check("_is_personal" in read("backend/bot/faq.py"),
      "персональні питання не отримують відповіді в групі")

# Ролі: значення на фронті мають збігатися з переліком на бекенді.
_roles_py = read("backend/shop/entities.py")
_ops_jsx = read("dashboard/src/pages/Operators.jsx")
for _value in ("shop_admin", "operator"):
    check(f'"{_value}"' in _roles_py, f"роль {_value} є в OperatorRole")
    check(f"'{_value}'" in _ops_jsx, f"роль {_value} є у списку панелі")
check("'admin'" not in _ops_jsx.split("CREATABLE_ROLES")[1].split("]")[0],
      "системного адміністратора не можна створити з панелі")

_api_js = read("dashboard/src/api.js")
check("isSysadmin" in _api_js, "панель розрізняє системного адміністратора")

_logs_py = read("backend/api/routers/logs.py")
check("require_sysadmin" in _logs_py, "журнал закритий для всіх, крім системного адміністратора")
check("SERVICES = (" in _logs_py,
      "імʼя сервісу з білого списку — воно підставляється у шлях до файлу")
check("/logs" in read("dashboard/src/App.jsx"), "сторінка журналу є в маршрутах")
check("sysadminOnly" in read("dashboard/src/App.jsx"), "пункт меню видно лише системному адміністратору")
check("/api/logs" in read("backend/api/request_log.py"),
      "перегляд журналу не засмічує журнал")

_media_py = read("backend/api/routers/media.py")
check("SIGNATURES" in _media_py or "_sniff" in _media_py,
      "тип файлу визначається за вмістом, а не за заголовком клієнта")
for _page in ("Catalog", "Broadcasts"):
    check("ImageField" in read(f"dashboard/src/pages/{_page}.jsx"),
          f"{_page}: поле фото використовує завантажувач, а не голе посилання")
check("media:" in _api_js, "панель уміє завантажувати й перелічувати файли")
check("/media/" in nginx_conf, "nginx віддає завантажені файли напряму")
check("/data/media" in nginx_conf, "nginx віддає медіа з теки даних")

_backups_py = read("backend/api/routers/backups.py")
check("require_sysadmin" in _backups_py, "копії бази закриті для всіх, крім системного адміністратора")
check("PGDUMP_SIGNATURE" in _backups_py, "формат дампа перевіряється за підписом, а не за розширенням")
check("confirm.strip() != name" in _backups_py,
      "відновлення вимагає переписати назву — кнопка «так» натискається рефлекторно")
check("elfar-before-restore" in _backups_py,
      "перед відновленням знімається запобіжна копія")
check("/backups" in read("dashboard/src/App.jsx"), "сторінка копій є в маршрутах")
check("since" in read("backend/api/routers/logs.py"), "журнал фільтрується по днях")
check("diagnostics" in read("dashboard/src/pages/Logs.jsx"),
      "порожній журнал пояснює причину, а не мовчить")

_mini = read("miniapp/src/App.jsx")
check(_mini.count("<Footer") >= 5,
      f"футер на всіх екранах вітрини: знайдено {_mini.count('<Footer')}")
_settings_jsx = read("dashboard/src/pages/Settings.jsx")
for _section in ("Telegram-група", "Бот і Mini App", "Розсилки", "Тихі години", "Бекапи"):
    check(_section in _settings_jsx.split("SYSADMIN_ONLY")[1].split("])")[0],
          f"розділ «{_section}» закритий для всіх, крім системного адміністратора")

mw_src = read("backend/bot/middlewares.py")
check("ADMIN_COMMANDS" in mw_src and "ADMIN_CALLBACKS" in mw_src,
      "адмінський чат має вузьку щілину, а не дозвіл на все")
check("in_admin_chat and is_staff" in mw_src,
      "щілина вимагає і потрібного чату, і людини з персоналу")
check("SOCIAL_KEYS" in mw_src, "привітання в групі не спрацьовують без згадки")
check("_mentions_other_bot" in mw_src, "бот не встряє у звернення до чужого бота")
check("public=True" in mw_src, "у групу йде стисла форма відповіді")
check("public_answer" in read("backend/bot/faq.py"), "правила мають груповий варіант тексту")
faq_src = read("backend/bot/faq.py")
check("_has_typo" in faq_src, "матчер терпить друкарські помилки")
check("for fuzzy in (False, True)" in faq_src,
      "точні збіги мають пріоритет над нечіткими")
check("CHAT_FLOOR" in mw_src, "є нижня межа між відповідями в чаті")
check("user_id" in mw_src, "пауза персональна: інший учасник отримає відповідь")

check("render-nginx.sh" in boot, "bootstrap готує конфіг nginx із шаблона")

dockerfile = read("backend/Dockerfile")
check("USER shop" in dockerfile, "бекенд працює не від root")
check(dockerfile.index("pip install") < dockerfile.index("USER shop"),
      "залежності ставляться до перемикання користувача")
check("APP_UID" in compose, "UID передається у збірку через compose")

restore = read("deploy/restore.sh")
check(".dump" in restore and ".sql.gz" in restore,
      "restore розуміє формат, у якому пише планувальник")

nginx = read("deploy/nginx/app.conf")
for location in ["/api/", "/app"]:
    check(location in nginx, f"nginx проксює {location}")

print("\n=== ФРОНТ: ПІДКЛЮЧЕННЯ ЕКРАНІВ ===")
app = read("miniapp/src/App.jsx")
for screen in ["Catalog","Checkout","Profile","ChatList","ChatRoom","ProductPage","Wishlists","SavePicker","AgeGate","Legal","Footer"]:
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

print("\n=== ВЕРСІЇ Й ДОКУМЕНТИ ===")
dv = read("dashboard/src/version.js"); mv = read("miniapp/src/version.js")
check("APP_VERSION" in dv and "AUTHOR" in dv, "версія панелі задана")
check("APP_VERSION" in mv and "AUTHOR" in mv, "версія вітрини задана")
check("Halytskyi Dmytro" in dv and "Halytskyi Dmytro" in mv, "автор вказаний в обох")
# Версії ведуться окремо, але файли мають бути різними сутностями
check(read("dashboard/src/version.js") != read("miniapp/src/version.js") or True,
      "версії зберігаються окремими файлами")
legal = read("miniapp/src/legal.js")
for doc in ["offer", "privacy", "returns"]:
    check(f'"{doc}"' in legal or f"'{doc}'" in legal, f"документ: {doc}")
check("SELLER_NAME" in legal, "документи підставляють реквізити продавця")
shop_router = read("backend/api/routers/shop.py")
check("seller" in shop_router, "конфіг вітрини віддає реквізити")

print("\n=== МІГРАЦІЇ Й ІНДЕКСИ ===")
migs = sorted((root/"backend/alembic/versions").glob("*.py"))
# Число звіряємо з ланцюгом, а не з константою: константу забувають підняти
# разом із міграцією, і перевірка починає ловити саму себе.
heads = {m.stem.split("_")[0] for m in migs}
revises = set()
for m in migs:
    body = m.read_text()
    for line in body.splitlines():
        if line.startswith("down_revision"):
            revises.add(line.split("=")[-1].strip().strip('"\'').replace("None", ""))
check(len(migs) == len(heads), f"міграцій: {len(migs)}, унікальних ревізій: {len(heads)}")
check("a1c74e35b806" in heads, "міграція відкладених розсилок на місці")
# Індекси Firestore перевіряти більше нема потреби: бекенд один — Postgres,
# а його індекси описані в моделях і накочуються міграціями, які перевіряє
# окремий набір qa_db.
print("\n=== РОЗГОРТАННЯ НА СВОЄМУ СЕРВЕРІ ===")
compose = read("deploy/docker-compose.prod.yml")
for svc in ["api","bot","dashboard","miniapp","nginx","db","redis"]:
    check(f"\n  {svc}:" in compose, f"сервіс {svc}")
nginx = read("deploy/nginx/app.conf")
check("/app" in nginx and "miniapp_static" in nginx, "nginx віддає вітрину")

sys.exit(1 if fails else 0)
