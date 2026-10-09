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
sys.path.insert(0, str(env_path.resolve().parent / 'backend'))
from shop.production_security import validate_production_security
try:
    validate_production_security(vals.get('PUBLIC_URL', ''), vals['JWT_SECRET'], vals['DASHBOARD_PASSWORD'])
except RuntimeError as exc:
    raise SystemExit(str(exc)) from None
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
BACKUP_CREATED=0
if ./backup.sh; then
    BACKUP_CREATED=1
else
    echo "    Бекап не створено; для першого запуску це очікувано"
fi

echo "==> Конфігурація nginx"
./render-nginx.sh

echo "==> Збірка образів (поточні сервіси ще працюють)"
"${COMPOSE[@]}" build

# Smoke нового backend image ДО міграцій і ДО заміни контейнерів.
echo "==> Перевірка нового backend image"
"${COMPOSE[@]}" run --rm --no-deps -T api python -m shop.preflight

CATALOG_BREAKING_UPGRADE=0

rollback_core_runtime() {
    if [[ "$CATALOG_BREAKING_UPGRADE" == 1 ]]; then
        echo "Каталог уже перейшов на нову схему. Повернення старих образів потребує відновлення резервної копії БД; автоматичний runtime rollback пропущено." >&2
        return
    fi
    echo "==> Основний реліз не пройшов health gate. Rollback CORE runtime..." >&2
    if [[ -f "$ROLLBACK_DIR/images.tsv" ]]; then
        while IFS=$'\t' read -r svc sha ref; do
            # Promo має власну фазу і не бере участі в core rollback.
            [[ "$svc" == "promo-controller" ]] && continue
            [[ -n "$sha" && -n "$ref" ]] || continue
            docker tag "$sha" "$ref" >/dev/null 2>&1 || true
        done < "$ROLLBACK_DIR/images.tsv"
        "${COMPOSE[@]}" up -d --no-deps --force-recreate api bot scheduler dashboard miniapp || true
        # nginx завжди пересоздаємо ПІСЛЯ повернення API, щоб він резолвив актуальну IP.
        "${COMPOSE[@]}" up -d --no-deps --force-recreate nginx || true
    fi
    if [[ -f "$ROLLBACK_DIR/app.conf" ]]; then
        cp "$ROLLBACK_DIR/app.conf" nginx/generated/app.conf
        "${COMPOSE[@]}" exec -T nginx nginx -t >/dev/null 2>&1 && "${COMPOSE[@]}" exec -T nginx nginx -s reload >/dev/null 2>&1 || true
    fi
    echo "Core rollback виконано наскільки можливо. Promo-система не перезапускалась. Бекап БД: deploy/data/backups; metadata: $ROLLBACK_DIR" >&2
}

echo "==> ФАЗА 1/6: базові сервіси (PostgreSQL + Redis)"
"${COMPOSE[@]}" up -d db redis

wait_service_healthy() {
    local svc="$1"; local attempts="${2:-45}"
    local cid status
    for _ in $(seq 1 "$attempts"); do
        cid="$("${COMPOSE[@]}" ps -q "$svc" 2>/dev/null || true)"
        if [[ -n "$cid" ]]; then
            status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
            [[ "$status" == "healthy" || "$status" == "running" ]] && return 0
        fi
        sleep 2
    done
    echo "$svc не став healthy" >&2
    "${COMPOSE[@]}" logs --tail=100 "$svc" >&2 || true
    return 1
}

wait_service_healthy db 45 || exit 1
wait_service_healthy redis 45 || exit 1

echo "==> ФАЗА 2/6: міграції БД"
# Міграції йдуть тільки після healthy DB. Перехід категорій змінює старий API.
CATALOG_BREAKING_UPGRADE="$("${COMPOSE[@]}" run --rm --no-deps -T api python -m shop.catalog_upgrade)"
if [[ "$CATALOG_BREAKING_UPGRADE" == 1 ]]; then
    if [[ "$BACKUP_CREATED" != 1 ]]; then
        echo "Перехід каталогу зупинено: спочатку потрібен успішний бекап поточної БД." >&2
        exit 1
    fi
    echo "==> Перехід каталогу: зупиняємо старі API, бот і scheduler до міграції"
    "${COMPOSE[@]}" stop api bot scheduler
fi
"${COMPOSE[@]}" run --rm migrate

echo "==> ФАЗА 3/6: API"
# API запускаємо окремо. Якщо він не піднявся — деплой ЗУПИНЯЄТЬСЯ ДО nginx/promo.
"${COMPOSE[@]}" up -d --no-deps api

api_ok=0
for i in $(seq 1 60); do
    cid="$("${COMPOSE[@]}" ps -q api 2>/dev/null || true)"
    if [[ -n "$cid" ]] && docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null | grep -q true; then
        if "${COMPOSE[@]}" exec -T api python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3); raise SystemExit(0 if r.status==200 else 1)" >/dev/null 2>&1; then
            api_ok=1
            break
        fi
    fi
    sleep 2
done

if [[ "$api_ok" != 1 ]]; then
    echo "API не пройшов health-check. Основні web/promo сервіси НЕ оновлювались." >&2
    "${COMPOSE[@]}" logs --tail=150 api >&2 || true
    rollback_core_runtime
    exit 1
fi

echo "    API health: OK"

echo "==> ФАЗА 4/6: основні застосунки"
# Ці сервіси запускаємо лише після здорового API.
"${COMPOSE[@]}" up -d --no-deps dashboard miniapp bot scheduler certbot

# Bot/scheduler не мають HTTP health endpoint, тому тут перевіряємо, що вони не
# завершилися одразу після старту. Dashboard/miniapp мають просто бути running.
for svc in dashboard miniapp bot scheduler; do
    cid="$("${COMPOSE[@]}" ps -q "$svc" 2>/dev/null || true)"
    if [[ -z "$cid" ]] || ! docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null | grep -q true; then
        echo "$svc не запущений після оновлення" >&2
        "${COMPOSE[@]}" logs --tail=100 "$svc" >&2 || true
        rollback_core_runtime
        exit 1
    fi
done

echo "==> ФАЗА 5/6: nginx основного сайту"
# ВАЖЛИВО: nginx запускається/пересоздається ПІСЛЯ API. Це гарантує, що
# proxy_pass api:8000 резолвиться на актуальний контейнер, а не на стару IP.
"${COMPOSE[@]}" up -d --no-deps --force-recreate nginx

nginx_core_ok=0
for i in $(seq 1 30); do
    if "${COMPOSE[@]}" exec -T nginx wget -q -T 5 -O /dev/null http://127.0.0.1:8080/__deploy_api_health 2>/dev/null; then
        nginx_core_ok=1
        break
    fi
    sleep 2
done
if [[ "$nginx_core_ok" != 1 ]]; then
    echo "Внутрішній nginx→API маршрут не пройшов health-check після recreate" >&2
    "${COMPOSE[@]}" exec -T nginx wget -S -T 5 -O /dev/null http://127.0.0.1:8080/__deploy_api_health >&2 || true
    "${COMPOSE[@]}" logs --tail=120 nginx api >&2 || true
    rollback_core_runtime
    exit 1
fi

# Перевіряємо саме nginx-маршрут головного сайту, окремо від будь-якого promo Host.
# PUBLIC_URL використовується тільки для Host основної системи.
MAIN_HOST="$(python3 - "$ENV_FILE" <<'PY2'
import sys
from pathlib import Path
from urllib.parse import urlsplit
vals={}
for raw in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    line=raw.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1); vals[k.strip()]=v.strip().strip('"\'')
u=vals.get('PUBLIC_URL','') or vals.get('DASHBOARD_PUBLIC_URL','')
host = urlsplit(u).hostname or ''
print('elfar.pp.ua' if host == 'www.elfar.pp.ua' else host)
PY2
)"

if [[ -n "$MAIN_HOST" ]]; then
    # Локальний TLS без зовнішнього DNS/HTTP-редиректу. Host обирає основний
    # vhost. Перевірка довіри сертифіката вимкнена ТІЛЬКИ для loopback probe:
    # render-nginx може створити тимчасовий self-signed cert при bootstrap.
    core_route_ok=0
    for i in $(seq 1 20); do
        if "${COMPOSE[@]}" exec -T nginx wget -q -T 5 --no-check-certificate --header="Host: $MAIN_HOST" -O /dev/null https://127.0.0.1/api/health 2>/dev/null; then
            core_route_ok=1; break
        fi
        sleep 2
    done
    if [[ "$core_route_ok" != 1 ]]; then
        echo "Основний nginx route ($MAIN_HOST) не віддає /api/health" >&2
        "${COMPOSE[@]}" exec -T nginx wget -S -T 5 --no-check-certificate --header="Host: $MAIN_HOST" -O /dev/null https://127.0.0.1/api/health >&2 || true
        "${COMPOSE[@]}" logs --tail=120 nginx api >&2 || true
        rollback_core_runtime
        exit 1
    fi
    echo "    Main route health ($MAIN_HOST): OK"
else
    echo "    PUBLIC_URL не заданий — Host-перевірку головного домену пропущено; internal nginx→API: OK"
fi

echo "==> ФАЗА 6/6: промо-система"
# Promo-controller стартує ОСТАННІМ і не є умовою здоров'я основної системи.
# Він має власний health-check і окремі server_name для кожного промо-домену.
"${COMPOSE[@]}" up -d --no-deps promo-controller
promo_ok=0
for i in $(seq 1 30); do
    cid="$("${COMPOSE[@]}" ps -q promo-controller 2>/dev/null || true)"
    if [[ -n "$cid" ]]; then
        status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
        if [[ "$status" == "healthy" ]]; then promo_ok=1; break; fi
    fi
    sleep 2
done

if [[ "$promo_ok" != 1 ]]; then
    echo "УВАГА: основна система здорова, але Promo Controller не пройшов health-check." >&2
    echo "Промо ізольовано від основного сайту; full deploy не відкочується через promo-помилку." >&2
    "${COMPOSE[@]}" logs --tail=120 promo-controller >&2 || true
else
    echo "    Promo Controller health: OK"
fi

# Після promo-controller робимо фінальну перевірку API, щоб promo-фаза не могла
# непомітно зачепити основу.
if ! "${COMPOSE[@]}" exec -T api python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3); raise SystemExit(0 if r.status==200 else 1)" >/dev/null 2>&1; then
    echo "КРИТИЧНО: API перестав бути healthy після promo-фази." >&2
    "${COMPOSE[@]}" logs --tail=120 api promo-controller nginx >&2 || true
    rollback_core_runtime
    exit 1
fi

echo "==> Фінальний API health: OK"

echo "==> API здоровий; rollback images можна прибрати при наступному успішному релізі"
# Prune лише ПІСЛЯ health gate; rollback-теги не видаляються prune -f.
docker image prune -f >/dev/null || true

echo "Готово. Статус:"
"${COMPOSE[@]}" ps
