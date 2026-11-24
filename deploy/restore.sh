#!/usr/bin/env bash
# Відновлення з бекапу.
#   ./restore.sh backups/elfar-2026-08-19.dump
#   ./restore.sh backups/db_2026-08-19_0300.sql.gz   (старий формат)
set -euo pipefail

cd "$(dirname "$0")"
# Читаємо .env безпечно, а не через source.
#
# `source` виконує файл як скрипт, і значення з пробілами його ламають:
# CARD_NUMBER=0000 0000 0000 0000 перетворюється на спробу запустити
# команду «0000». Помилка виглядає загадково («0000: command not found»)
# і не зупиняє скрипт — він просто йде далі без потрібних змінних.
env_value() {
    sed -n "s/^$1=//p" ../.env | head -1 | sed 's/^["'"'"']//; s/["'"'"']$//'
}

POSTGRES_USER=$(env_value POSTGRES_USER)
POSTGRES_PASSWORD=$(env_value POSTGRES_PASSWORD)
POSTGRES_DB=$(env_value POSTGRES_DB)
export POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB
COMPOSE="docker compose --env-file ../.env -f docker-compose.prod.yml"

[[ $# -eq 1 ]] || { echo "Вкажіть файл бекапу: ./restore.sh backups/elfar-....dump" >&2; exit 1; }
[[ -f $1 ]] || { echo "Файл $1 не знайдено" >&2; exit 1; }

# Формат визначаємо за розширенням. Планувальник і backup.sh пишуть .dump,
# але на серверах, що працюють давно, лежать ще старі .sql.gz — мовчки
# відмовитись їх читати означало б втратити саме ті бекапи, які найстаріші
# і найпотрібніші.
case "$1" in
    *.dump)   MODE=custom ;;
    *.sql.gz) MODE=plain ;;
    *) echo "Невідомий формат: очікується .dump або .sql.gz" >&2; exit 1 ;;
esac

read -rp "Це перезапише поточну базу. Продовжити? (yes/no) " ANSWER
[[ $ANSWER == "yes" ]] || { echo "Скасовано"; exit 0; }

# The browser no longer restores (backups.py refuses it); this script owns the
# safety copy, so a wrong file can always be rolled back.
SAFETY="backups/elfar-before-restore-$(date +%Y%m%d-%H%M%S).dump"
mkdir -p backups
echo "==> Запобіжна копія поточної бази: $SAFETY"
( umask 077; $COMPOSE exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$SAFETY" )
[[ $(stat -c%s "$SAFETY") -ge 1000 ]] || { echo "Запобіжна копія підозріло мала — відновлення скасовано" >&2; exit 1; }

echo "==> Зупиняю бота, API, планувальник і maintenance, щоб ніхто не писав у базу"
$COMPOSE stop bot api scheduler maintenance

if [[ $MODE == custom ]]; then
    # Схема public замінюється повністю в одній транзакції. --clean лишав
    # таблиці новіших ревізій, яких немає в старішій копії, і наступний
    # upgrade падав. SQL спершу повністю розгортається з архіву: COMMIT
    # можливий лише після успішного pg_restore, а будь-яка помилка
    # відкочує все, і поточна база лишається як була.
    $COMPOSE exec -T db sh -c 'umask 077; pg_restore --no-owner --no-acl -f /tmp/elfar-restore.sql' < "$1"
    $COMPOSE exec -T db sh -c '{ echo "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"; cat /tmp/elfar-restore.sql; } | psql -v ON_ERROR_STOP=1 --single-transaction -q -U "$1" -d "$2"; code=$?; rm -f /tmp/elfar-restore.sql; exit $code' sh "$POSTGRES_USER" "$POSTGRES_DB"
else
    gunzip -c "$1" | $COMPOSE exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
fi

# Older copies may still carry session rows; a restored copy must not revive
# logins revoked after it was taken.
$COMPOSE exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
    "DO \$\$ BEGIN IF to_regclass('public.dashboard_sessions') IS NOT NULL THEN TRUNCATE dashboard_sessions; END IF; END \$\$;"

echo "==> Накочую міграції: бекап може бути старішим за поточну схему"
$COMPOSE run --rm migrate

echo "==> Запускаю назад"
$COMPOSE start bot api scheduler maintenance
echo "Готово."
