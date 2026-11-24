#!/usr/bin/env bash
# Готує конфігурацію nginx до запуску.
#
# Робить дві речі, без яких nginx не підніметься:
#   1. підставляє домен із PUBLIC_URL у шаблон;
#   2. переконується, що файл сертифіката існує — хоч тимчасовий.
#
# Викликається з deploy.sh і bootstrap.sh перед стартом. Ідемпотентний:
# запускати можна скільки завгодно разів.
set -euo pipefail

cd "$(dirname "$0")"
COMPOSE="docker compose --env-file ../.env -f docker-compose.prod.yml"

DOMAIN=$(python3 domain_config.py primary)
mapfile -t CERT_DOMAINS < <(python3 domain_config.py domains)
CERT_SAN=$(printf 'DNS:%s,' "${CERT_DOMAINS[@]}")
CERT_SAN=${CERT_SAN%,}
python3 domain_config.py render
echo "    nginx/generated/app.conf для ${DOMAIN}"

# Сертифікат. Nginx не стартує, якщо файл відсутній, — разом із блоком на
# 80 порту, через який Let's Encrypt і підтверджує домен. Тимчасовий
# самопідписаний розриває це коло; certbot-init.sh замінить його справжнім.
LIVE="/etc/letsencrypt/live/${DOMAIN}"
if $COMPOSE run --rm --entrypoint sh certbot -c "test -f ${LIVE}/fullchain.pem" 2>/dev/null; then
    echo "    сертифікат на місці"
else
    echo "    сертифіката немає — кладу тимчасовий, щоб nginx піднявся"
    $COMPOSE run --rm --entrypoint sh certbot -c "
        mkdir -p ${LIVE} &&
        openssl req -x509 -nodes -newkey rsa:2048 -days 90 \
            -keyout ${LIVE}/privkey.pem -out ${LIVE}/fullchain.pem \
            -subj '/CN=${DOMAIN}' -addext 'subjectAltName=${CERT_SAN}' 2>/dev/null
    " >/dev/null
    echo "    отримайте справжній:  ./certbot-init.sh ${DOMAIN}"
fi
