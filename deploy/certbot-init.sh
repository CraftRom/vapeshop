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
    # Перевіряємо не «чи немає сміття», а «чи це взагалі схоже на домен».
    # Перший підхід ловить лише те, про що згадав автор: минулого разу він
    # пропустив прапорець -v, і той поїхав у certbot як значення для -d,
    # де впав із невиразним «expected one argument».
    if [[ ! "$d" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$ ]]; then
        echo "Це не схоже на домен: ${d}" >&2
        echo "" >&2
        if [[ "$d" == -* ]]; then
            echo "Схоже на прапорець. Скрипт приймає лише домени:" >&2
        elif [[ "$d" == *"://"* || "$d" == *"["* ]]; then
            echo "Схоже на посилання з розміткою. Потрібне саме імʼя домену:" >&2
        fi
        echo "    ./certbot-init.sh elfar.pp.ua www.elfar.pp.ua" >&2
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

# Домен у конфізі nginx має збігатися з тим, на який просимо сертифікат.
# Інакше виходить найгірший різновид помилки: сертифікат успішно видається
# за шляхом live/<домен>, а nginx уперто шукає live/example.com і падає
# в нескінченний рестарт, ніяк не натякаючи, що справа в заглушці.
echo "==> Домен у конфігурації nginx"
if grep -q 'example\.com' nginx/app.conf; then
    sed -i "s|example\.com|${DOMAIN}|g" nginx/app.conf
    echo "    example.com → ${DOMAIN}"
else
    configured=$(grep -m1 -oP 'server_name \K[^ ;]+' nginx/app.conf || true)
    if [[ -n "$configured" && "$configured" != "$DOMAIN" ]]; then
        echo "У nginx/app.conf налаштований домен ${configured}, а сертифікат просимо на ${DOMAIN}." >&2
        echo "Або виправте конфіг, або запустіть скрипт із ${configured}." >&2
        exit 1
    fi
    echo "    ${DOMAIN} — уже на місці"
fi

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

echo "==> Піднімаю nginx"
# --force-recreate, а не просто up: контейнер міг зациклитись у рестарті
# зі старим конфігом, і звичайний up вважав би, що він уже «запущений».
$COMPOSE up -d --force-recreate nginx

for attempt in 1 2 3 4 5 6 7 8 9 10; do
    state=$($COMPOSE ps --format '{{.State}}' nginx 2>/dev/null | head -1)
    [[ "$state" == "running" ]] && break
    sleep 2
done

if [[ "$state" != "running" ]]; then
    echo "nginx не піднявся. Останні рядки логу:" >&2
    $COMPOSE logs --tail 15 nginx >&2
    exit 1
fi
echo "    nginx працює"

# Спершу перевіряємо локально: так відокремлюємо «nginx не віддає» від
# «ззовні не достукатись». Друге буває через фаєрвол провайдера або через
# те, що A-запис веде на іншу адресу, і плутати ці випадки дорого.
echo "==> Перевіряю віддачу /.well-known"
if ! curl -fsS --max-time 5 -H "Host: ${DOMAIN}" \
        "http://127.0.0.1/.well-known/acme-challenge/probe" -o /dev/null 2>&1; then
    code=$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' \
           -H "Host: ${DOMAIN}" "http://127.0.0.1/" 2>/dev/null || echo 000)
    if [[ "$code" == "000" ]]; then
        echo "nginx не відповідає навіть локально — далі йти немає сенсу." >&2
        exit 1
    fi
fi
echo "    Локально віддає"

echo "==> Перевіряю доступ ззовні"
if ! curl -sS --max-time 10 -o /dev/null -w '%{http_code}' "http://${DOMAIN}/" 2>/dev/null | grep -qE '^[2345]'; then
    echo "Порт 80 на ${DOMAIN} не відповідає ззовні, хоча локально nginx працює." >&2
    echo "" >&2
    echo "Що перевірити:" >&2
    echo "  • чи A-запис веде на IPv4 цього сервера:" >&2
    echo "      curl -4 -s ifconfig.me     і порівняти з dig +short ${DOMAIN}" >&2
    echo "  • фаєрвол сервера:  sudo ufw status" >&2
    echo "  • мережевий фаєрвол OVH у панелі — він працює до сервера" >&2
    echo "    і про ufw нічого не знає" >&2
    exit 1
fi
echo "    Ззовні доступний"

echo "==> Замовляю сертифікат"
# --force-renewal: інакше certbot побачить свіжий самопідписаний файл
# і вирішить, що поновлювати ще рано.
$COMPOSE run --rm --entrypoint certbot certbot \
    certonly --webroot -w /var/www/certbot \
    "${DOMAIN_ARGS[@]}" \
    --email "$EMAIL" --agree-tos --no-eff-email \
    --force-renewal

echo "==> Вмикаю HTTPS-режим"
# Доки сертифіката не було, сайт віддавався по HTTP. Тепер можна і
# перенаправляти, і вмикати HSTS. Порядок саме такий: спершу файли,
# потім перезапуск, інакше nginx підхопить лише половину.
mkdir -p nginx/redirect.d nginx/hsts.d
echo 'return 301 https://$host$request_uri;' > nginx/redirect.d/force-https.conf
echo 'add_header Strict-Transport-Security "max-age=31536000" always;' > nginx/hsts.d/hsts.conf

echo "==> Перезапускаю nginx із сертифікатом"
$COMPOSE restart nginx
echo "Готово. Перевірка:  curl -sI https://${PROBE} | head -1"
