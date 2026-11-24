#!/usr/bin/env bash
# ELFAR і ACCORD NICHE на одному сервері й в одному Docker.
#
# Публічний nginx ELFAR (Compose project `deploy`, контейнер deploy-nginx-1)
# є єдиним edge для обох магазинів. Інсталятор ACCORD
# (/opt/accord-niche/scripts/connect_elfar_edge.py) підключає до нього
# зовнішню мережу `accord-shared-edge` і файл nginx/accord-main.conf.
# Обидва підключення тепер записані в docker-compose.prod.yml цього
# репозиторію, тож оновлення ELFAR більше не стирає їх.
#
# Використання (з каталогу deploy/):
#   bash shared-edge.sh ensure    — мережа й файл-заглушка, якщо їх ще немає
#   bash shared-edge.sh guard     — до будь-яких змін: чужі контейнери й імена
#   bash shared-edge.sh nginx-test — nginx -t з повним набором конфігурацій
#   bash shared-edge.sh verify    — після recreate: мережа на місці, ACCORD живий
#
# Скрипт нічого не змінює в ACCORD: не чіпає його Compose, томи, .env.domains
# і не перезапускає його контейнери.
set -euo pipefail
cd "$(dirname "$0")"

NETWORK="accord-shared-edge"
EDGE_CONF="nginx/accord-main.conf"
# Перший рядок файлу, який створює інсталятор ACCORD. Він перевіряє саме його
# і відмовляється перезаписувати файл без цієї позначки.
EDGE_MARKER="# Managed by ACCORD NICHE shared-edge installer"
PROJECT="deploy"
COMPOSE=(docker compose --env-file ../.env -f docker-compose.prod.yml)
# Імена, за якими nginx ELFAR шукає свої upstream (api, dashboard, miniapp) і
# інші сервіси ELFAR. Жоден чужий контейнер у спільній мережі не сміє мати
# такий DNS alias: Docker DNS віддав би nginx чужу адресу.
RESERVED_ALIASES="api dashboard miniapp nginx promo-controller db redis bot scheduler maintenance migrate certbot"

fail() { echo "SHARED EDGE: $*" >&2; exit 1; }

ensure() {
    if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
        docker network create "$NETWORK" >/dev/null
        echo "    Мережу $NETWORK створено (ACCORD ще не підключався або мережу видалили)"
    fi
    if [[ -L "$EDGE_CONF" ]]; then
        fail "$EDGE_CONF — символічне посилання; керований файл має бути звичайним"
    fi
    if [[ -d "$EDGE_CONF" ]]; then
        # Docker створює каталог на місці відсутнього bind-mount файлу.
        if rmdir "$EDGE_CONF" 2>/dev/null; then
            echo "    Прибрано порожній каталог $EDGE_CONF, який створив Docker"
        else
            fail "$EDGE_CONF — непорожній каталог; перевірте вручну"
        fi
    fi
    if [[ ! -e "$EDGE_CONF" ]]; then
        # Заглушка з позначкою інсталятора: nginx стартує без ACCORD, а
        # connect_elfar_edge.py пізніше спокійно замінить її своїм конфігом.
        printf '%s\n# ACCORD ще не підключено: файл заповнить connect_elfar_edge.py.\n' "$EDGE_MARKER" > "$EDGE_CONF"
        chmod 644 "$EDGE_CONF"
        echo "    Створено заглушку $EDGE_CONF"
    elif ! head -n1 "$EDGE_CONF" | grep -qxF "$EDGE_MARKER"; then
        fail "$EDGE_CONF існує, але не належить інсталятору ACCORD; деплой зупинено"
    fi
}

guard() {
    # 1. Compose project `deploy` належить лише цьому каталогу. Інший проєкт
    #    з тим самим ім'ям (наприклад, ACCORD без COMPOSE_PROJECT_NAME) деплой
    #    ELFAR перестворив би або прибрав би як orphan.
    local here foreign
    here="$(pwd -P)"
    foreign="$(docker ps -a --filter "label=com.docker.compose.project=$PROJECT" \
        --format '{{.Names}} {{.Label "com.docker.compose.project.working_dir"}}' \
        | awk -v here="$here" '$2 != "" && $2 != here {print $1 " (" $2 ")"}')"
    if [[ -n "$foreign" ]]; then
        fail "у Compose project '$PROJECT' є контейнери з іншого каталогу: $foreign"
    fi
    # 2. Чужі контейнери в спільній мережі не мають імен сервісів ELFAR.
    if docker network inspect "$NETWORK" >/dev/null 2>&1; then
        local ids id project aliases name clash=""
        ids="$(docker network inspect -f '{{range $id, $c := .Containers}}{{$id}} {{end}}' "$NETWORK")"
        for id in $ids; do
            project="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$id" 2>/dev/null || true)"
            [[ "$project" == "$PROJECT" ]] && continue
            name="$(docker inspect -f '{{.Name}}' "$id" | sed 's#^/##')"
            aliases="$(docker inspect -f "{{with index .NetworkSettings.Networks \"$NETWORK\"}}{{range .Aliases}}{{.}} {{end}}{{range .DNSNames}}{{.}} {{end}}{{end}}" "$id" 2>/dev/null || true)"
            for alias in $aliases; do
                for reserved in $RESERVED_ALIASES; do
                    [[ "$alias" == "$reserved" && "$clash" != *" $name→$alias"* ]] && clash+=" $name→$alias"
                done
            done
        done
        if [[ -n "$clash" ]]; then
            fail "у мережі $NETWORK чужі контейнери мають імена сервісів ELFAR:$clash. Nginx ELFAR міг би звернутися до них замість своїх. Перейменуйте сервіси ACCORD (v1.8.1+: accord-website, accord-miniapp, accord-dashboard)."
        fi
    fi
}

nginx_test() {
    # Той самий образ і ті самі mount, що й у робочого nginx, але в тимчасовому
    # контейнері без портів: битий конфіг ACCORD не покладе ELFAR.
    if ! "${COMPOSE[@]}" run --rm --no-deps --pull never -T --entrypoint nginx nginx -t >/dev/null 2>"$1"; then
        cat "$1" >&2
        fail "nginx -t з конфігами ELFAR і ACCORD не пройшов; робочий nginx не перестворено"
    fi
}

accord_hosts() {
    # Хости, які описує конфіг ACCORD (порожньо, якщо там лише заглушка).
    grep -Eo 'server_name[^;]*' "$EDGE_CONF" 2>/dev/null | sed 's/server_name//' | tr ' ' '\n' | grep -E '^[a-z0-9.-]+\.[a-z]+$' | sort -u || true
}

verify() {
    local cid attached host code bad="" hosts
    cid="$("${COMPOSE[@]}" ps -q nginx)"
    [[ -n "$cid" ]] || fail "контейнер nginx не запущений"
    attached="$(docker inspect -f "{{with index .NetworkSettings.Networks \"$NETWORK\"}}yes{{end}}" "$cid")"
    [[ "$attached" == "yes" ]] || fail "nginx не підключений до мережі $NETWORK — сайти ACCORD недоступні"
    hosts="$(accord_hosts | tr '\n' ' ')"
    for host in $hosts; do
        # Лише власний TLS-vhost: 2xx/3xx/4xx — nginx обслуговує ACCORD;
        # 5xx/000 — upstream ACCORD недоступний або vhost зламаний.
        code="$(docker exec "$cid" wget -q -S -T 5 --no-check-certificate -O /dev/null --header="Host: $host" https://127.0.0.1/ 2>&1 | awk '/^  HTTP\//{c=$2} END{print c+0}')"
        if [[ "$code" -lt 200 || "$code" -ge 500 ]]; then bad+=" $host:$code"; fi
    done
    if [[ -n "$bad" ]]; then
        # ELFAR не відкочується через ACCORD: його стек живе окремо. Але
        # оператор має побачити це одразу, а не від покупців.
        echo "УВАГА: nginx ELFAR піднято, але сайти ACCORD відповідають з помилкою:$bad" >&2
        echo "       Перевірте: cd /opt/accord-niche && bash deploy/domains.sh --docker-edge ps" >&2
        return 2
    fi
    echo "    Спільний edge: nginx у мережі $NETWORK; ACCORD: ${hosts:-не підключено}"
}

case "${1:-}" in
    ensure) ensure ;;
    guard) guard ;;
    nginx-test) nginx_test "$(mktemp)" ;;
    verify) verify ;;
    *) echo "Використання: bash shared-edge.sh ensure|guard|nginx-test|verify" >&2; exit 64 ;;
esac
