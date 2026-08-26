#!/usr/bin/env bash
# Отримання першого сертифіката.
#
#   ./certbot-init.sh elfar.pp.ua www.elfar.pp.ua
#
# Окремий скрипт, а не команда з документації, з однієї причини: сервіс
# certbot у compose має власний entrypoint із циклом продовження. При
# `docker compose run --rm certbot certonly ...` аргументи йдуть цьому
# циклу як позиційні параметри sh -c, тобто просто ігноруються — контейнер
# мовчки лягає спати на 12 годин. Виглядає як зависання, і зрозуміти
# причину з виводу неможливо.
#
# Тому тут entrypoint явно перевизначається на сам certbot.
set -euo pipefail

cd "$(dirname "$0")"
COMPOSE="docker compose -f docker-compose.prod.yml"

[[ $# -ge 1 ]] || { echo "Вкажіть домени: ./certbot-init.sh elfar.pp.ua www.elfar.pp.ua" >&2; exit 1; }

EMAIL="${CERTBOT_EMAIL:-}"
if [[ -z "$EMAIL" ]]; then
    read -rp "Email для сповіщень Let's Encrypt: " EMAIL
fi

DOMAIN_ARGS=()
for d in "$@"; do
    # Захист від скопійованого з чату посилання виду [www.site](https://www.site)
    if [[ "$d" =~ [][:space:]()] || "$d" == *"://"* ]]; then
        echo "Домен виглядає зіпсованим: $d" >&2
        echo "Схоже, скопійовано разом із розміткою посилання. Вкажіть просто www.site.com" >&2
        exit 1
    fi
    DOMAIN_ARGS+=(-d "$d")
done

# Глухий кут, який інакше не розірвати: nginx не стартує, якщо файлу
# сертифіката немає (ssl_certificate вказує в порожнечу), а сертифікат не
# отримати, бо перевірка Let's Encrypt стукає саме в nginx на 80 порт.
# Виглядає це найгірше з можливого: сайт просто не відповідає, і в логах
# «cannot load certificate», хоч ви ще жодного разу його не замовляли.
#
# Розрив — тимчасовий самопідписаний сертифікат. Він нікого не обманює й
# живе рівно до моменту, поки Let's Encrypt не видасть справжній.
DOMAIN="$1"
LIVE="/etc/letsencrypt/live/${DOMAIN}"

echo "==> Перевіряю наявність сертифіката"
if $COMPOSE run --rm --entrypoint sh certbot -c "test -f ${LIVE}/fullchain.pem" 2>/dev/null; then
    echo "    Сертифікат уже є"
else
    echo "    Немає — створюю тимчасовий самопідписаний, щоб nginx піднявся"
    $COMPOSE run --rm --entrypoint sh certbot -c "
        mkdir -p ${LIVE} &&
        openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
            -keyout ${LIVE}/privkey.pem \
            -out ${LIVE}/fullchain.pem \
            -subj '/CN=${DOMAIN}'
    " || {
        echo "Не вдалося створити тимчасовий сертифікат." >&2
        echo "Перевірте, що образ certbot має openssl: $COMPOSE run --rm --entrypoint sh certbot -c 'which openssl'" >&2
        exit 1
    }
fi

echo "==> Перевіряю, що nginx віддає /.well-known на порту 80"
$COMPOSE up -d nginx
sleep 2
PROBE="${1}"
if ! curl -fsS --max-time 10 "http://${PROBE}/.well-known/acme-challenge/" -o /dev/null 2>&1; then
    # 404 тут нормальний — файлу ще немає. Погано, якщо зʼєднання зовсім немає.
    if ! curl -sS --max-time 10 -o /dev/null -w '%{http_code}' "http://${PROBE}/" | grep -qE '^[2345]'; then
        echo "Порт 80 на ${PROBE} не відповідає. Перевірте DNS і ufw, перш ніж просити сертифікат." >&2
        exit 1
    fi
fi

echo "==> Замовляю сертифікат"
# --force-renewal: інакше certbot побачить свіжий самопідписаний файл
# і вирішить, що поновлювати ще рано.
$COMPOSE run --rm --entrypoint certbot certbot \
    certonly --webroot -w /var/www/certbot \
    "${DOMAIN_ARGS[@]}" \
    --email "$EMAIL" --agree-tos --no-eff-email \
    --force-renewal

echo "==> Перезапускаю nginx із сертифікатом"
$COMPOSE restart nginx
echo "Готово. Перевірка:  curl -sI https://${PROBE} | head -1"
