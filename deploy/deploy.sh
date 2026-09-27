#!/usr/bin/env bash
# Повний production deploy. Запускати з deploy/ або з будь-якої теки.
set -euo pipefail

cd "$(dirname "$0")"
ENV_FILE="../.env"
COMPOSE_FILE="docker-compose.prod.yml"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
STAMP="$(date +%Y%m%d-%H%M%S)"
ROLLBACK_DIR="./data/deploy-rollback/$STAMP"
mkdir -p "$ROLLBACK_DIR"

fail() { echo "ПОМИЛКА: $*" >&2; exit 1; }

[[ -f "$ENV_FILE" ]] || fail "Немає $ENV_FILE — створіть його з .env.example."

# Не дозволяємо другому .env тихо підміняти значення compose.
# Відтепер єдине джерело підстановок — ../.env через --env-file.
if [[ -f .env && ! -L .env ]]; then
    mv .env "$ROLLBACK_DIR/deploy.env.stale"
    echo "==> Знайдено старий deploy/.env; перенесено в $ROLLBACK_DIR/deploy.env.stale"
elif [[ -L .env ]]; then
    rm -f .env
fi

# Перевіряємо сам .env і узгодженість connection URL ДО build/restart.
python3 - "$ENV_FILE" <<'PY'
import sys
from pathlib import Path
from urllib.parse import urlsplit, unquote

env_path = Path(sys.argv[1])
vals = {}
for raw in env_path.read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    k = k.strip(); v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    vals[k] = v

required = [
    'BOT_TOKEN','JWT_SECRET','DATA_ENCRYPTION_KEY','DASHBOARD_PASSWORD',
    'POSTGRES_USER','POSTGRES_PASSWORD','POSTGRES_DB','REDIS_PASSWORD','REDIS_URL',
]
missing = [k for k in required if not vals.get(k)]
if missing:
    raise SystemExit('Не заповнені обов’язкові змінні: ' + ', '.join(missing))
if vals['JWT_SECRET'] in {'change-me','change_this','change_this_to_a_long_random_string'}:
    raise SystemExit('JWT_SECRET має дефолтне/небезпечне значення')
if vals['DASHBOARD_PASSWORD'] in {'admin','change_this_password_too'}:
    raise SystemExit('DASHBOARD_PASSWORD має дефолтне значення')

# Якщо DATABASE_URL заданий, він мусить відповідати тим самим POSTGRES_*.
dburl = vals.get('DATABASE_URL','').strip()
if dburl:
    # urlsplit не знає dialect suffix, але коректно парсить після заміни scheme.
    parsed = urlsplit(dburl.replace('postgresql+asyncpg://','postgresql://',1))
    errors = []
    if parsed.hostname != 'db': errors.append(f'host={parsed.hostname!r}, очікується db')
    if unquote(parsed.username or '') != vals['POSTGRES_USER']: errors.append('POSTGRES_USER не збігається з DATABASE_URL')
    if unquote(parsed.password or '') != vals['POSTGRES_PASSWORD']: errors.append('POSTGRES_PASSWORD не збігається з DATABASE_URL')
    if (parsed.path or '').lstrip('/') != vals['POSTGRES_DB']: errors.append('POSTGRES_DB не збігається з DATABASE_URL')
    if errors: raise SystemExit('Некоректний DATABASE_URL: ' + '; '.join(errors))

rurl = vals['REDIS_URL']
rp = urlsplit(rurl)
errors = []
if rp.hostname != 'redis': errors.append(f'host={rp.hostname!r}, очікується redis')
if unquote(rp.password or '') != vals['REDIS_PASSWORD']: errors.append('REDIS_PASSWORD не збігається з REDIS_URL')
if errors: raise SystemExit('Некоректний REDIS_URL: ' + '; '.join(errors))
print('env preflight: OK')
PY

# Compose має повністю розгорнути конфіг із ЦЬОГО env без warning/порожніх required values.
echo "==> Preflight docker compose"
"${COMPOSE[@]}" config --quiet

# Старі image SHA/refs потрібні для автоматичного rollback, якщо новий API не підніметься.
for svc in api bot scheduler dashboard miniapp promo-controller; do
    cid="$("${COMPOSE[@]}" ps -q "$svc" 2>/dev/null || true)"
    if [[ -n "$cid" ]]; then
        old_sha="$(docker inspect -f '{{.Image}}' "$cid" 2>/dev/null || true)"
        old_ref="$(docker inspect -f '{{.Config.Image}}' "$cid" 2>/dev/null || true)"
        if [[ -n "$old_sha" && -n "$old_ref" ]]; then
            printf '%s\t%s\t%s\n' "$svc" "$old_sha" "$old_ref" >> "$ROLLBACK_DIR/images.tsv"
            docker tag "$old_sha" "elfar-rollback:${STAMP}-${svc}" >/dev/null 2>&1 || true
        fi
    fi
done
[[ -f nginx/generated/app.conf ]] && cp nginx/generated/app.conf "$ROLLBACK_DIR/app.conf" || true

# Старі інсталяції: генеруємо внутрішній promo secret лише у канонічному ../.env.
promo_token=$(grep -E '^PROMO_CONTROLLER_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)
if [[ -z "$promo_token" || "$promo_token" == change_this* ]]; then
    promo_token=$(openssl rand -hex 32)
    if grep -q '^PROMO_CONTROLLER_TOKEN=' "$ENV_FILE"; then
        sed -i "s|^PROMO_CONTROLLER_TOKEN=.*|PROMO_CONTROLLER_TOKEN=${promo_token}|" "$ENV_FILE"
    else
        printf '\nPROMO_CONTROLLER_TOKEN=%s\n' "$promo_token" >> "$ENV_FILE"
    fi
    echo "==> Згенеровано внутрішній секрет Promo Controller"
fi

echo "==> Бекап бази перед оновленням"
./backup.sh || echo "    (бази ще немає — перший запуск)"

echo "==> Конфігурація nginx"
./render-nginx.sh

echo "==> Збірка образів (поточні сервіси ще працюють)"
"${COMPOSE[@]}" build

# Smoke нового backend image ДО міграцій і ДО заміни контейнерів.
echo "==> Перевірка нового backend image"
"${COMPOSE[@]}" run --rm --no-deps api python - <<'PY'
from cryptography.fernet import Fernet
from shop.config import settings
missing = settings.missing_required()
if missing:
    raise SystemExit('В image бракує обов’язкових налаштувань: ' + ', '.join(missing))
if not settings.data_encryption_key:
    raise SystemExit('DATA_ENCRYPTION_KEY порожній')
Fernet(settings.data_encryption_key.encode())
import api.main
print('backend pre-start smoke: OK')
PY

echo "==> Міграції"
# Якщо міграція падає, старі production-контейнери ще не замінено.
"${COMPOSE[@]}" run --rm migrate

rollback_runtime() {
    echo "==> Новий API не став здоровим. Автоматичний rollback runtime..." >&2
    if [[ -f "$ROLLBACK_DIR/images.tsv" ]]; then
        while IFS=$'\t' read -r svc sha ref; do
            [[ -n "$sha" && -n "$ref" ]] || continue
            docker tag "$sha" "$ref" >/dev/null 2>&1 || true
        done < "$ROLLBACK_DIR/images.tsv"
        "${COMPOSE[@]}" up -d --no-deps --force-recreate api bot scheduler dashboard miniapp promo-controller || true
    fi
    if [[ -f "$ROLLBACK_DIR/app.conf" ]]; then
        cp "$ROLLBACK_DIR/app.conf" nginx/generated/app.conf
        "${COMPOSE[@]}" exec -T nginx nginx -t >/dev/null 2>&1 && "${COMPOSE[@]}" exec -T nginx nginx -s reload >/dev/null 2>&1 || true
    fi
    echo "Rollback виконано наскільки можливо. Бекап БД: deploy/data/backups; metadata: $ROLLBACK_DIR" >&2
}

echo "==> Оновлення production сервісів"
"${COMPOSE[@]}" up -d --remove-orphans

echo "==> Чекаємо здоровий API"
api_ok=0
for i in $(seq 1 45); do
    if "${COMPOSE[@]}" exec -T api python -c "import urllib.request; r=urllib.request.urlopen('http://localhost:8000/api/health', timeout=3); raise SystemExit(0 if r.status==200 else 1)" >/dev/null 2>&1; then
        api_ok=1; break
    fi
    sleep 2
done

if [[ "$api_ok" != 1 ]]; then
    echo "API не піднявся. Останні логи:" >&2
    "${COMPOSE[@]}" logs --tail=100 api >&2 || true
    rollback_runtime
    exit 1
fi

# Друга перевірка з точки зору nginx: ловить broken Docker DNS/upstream.
echo "==> Перевірка nginx → API"
nginx_ok=0
for i in $(seq 1 15); do
    if "${COMPOSE[@]}" exec -T nginx wget -q -O /dev/null http://api:8000/api/health 2>/dev/null; then
        nginx_ok=1; break
    fi
    sleep 2
done
if [[ "$nginx_ok" != 1 ]]; then
    echo "nginx не бачить API; логи nginx/API:" >&2
    "${COMPOSE[@]}" logs --tail=80 nginx api >&2 || true
    rollback_runtime
    exit 1
fi

echo "==> API здоровий; rollback images можна прибрати при наступному успішному релізі"
# Prune лише ПІСЛЯ health gate; rollback-теги не видаляються prune -f.
docker image prune -f >/dev/null || true

echo "Готово. Статус:"
"${COMPOSE[@]}" ps
