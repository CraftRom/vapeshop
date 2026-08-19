#!/usr/bin/env bash
# Бекап бази. Тримає останні 14 копій.
# У crontab:  0 3 * * * /path/to/deploy/backup.sh >> /var/log/shop-backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")"
source ../.env

COMPOSE="docker compose -f docker-compose.prod.yml"
STAMP=$(date +%F_%H%M)
mkdir -p backups

$COMPOSE exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "backups/db_${STAMP}.sql.gz"

SIZE=$(du -h "backups/db_${STAMP}.sql.gz" | cut -f1)
echo "$(date '+%F %T')  Бекап створено: db_${STAMP}.sql.gz ($SIZE)"

# Порожній дамп означає, що щось пішло не так — краще дізнатись одразу
if [[ $(stat -c%s "backups/db_${STAMP}.sql.gz") -lt 1000 ]]; then
    echo "УВАГА: бекап підозріло малий, перевірте базу" >&2
    exit 1
fi

ls -1t backups/db_*.sql.gz | tail -n +15 | xargs -r rm --
