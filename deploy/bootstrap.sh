#!/usr/bin/env bash
# Первинне розгортання на чистій Ubuntu 22.04/24.04.
#
# Запускати від root на свіжому сервері:
#   bash deploy/bootstrap.sh
#
# Скрипт ідемпотентний: повторний запуск нічого не ламає й не перезаписує
# вже заповнений .env. Це навмисно — перший запуск рідко проходить з першого
# разу, і скрипт, який при повторі стирає конфіг, гірший за його відсутність.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_USER="${SERVICE_USER:-shop}"
UNIT_NAME="elfar"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m    %s\033[0m\n' "$*"; }
die()  { printf '\033[31mПомилка: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "потрібні права root: sudo bash deploy/bootstrap.sh"


say "Перевірка системи"
. /etc/os-release 2>/dev/null || die "не вдалося визначити дистрибутив"
[[ "${ID:-}" == "ubuntu" ]] || warn "очікувалась Ubuntu, знайдено ${PRETTY_NAME:-невідомо} — продовжую"

mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
disk_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
(( mem_mb >= 1800 )) || warn "мало памʼяті: ${mem_mb} МБ, рекомендовано 2 ГБ"
(( disk_gb >= 15 ))  || warn "мало диска: ${disk_gb} ГБ, рекомендовано 20 ГБ"


say "Пакети та Docker"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl ufw >/dev/null

if command -v docker >/dev/null 2>&1; then
    echo "    Docker уже встановлено: $(docker --version)"
else
    curl -fsSL https://get.docker.com | sh >/dev/null
    echo "    Docker встановлено: $(docker --version)"
fi

# Docker має підніматися сам після ребуту — без цього автозапуск стека
# не спрацює, скільки б restart-політик не стояло в compose.
systemctl enable --now docker >/dev/null 2>&1 || true


say "Користувач ${SERVICE_USER}"
if id "$SERVICE_USER" >/dev/null 2>&1; then
    echo "    Користувач уже існує"
else
    adduser --disabled-password --gecos "" "$SERVICE_USER" >/dev/null
    echo "    Створено"
fi
usermod -aG docker "$SERVICE_USER"
chown -R "$SERVICE_USER:$SERVICE_USER" "$REPO_DIR"


as_user() {
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$SERVICE_USER" -- "$@" 2>/dev/null
    else
        su -s /bin/sh "$SERVICE_USER" -c "$(printf '%q ' "$@")" >/dev/null 2>&1
    fi
}

say "Доступність каталогу для ${SERVICE_USER}"
# Права на сам репозиторій ще нічого не гарантують: щоб зайти в нього,
# користувачу потрібен біт «x» на кожному каталозі шляху. Домівка іншого
# користувача в Ubuntu має режим 750, тож ~/elfar для shop недосяжний,
# хоч би файли й належали йому.
#
# Ловимо це тут, а не на старті юніта: systemd повідомляє про таке кодом
# «status=200/CHDIR», за яким причину не видно взагалі.
blocker=""
probe="$REPO_DIR"
while [[ "$probe" != "/" ]]; do
    # runuser є в util-linux і стоїть скрізь, але на урізаних образах його
    # може не бути — тоді відкочуємось на su.
    if ! as_user test -x "$probe"; then
        blocker="$probe"
    fi
    probe="$(dirname "$probe")"
done

if [[ -n "$blocker" ]]; then
    mode=$(stat -c '%a' "$blocker")
    owner=$(stat -c '%U' "$blocker")
    cat >&2 <<EOF

Помилка: користувач ${SERVICE_USER} не може зайти в ${REPO_DIR}.

    Заважає: ${blocker} (режим ${mode}, власник ${owner})

Найкоротший шлях — перенести проєкт туди, куди доступ є всім:

    systemctl stop ${UNIT_NAME} 2>/dev/null || true
    mv ${REPO_DIR} /opt/elfar
    chown -R ${SERVICE_USER}:${SERVICE_USER} /opt/elfar
    cd /opt/elfar && sudo bash deploy/bootstrap.sh

Не робіть замість цього chmod 755 на ${blocker}: це відкриє домашній
каталог на читання всім користувачам системи, теперішнім і майбутнім.
EOF
    exit 1
fi
echo "    Шлях прохідний"


say "Фаєрвол"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp  >/dev/null
ufw allow 443/tcp >/dev/null
# Postgres і Redis назовні не відкриваємо: вони живуть у внутрішній мережі
# Docker, і порти назовні їм не потрібні.
ufw --force enable >/dev/null
echo "    Відкриті: SSH, 80, 443"


say "Конфігурація"
if [[ -f "$REPO_DIR/.env" ]]; then
    echo "    .env уже є — не чіпаю"
else
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    # Секрети генеруємо одразу: залишений «change-me» — найпоширеніша
    # причина відкритої назовні панелі.
    jwt=$(openssl rand -hex 32)
    pgpass=$(openssl rand -hex 16)
    dashpass=$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-16)
    cron=$(openssl rand -hex 16)
    hook=$(openssl rand -hex 16)

    sed -i \
        -e "s|^JWT_SECRET=.*|JWT_SECRET=${jwt}|" \
        -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${pgpass}|" \
        -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://shop:${pgpass}@db:5432/shop|" \
        -e "s|^DASHBOARD_PASSWORD=.*|DASHBOARD_PASSWORD=${dashpass}|" \
        -e "s|^CRON_SECRET=.*|CRON_SECRET=${cron}|" \
        -e "s|^WEBHOOK_SECRET=.*|WEBHOOK_SECRET=${hook}|" \
        "$REPO_DIR/.env"
    chmod 600 "$REPO_DIR/.env"
    chown "$SERVICE_USER:$SERVICE_USER" "$REPO_DIR/.env"

    printf '\n    Згенеровано секрети. Пароль панелі: \033[1m%s\033[0m\n' "$dashpass"
    echo "    Запишіть його — у файлі він теж є, але .env закритий від сторонніх."
fi

# UID/GID користувача shop прописуємо завжди, а не лише при створенні .env:
# за ними збирається образ бекенду, і процеси в контейнерах працюють від того
# самого числового користувача. Без цього дампи в ./backups належали б чужому
# UID, і власник сервера не зміг би їх ні прочитати, ні видалити без sudo.
#
# Це поза гілкою «створюємо .env» навмисно: файл міг приїхати з репозиторію
# або з іншого сервера, де UID інший.
uid=$(id -u "$SERVICE_USER")
gid=$(id -g "$SERVICE_USER")
if grep -q '^APP_UID=' "$REPO_DIR/.env"; then
    sed -i -e "s|^APP_UID=.*|APP_UID=${uid}|" -e "s|^APP_GID=.*|APP_GID=${gid}|" "$REPO_DIR/.env"
else
    printf '\nAPP_UID=%s\nAPP_GID=%s\n' "$uid" "$gid" >> "$REPO_DIR/.env"
fi
echo "    Процеси в контейнерах працюватимуть від UID ${uid}:${gid} (${SERVICE_USER})"


# Порожнє значення — не єдиний спосіб лишити змінну незаповненою: у
# .env.example стоять приклади-заглушки (1234567890:AAxx…, -1001234567890),
# і перевірка «чи не порожньо» їх би пропустила, а магазин піднявся б
# з неробочим токеном.
missing=()
env_value() { grep -E "^${1}=" "$REPO_DIR/.env" | head -1 | cut -d= -f2- || true; }

value=$(env_value BOT_TOKEN)
[[ -z "$value" || "$value" == 1234567890:* ]] && missing+=(BOT_TOKEN)

value=$(env_value ADMIN_CHAT_ID)
[[ -z "$value" || "$value" == "-1001234567890" || "$value" == "0" ]] && missing+=(ADMIN_CHAT_ID)

value=$(env_value PUBLIC_URL)
[[ "$value" != https://* ]] && missing+=(PUBLIC_URL)


say "Права на скрипти"
# Zip не завжди доносить прапорець виконання: залежить від того, чим
# розпаковували й на якій системі. Виглядає це як «Permission denied» на
# ./deploy.sh, хоч файл на місці й читається.
chmod +x "$REPO_DIR"/deploy/*.sh
echo "    $(ls "$REPO_DIR"/deploy/*.sh | wc -l) скриптів позначено виконуваними"


say "Звʼязок compose із .env"
# docker compose читає два різні набори змінних, і плутанина між ними —
# класична пастка:
#   • env_file: ../.env — те, що бачить процес ВСЕРЕДИНІ контейнера
#   • ${VAR} у самому YAML — підставляється з файлу .env поруч
#     із compose-файлом, тобто з deploy/.env
#
# Без цього симлінка ${POSTGRES_USER} розкривається в порожній рядок,
# Postgres відмовляється ініціалізуватись, а compose каже лише
# «container deploy-db-1 is unhealthy», не називаючи причини.
ln -sfn ../.env "$REPO_DIR/deploy/.env"
echo "    deploy/.env → ../.env"


say "Домен у конфігурації nginx"
# У app.conf стоять заглушки example.com — і в server_name, і в шляхах до
# сертифіката. Якщо їх не замінити, nginx не знайде сертифікат і не підніме
# HTTPS, а помилка виглядатиме як «cannot load certificate», хоч сертифікат
# насправді успішно отриманий, просто під іншим іменем.
public_url=$(grep -E '^PUBLIC_URL=' "$REPO_DIR/.env" | head -1 | cut -d= -f2-)
domain=${public_url#https://}
domain=${domain#http://}
domain=${domain%%/*}

if [[ -z "$domain" ]]; then
    warn "PUBLIC_URL ще не заповнено — домен у nginx лишається заглушкою"
elif grep -q 'example\.com' "$REPO_DIR/deploy/nginx/app.conf"; then
    sed -i "s|example\.com|${domain}|g" "$REPO_DIR/deploy/nginx/app.conf"
    # www.<домен> у server_name лишаємо: сертифікат зазвичай беруть на обидва,
    # а зайве імʼя в server_name нічого не ламає.
    echo "    example.com → ${domain}"
else
    echo "    Домен уже підставлено"
fi


say "Каталог даних"
# Одна тека замість трьох окремих: журнал, копії бази й завантажені
# зображення. Підкаталоги створює сам застосунок при першому звертанні —
# тут лише коренева тека з правильним власником, бо процеси в контейнерах
# працюють не від root.
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 750 "$REPO_DIR/deploy/data"
for sub in logs backups media; do
    install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 750 "$REPO_DIR/deploy/data/$sub"
done
echo "    $REPO_DIR/deploy/data (logs, backups, media)"


say "Служба автозапуску"
install -m 644 "$REPO_DIR/deploy/${UNIT_NAME}.service" "/etc/systemd/system/${UNIT_NAME}.service"
sed -i \
    -e "s|__REPO_DIR__|${REPO_DIR}|g" \
    -e "s|__USER__|${SERVICE_USER}|g" \
    "/etc/systemd/system/${UNIT_NAME}.service"
systemctl daemon-reload
systemctl enable "${UNIT_NAME}.service" >/dev/null
echo "    ${UNIT_NAME}.service увімкнено — стек підніметься сам після ребуту"


if (( ${#missing[@]} )); then
    say "Лишилось заповнити вручну"
    for key in "${missing[@]}"; do echo "    • $key"; done
    cat <<EOF

    nano $REPO_DIR/.env

    Далі:
      systemctl start ${UNIT_NAME}      # підняти стек
      systemctl status ${UNIT_NAME}     # перевірити
EOF
    exit 0
fi


say "Запуск"
systemctl start "${UNIT_NAME}.service"

cat <<EOF

Готово.

  Панель:      $(grep -E '^PUBLIC_URL=' "$REPO_DIR/.env" | cut -d= -f2-)
  Стан:        systemctl status ${UNIT_NAME}
  Логи:        journalctl -u ${UNIT_NAME} -f
  Оновлення:   sudo -u ${SERVICE_USER} ${REPO_DIR}/deploy/deploy.sh

Перевірка ребуту: reboot, потім systemctl status ${UNIT_NAME}
EOF
