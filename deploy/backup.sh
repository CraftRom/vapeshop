#!/usr/bin/env bash
# Ручний бекап бази — той самий формат, у якому пише планувальник.
#
# Регулярні бекапи робить сервіс scheduler за розкладом із панелі. Цей скрипт
# потрібен для позапланового знімка: перед деплоєм, перед ризикованою зміною,
# перед відновленням.
set -euo pipefail

cd "$(dirname "$0")"
source ../.env

COMPOSE="docker compose -f docker-compose.prod.yml"
STAMP=$(date +%F_%H%M)
TARGET="backups/elfar-manual-${STAMP}.dump"
mkdir -p backups

# Формат custom (-Fc), а не SQL: стискається вдвічі й дозволяє відновлювати
# окремі таблиці через pg_restore. Той самий формат, що в планувальника, —
# інакше restore.sh довелося б угадувати, що йому підсунули.
#
# Пишемо через stdout на хост, а не в примонтований том: файл одразу
# належить тому, хто запустив скрипт, без возні з UID контейнера.
$COMPOSE exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$TARGET"

SIZE_BYTES=$(stat -c%s "$TARGET")
echo "$(date '+%F %T')  Бекап створено: $(basename "$TARGET") ($(du -h "$TARGET" | cut -f1))"

# Порожній дамп означає, що щось пішло не так — краще дізнатись одразу,
# ніж у момент, коли бекап знадобиться.
if [[ $SIZE_BYTES -lt 1000 ]]; then
    echo "УВАГА: бекап підозріло малий ($SIZE_BYTES Б), перевірте базу" >&2
    exit 1
fi

# Ручні знімки чистимо окремо від автоматичних: за автоматичні відповідає
# планувальник із ретенцією з панелі.
ls -1t backups/elfar-manual-*.dump 2>/dev/null | tail -n +15 | xargs -r rm --
