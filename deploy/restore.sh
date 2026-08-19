#!/usr/bin/env bash
# Відновлення з бекапу.  Використання: ./restore.sh backups/db_2026-08-19_0300.sql.gz
set -euo pipefail

cd "$(dirname "$0")"
source ../.env
COMPOSE="docker compose -f docker-compose.prod.yml"

[[ $# -eq 1 ]] || { echo "Вкажіть файл бекапу: ./restore.sh backups/db_....sql.gz" >&2; exit 1; }
[[ -f $1 ]] || { echo "Файл $1 не знайдено" >&2; exit 1; }

read -rp "Це перезапише поточну базу. Продовжити? (yes/no) " ANSWER
[[ $ANSWER == "yes" ]] || { echo "Скасовано"; exit 0; }

echo "==> Зупиняю бота й API, щоб ніхто не писав у базу"
$COMPOSE stop bot api

gunzip -c "$1" | $COMPOSE exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

echo "==> Запускаю назад"
$COMPOSE start api bot
echo "Відновлено з $1"
