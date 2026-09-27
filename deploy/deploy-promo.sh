#!/usr/bin/env bash
# Promo-only deployment. Does not rebuild/restart bot, scheduler, miniapp,
# database, redis, certbot or unrelated services.
set -euo pipefail

COMPOSE="docker compose --env-file ../.env -f docker-compose.prod.yml"
cd "$(dirname "$0")"

if [[ ! -f ../.env ]]; then
    echo "Немає ../.env — promo update скасовано." >&2
    exit 1
fi
[[ -L .env || -f .env ]] || ln -sfn ../.env .env

# Promo depends on the existing DB/API stack. Do not run migrations or touch DB
# here: this command is intentionally safe for UI/controller promo updates.
for service in db redis api nginx; do
    if ! $COMPOSE ps --status running --services | grep -qx "$service"; then
        echo "Сервіс $service зараз не запущений. Promo-only deploy не буде підіймати весь стек автоматично." >&2
        echo "Спочатку відновіть штатний стек, потім повторіть deploy-promo.sh." >&2
        exit 1
    fi
done

echo "==> Перевірка promo-коду"
python3 ../backend/qa/qa_promo_landing.py
python3 ../backend/qa/qa_promo_cloudflare.py
python3 -m py_compile ../backend/api/routers/landing_pages.py ./promo-controller/controller.py

echo "==> Збірка тільки API/dashboard/promo-controller"
$COMPOSE build api dashboard promo-controller

echo "==> Оновлення тільки promo-залежних контейнерів"
# --no-deps is deliberate: never restart postgres/redis/nginx/bot/etc here.
$COMPOSE up -d --no-deps api dashboard promo-controller

echo "==> Очікуємо API після точкового оновлення"
for i in $(seq 1 30); do
    if $COMPOSE exec -T api python -c \
        "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health', timeout=2)" 2>/dev/null; then
        echo "    API відповідає"
        break
    fi
    if [[ $i -eq 30 ]]; then
        echo "API не піднявся після promo-only update. Останні логи API:" >&2
        $COMPOSE logs --tail=80 api >&2
        exit 1
    fi
    sleep 2
done

echo "==> Promo-only update завершено"
$COMPOSE ps api dashboard promo-controller
