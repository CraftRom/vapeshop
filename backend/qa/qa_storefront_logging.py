"""Статичні інваріанти журналу Mini App і канонічного домену."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
shop = (ROOT / "api/routers/shop.py").read_text()
logs = (ROOT / "api/routers/logs.py").read_text()
logging_setup = (ROOT / "shop/logging_setup.py").read_text()
client = (ROOT / "shop/client_logging.py").read_text()
config = (ROOT / "shop/config.py").read_text()
nginx = (ROOT.parent / "deploy/nginx/app.conf.template").read_text()
rate = (ROOT.parent / "deploy/nginx/ratelimit.conf").read_text()
bot_main = (ROOT / "bot/__main__.py").read_text()
links = (ROOT / "shop/links.py").read_text()
render = (ROOT.parent / "deploy/render-nginx.sh").read_text()
mini_main = (ROOT.parent / "miniapp/src/main.jsx").read_text()
mini_tg = (ROOT.parent / "miniapp/src/telegram.js").read_text()

checks = {
    "public client-log endpoint": '@router.post("/client-log"' in shop,
    "storefront own log": 'storefront.log' in client,
    "logs UI service allowed": '"storefront"' in logs,
    "budget includes storefront": 'SERVICES_COUNT = 4' in logging_setup,
    "raw initData field absent": 'x_telegram_init_data' not in shop[shop.index('class ClientLogIn'):shop.index('# ------------------------------------------------------------------ схеми')],
    "www alias normalized": 'www.elfar.pp.ua' in config and 'elfar.pp.ua' in config,
    "nginx telemetry rate": 'zone=storefront_log' in rate and 'limit_req zone=storefront_log' in nginx,
    "telemetry body capped": 'client_max_body_size 16k' in nginx,
    "telemetry schema forbids extras": 'ConfigDict(extra="forbid")' in shop,
    "api request log keeps telemetry quiet": '"/api/shop/client-log"' in (ROOT / "api/request_log.py").read_text(),
    "polling refreshes telegram menu url": 'set_chat_menu_button' in bot_main and 'canonical_public_url' in bot_main,
    "public links avoid stale named app url": 'return chat_link(start_param)' in links,
    "deploy renderer canonicalizes stale www": 'www.elfar.pp.ua' in render and 'DOMAIN="elfar.pp.ua"' in render,
    "miniapp self-heals stale www before React": 'legacyHostRedirectUrl' in mini_main and 'window.location.replace' in mini_main,
    "miniapp accepts launch data from query": 'fromSearch()' in mini_tg and 'window.location.search' in mini_tg,
}
for name, ok in checks.items():
    print(('OK' if ok else 'FAIL'), name)
if not all(checks.values()):
    raise SystemExit(1)
