from pathlib import Path

root = Path(__file__).resolve().parents[2]
config = (root / 'backend/shop/config.py').read_text()
sd = (root / 'backend/shop/services/salesdrive.py').read_text()
env = (root / '.env.example').read_text()
compose = (root / 'docker-compose.yml').read_text()
checks = {
    'ENV має SALESDRIVE_TELEGRAM_SOURCE_ID': 'SALESDRIVE_TELEGRAM_SOURCE_ID=0' in env,
    'локальна БД лишилась shop': 'POSTGRES_DB=shop' in env and '${POSTGRES_DB:-shop}' in compose,
    'конфіг має source id': 'salesdrive_telegram_source_id: int = 0' in config,
    'відправка fail-closed без source id': 'SALESDRIVE_TELEGRAM_SOURCE_ID не задано' in sd,
    'webhook звіряє formId': 'int(data.get("formId")) == expected' in sd,
    'webhook звіряє account': 'account != (shop.salesdrive_domain or "").strip().lower()' in sd,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items(): print(('✓' if ok else '✗'), name)
raise SystemExit(1 if failed else 0)
