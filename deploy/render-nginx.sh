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
COMPOSE="docker compose -f docker-compose.prod.yml"

env_value() {
    sed -n "s/^$1=//p" ../.env | head -1 | sed 's/^["'"'"']//; s/["'"'"']$//'
}

PUBLIC_URL=$(env_value PUBLIC_URL)
DOMAIN=${PUBLIC_URL#https://}
DOMAIN=${DOMAIN#http://}
DOMAIN=${DOMAIN%%/*}

if [[ -z "$DOMAIN" ]]; then
    echo "У .env не заповнено PUBLIC_URL — nginx не знатиме, який домен обслуговувати." >&2
    exit 1
fi

mkdir -p nginx/generated
sed "s|__DOMAIN__|${DOMAIN}|g" nginx/app.conf.template > nginx/generated/app.conf
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
            -subj '/CN=${DOMAIN}' 2>/dev/null
    " >/dev/null
    echo "    отримайте справжній:  ./certbot-init.sh ${DOMAIN}"
fi
