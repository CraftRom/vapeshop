#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
COMPOSE="docker compose -f docker-compose.prod.yml"
DOMAIN="${1:-}"
if [[ ! "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]]; then echo "Вкажіть домен" >&2; exit 2; fi
rm -f "nginx/generated/promos/${DOMAIN}.conf"
$COMPOSE exec -T nginx nginx -t
$COMPOSE exec -T nginx nginx -s reload
echo "Nginx route для ${DOMAIN} прибрано. Сертифікат навмисно не видалено автоматично."
