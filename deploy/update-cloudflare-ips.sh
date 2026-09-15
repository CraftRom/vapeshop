#!/usr/bin/env bash
# Оновлює список адрес Cloudflare для nginx (nginx/cloudflare-realip.conf).
#
# Запуск: sudo bash deploy/update-cloudflare-ips.sh
#
# Файл перезаписується лише тоді, коли обидва списки завантажились і
# кожен рядок схожий на CIDR. Порожня або обірвана відповідь не має права
# стерти робочий список: без нього nginx знову бачитиме замість покупців
# адреси Cloudflare.
set -euo pipefail
cd "$(dirname "$0")"

TARGET="nginx/cloudflare-realip.conf"
COMPOSE="docker compose -f docker-compose.prod.yml"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

curl -fsS --max-time 20 https://www.cloudflare.com/ips-v4 -o "$tmp/v4"
curl -fsS --max-time 20 https://www.cloudflare.com/ips-v6 -o "$tmp/v6"

v4_ok='^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$'
v6_ok='^[0-9a-fA-F:]+/[0-9]{1,3}$'
for pair in "v4:$v4_ok" "v6:$v6_ok"; do
    name=${pair%%:*}; pattern=${pair#*:}
    sed -i '/^[[:space:]]*$/d' "$tmp/$name"
    count=$(wc -l < "$tmp/$name")
    if [[ "$count" -lt 3 ]] || grep -qvE "$pattern" "$tmp/$name"; then
        echo "Список ${name} виглядає пошкодженим — файл не змінено." >&2
        exit 1
    fi
done

# Шапку з поясненнями зберігаємо: вона пояснює, навіщо файл існує.
sed -n '1,/^# --- IPv4 ---$/p' "$TARGET" | sed '$d' > "$tmp/conf"
{
    echo "# --- IPv4 ---"
    sed 's/.*/set_real_ip_from &;/' "$tmp/v4"
    echo "# --- IPv6 ---"
    sed 's/.*/set_real_ip_from &;/' "$tmp/v6"
    echo
    echo "real_ip_header CF-Connecting-IP;"
} >> "$tmp/conf"

if cmp -s "$tmp/conf" "$TARGET"; then
    echo "Список адрес Cloudflare актуальний."
    exit 0
fi

cp "$TARGET" "$TARGET.bak"
cat "$tmp/conf" > "$TARGET"
# Перевіряємо конфіг до перезавантаження: зламаний файл не має покласти
# nginx, який зараз працює.
if $COMPOSE exec -T nginx nginx -t >/dev/null 2>&1; then
    $COMPOSE exec -T nginx nginx -s reload
    rm -f "$TARGET.bak"
    echo "Список адрес Cloudflare оновлено, nginx перезавантажено."
else
    cat "$TARGET.bak" > "$TARGET"
    rm -f "$TARGET.bak"
    echo "nginx не прийняв новий список — повернуто попередній." >&2
    exit 1
fi
