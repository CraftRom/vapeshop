#!/usr/bin/env bash
# Reload only main-domain nginx configuration. No migrations or application rebuilds.
set -euo pipefail
cd "$(dirname "$0")"
COMPOSE=(docker compose --env-file ../.env -f docker-compose.prod.yml)
backup=$(mktemp)
trap 'rm -f "$backup"' EXIT
[[ -f nginx/generated/app.conf ]] || { echo 'Спочатку bootstrap/deploy.' >&2; exit 1; }
cp nginx/generated/app.conf "$backup"
./render-nginx.sh
if ! "${COMPOSE[@]}" exec -T nginx nginx -t; then
    cat "$backup" > nginx/generated/app.conf
    echo 'Конфігурацію відновлено; робочий nginx не перезапускався.' >&2
    exit 1
fi
"${COMPOSE[@]}" exec -T nginx nginx -s reload
# Nginx reload is asynchronous. Allow its new workers to replace old ones.
for attempt in 1 2 3 4 5; do
    if python3 check-public-routes.py; then exit 0; fi
    sleep 2
done
echo 'Конфігурацію перечитано, але перевірка маршрутів не пройшла. Перевірте nginx/API логи.' >&2
exit 1
