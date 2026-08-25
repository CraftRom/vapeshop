#!/usr/bin/env bash
# Відновлення з бекапу.
#   ./restore.sh backups/elfar-2026-08-19.dump
#   ./restore.sh backups/db_2026-08-19_0300.sql.gz   (старий формат)
set -euo pipefail

cd "$(dirname "$0")"
source ../.env
COMPOSE="docker compose -f docker-compose.prod.yml"

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

echo "==> Зупиняю бота, API і планувальник, щоб ніхто не писав у базу"
$COMPOSE stop bot api scheduler

if [[ $MODE == custom ]]; then
    # --clean --if-exists прибирає наявні обʼєкти перед відновленням:
    # без цього pg_restore сипле помилками «вже існує» і лишає базу
    # напівстарою-напівновою.
    $COMPOSE exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --clean --if-exists --no-owner < "$1"
else
    gunzip -c "$1" | $COMPOSE exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
fi

echo "==> Накочую міграції: бекап може бути старішим за поточну схему"
$COMPOSE run --rm migrate

echo "==> Запускаю назад"
$COMPOSE start bot api scheduler
echo "Готово."
