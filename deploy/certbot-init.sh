#!/usr/bin/env bash
# Отримання першого сертифіката.
#
#   ./certbot-init.sh elfar.pp.ua
#   ./certbot-init.sh elfar.pp.ua --staging     перевірка без витрати лімітів
#   ./certbot-init.sh elfar.pp.ua --buypass     інший центр сертифікації
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

SCRIPT_VERSION="2026-10-10.1"

cd "$(dirname "$0")"
echo "certbot-init ${SCRIPT_VERSION}"
COMPOSE="docker compose --env-file ../.env -f docker-compose.prod.yml"

[[ $# -ge 1 ]] || { echo "Вкажіть домени: ./certbot-init.sh elfar.pp.ua" >&2; exit 1; }

EMAIL="${CERTBOT_EMAIL:-}"
if [[ -z "$EMAIL" ]]; then
    read -rp "Email для сповіщень Let's Encrypt: " EMAIL
fi

# Прапорці розбираємо до доменів: інакше вони поїхали б у certbot як
# значення для -d, як уже було з -v.
STAGING=0
ACME_ARGS=()
DOMAINS=()
for arg in "$@"; do
    case "$arg" in
        --staging|--test)
            # Тестовий сервер Let's Encrypt. Лімітів практично не має, але
            # сертифікат браузер не прийме: він доводить, що працює весь
            # ланцюжок — DNS, порт 80, webroot, — і нічого більше.
            STAGING=1
            ACME_ARGS+=(--staging)
            ;;
        --buypass)
            # Інший центр сертифікації з тим самим протоколом ACME.
            # Власні ліміти, не пов'язані з Let's Encrypt, і сертифікати
            # на 180 днів. Браузери йому довіряють.
            ACME_ARGS+=(--server https://api.buypass.com/acme/directory)
            ;;
        -*)
            echo "Невідомий прапорець: ${arg}" >&2
            echo "Доступні: --staging (тестовий сервер), --buypass (інший ЦС)" >&2
            exit 1
            ;;
        *)
            DOMAINS+=("$arg")
            ;;
    esac
done

[[ ${#DOMAINS[@]} -ge 1 ]] || {
    echo "Вкажіть домени: ./certbot-init.sh elfar.pp.ua" >&2
    exit 1
}

# The nginx aliases and the certificate SAN must use the same domain set.
CONFIGURED_DOMAIN=$(python3 domain_config.py primary)
mapfile -t CONFIGURED_DOMAINS < <(python3 domain_config.py domains)
for requested in "${DOMAINS[@]}"; do
    found=0
    for configured in "${CONFIGURED_DOMAINS[@]}"; do
        [[ "$requested" == "$configured" ]] && found=1
    done
    [[ $found == 1 ]] || { echo "Домен не налаштований у PUBLIC_URL/MAIN_DOMAIN_ALIASES: $requested" >&2; exit 1; }
done
DOMAINS=("${CONFIGURED_DOMAINS[@]}")

DOMAIN_ARGS=()
for d in "${DOMAINS[@]}"; do
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
        echo "    ./certbot-init.sh elfar.pp.ua" >&2
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
DOMAIN="${DOMAINS[0]}"
LIVE="/etc/letsencrypt/live/${DOMAIN}"

# Домен у конфізі nginx має збігатися з тим, на який просимо сертифікат.
# Інакше виходить найгірший різновид помилки: сертифікат успішно видається
# за шляхом live/<домен>, а nginx уперто шукає live/example.com і падає
# в нескінченний рестарт, ніяк не натякаючи, що справа в заглушці.
echo "==> Готую конфігурацію nginx"
# Робочий конфіг генерується з шаблона щоразу — правити його на місці не
# можна: наступне розпакування архіву поверне заглушку, і nginx упаде з
# «cannot load certificate .../example.com/fullchain.pem».
./render-nginx.sh

configured="$CONFIGURED_DOMAIN"
if [[ "$configured" != "$DOMAIN" ]]; then
    echo "" >&2
    echo "У .env вказано домен ${configured:-невідомо}, а сертифікат просимо на ${DOMAIN}." >&2
    echo "Виправте PUBLIC_URL у .env або запустіть скрипт із ${configured}." >&2
    exit 1
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

echo "==> Застосовую конфігурацію nginx"
state=$($COMPOSE ps --format '{{.State}}' nginx 2>/dev/null | head -1)
if [[ "$state" == "running" ]]; then
    $COMPOSE exec -T nginx nginx -t
    $COMPOSE exec -T nginx nginx -s reload
else
    # Recover a missing/restarting container; a healthy one only needs reload.
    $COMPOSE up -d --force-recreate nginx
fi

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
if ! curl -sS --max-time 10 -o /dev/null -w '%{http_code}' "http://${DOMAIN}/" 2>/dev/null | grep -qE '^[23]'; then
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

# Прибираємо заглушку перед запитом.
#
# Certbot відмовляється працювати з каталогом live/<домен>, якого він не
# створював: «live directory exists». А створювали його ми — щоб nginx мав
# що завантажити й узагалі піднявся. Ознака заглушки проста: є live/, але
# немає renewal/<домен>.conf, який certbot пише для кожного справжнього
# сертифіката.
#
# Видаляти безпечно саме зараз: nginx уже стартував і тримає сертифікат
# у памʼяті, файли йому більше не потрібні до перезапуску.
MANAGED=0
if $COMPOSE run --rm --entrypoint sh certbot \
        -c "test -f /etc/letsencrypt/renewal/${DOMAIN}.conf" 2>/dev/null; then
    MANAGED=1
    echo "==> Знайдено сертифікат під керуванням certbot — це поновлення"
else
    echo "==> Прибираю тимчасову заглушку"
    $COMPOSE run --rm --entrypoint sh certbot \
        -c "rm -rf /etc/letsencrypt/live/${DOMAIN} /etc/letsencrypt/archive/${DOMAIN}" \
        >/dev/null 2>&1 || true
fi

# Expand SAN when adding www; otherwise retain an unexpired certificate.
# Never force a fresh issuance on every deploy.
FORCE=(--expand --keep-until-expiring --non-interactive)
if [[ $STAGING -eq 1 && $MANAGED -eq 1 ]]; then
    echo "Не замінюю чинний сертифікат тестовим. Для staging використайте окреме тестове середовище." >&2
    exit 1
fi

if [[ $STAGING -eq 1 ]]; then
    echo "==> Тестовий сервер: сертифікат буде недовірений браузером"
fi

echo "==> Замовляю сертифікат"
# --cert-name прибиває шлях до сертифіката намертво.
#
# Без нього certbot іменує каталог за першим доменом, але при зміні набору
# доменів вважає це новим сертифікатом і створює live/<домен>-0001. Nginx
# продовжує дивитись у live/<домен>, не знаходить оновлення й падає —
# при тому що certbot щойно написав «Successfully received certificate».
if ! $COMPOSE run --rm --entrypoint certbot certbot \
    certonly --webroot -w /var/www/certbot \
    --cert-name "$DOMAIN" \
    "${DOMAIN_ARGS[@]}" \
    --email "$EMAIL" --agree-tos --no-eff-email \
    "${ACME_ARGS[@]}" "${FORCE[@]}"; then
    # Restore bootstrap certificate files if first issuance failed after removing the placeholder.
    ./render-nginx.sh
    echo "Сертифікат не отримано. Перевірте DNS та ACME для всіх налаштованих доменів." >&2
    exit 1
fi

if [[ $STAGING -eq 0 ]]; then
    mkdir -p nginx/hsts.d
    echo 'add_header Strict-Transport-Security "max-age=31536000" always;' > nginx/hsts.d/hsts.conf
fi

echo "==> Перечитую nginx із сертифікатом"
$COMPOSE exec -T nginx nginx -t
$COMPOSE exec -T nginx nginx -s reload

for attempt in 1 2 3 4 5 6 7 8 9 10; do
    state=$($COMPOSE ps --format '{{.State}}' nginx 2>/dev/null | head -1)
    [[ "$state" == "running" ]] && break
    sleep 2
done

if [[ "$state" != "running" ]]; then
    # HSTS не повинен лишатися після невдалого перемикання сертифіката.
    # Сам HTTP при цьому все одно не віддає застосунок: лише ACME challenge
    # і редірект на HTTPS, щоб токени та дані магазину не йшли відкрито.
    rm -f nginx/hsts.d/hsts.conf
    $COMPOSE restart nginx >/dev/null 2>&1 || true
    echo "" >&2
    echo "nginx не піднявся з новим сертифікатом." >&2
    echo "Найчастіша причина: сертифікат ліг не за тим шляхом." >&2
    echo "" >&2
    echo "Перевірте, що бачить certbot і куди дивиться nginx:" >&2
    echo "    $COMPOSE run --rm --entrypoint certbot certbot certificates" >&2
    echo "    grep ssl_certificate nginx/generated/app.conf" >&2
    $COMPOSE logs --tail 10 nginx >&2
    exit 1
fi

echo ""
echo "Готово. Перевірка:"
echo "    curl -sI https://${DOMAIN} | head -1"
