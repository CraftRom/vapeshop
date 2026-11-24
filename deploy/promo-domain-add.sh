#!/usr/bin/env bash
# Одноразово підключає домен до конструктора промо-сторінок.
# DNS A/AAAA домену вже має вказувати на цей сервер.
set -euo pipefail
cd "$(dirname "$0")"
COMPOSE="docker compose -f docker-compose.prod.yml"
DOMAIN="${1:-}"
EMAIL="${2:-}"

if [[ ! "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]]; then
  echo "Використання: $0 promo.example.com [email]" >&2
  exit 2
fi

mkdir -p nginx/generated/promos
# ACME challenge вже віддає основний default server на :80, тому сертифікат
# можна отримати до створення HTTPS server block нового домену.
CERT_ARGS=(certonly --webroot -w /var/www/certbot -d "$DOMAIN" --non-interactive --agree-tos)
if [[ -n "$EMAIL" ]]; then CERT_ARGS+=(--email "$EMAIL"); else CERT_ARGS+=(--register-unsafely-without-email); fi
$COMPOSE run --rm --entrypoint certbot certbot "${CERT_ARGS[@]}"

sed "s|__PROMO_DOMAIN__|${DOMAIN}|g" nginx/promo-domain.conf.template > "nginx/generated/promos/${DOMAIN}.conf"
$COMPOSE exec -T nginx nginx -t
$COMPOSE exec -T nginx nginx -s reload

echo "Підключено: https://${DOMAIN}/"
echo "Тепер створіть/оновіть сторінку з точним доменом ${DOMAIN} у панелі та натисніть «Опублікувати»."
