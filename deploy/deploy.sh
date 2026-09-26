#!/usr/bin/env bash
# Деплой на власний сервер. Запускати з теки deploy/.
set -euo pipefail

COMPOSE="docker compose -f docker-compose.prod.yml"
cd "$(dirname "$0")"

if [[ ! -f ../.env ]]; then
    echo "Немає ../.env — скопіюйте .env.example і заповніть його." >&2
    exit 1
fi

# ${VAR} у самому compose-файлі підставляється з .env поруч із ним, а не
# з env_file. Без цього симлінка POSTGRES_USER стає порожнім рядком, і
# Postgres падає з невиразним «container is unhealthy».
[[ -L .env || -f .env ]] || ln -sfn ../.env .env

# Порожня підстановка мовчазна за замовчуванням — ловимо її явно.
for key in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
    if ! grep -qE "^${key}=.+" ../.env; then
        echo "У .env не заповнено ${key} — Postgres не стартує." >&2
        exit 1
    fi
done

# Перевіряємо, що дефолтні паролі змінено: інакше панель відкрита всім
if grep -qE '^(DASHBOARD_PASSWORD=admin|JWT_SECRET=change_this)' ../.env; then
    echo "У .env лишились дефолтні секрети. Змініть DASHBOARD_PASSWORD і JWT_SECRET." >&2
    exit 1
fi

# Старі інсталяції не мають PROMO_CONTROLLER_TOKEN. Генеруємо його
# автоматично під час звичайного deploy, щоб новий модуль не вимагав
# ручного SSH-налаштування після оновлення. Секрет ніколи не потрапляє
# у браузер — ним спілкуються тільки API та ізольований promo-controller.
promo_token=$(grep -E '^PROMO_CONTROLLER_TOKEN=' ../.env | head -1 | cut -d= -f2- || true)
if [[ -z "$promo_token" || "$promo_token" == change_this* ]]; then
    promo_token=$(openssl rand -hex 32)
    if grep -q '^PROMO_CONTROLLER_TOKEN=' ../.env; then
        sed -i "s|^PROMO_CONTROLLER_TOKEN=.*|PROMO_CONTROLLER_TOKEN=${promo_token}|" ../.env
    else
        printf '\nPROMO_CONTROLLER_TOKEN=%s\n' "$promo_token" >> ../.env
    fi
    echo "==> Згенеровано внутрішній секрет Promo Controller"
fi

echo "==> Бекап бази перед оновленням"
./backup.sh || echo "    (бази ще немає — перший запуск)"

echo "==> Конфігурація nginx"
# Обовʼязково перед стартом: шаблон у репозиторії, робочий конфіг —
# згенерований. Інакше оновлення коду повертало б заглушку домену.
./render-nginx.sh

echo "==> Збірка образів"
$COMPOSE build

echo "==> Міграції"
$COMPOSE run --rm migrate

echo "==> Перезапуск сервісів"
$COMPOSE up -d --remove-orphans

echo "==> Чекаємо, поки API стане здоровим"
for i in $(seq 1 30); do
    if $COMPOSE exec -T api python -c \
        "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')" 2>/dev/null; then
        echo "    API відповідає"
        break
    fi
    [[ $i -eq 30 ]] && { echo "API не піднявся. Логи:" >&2; $COMPOSE logs --tail=50 api >&2; exit 1; }
    sleep 2
done

echo "==> Прибирання старих образів"
docker image prune -f >/dev/null

echo "Готово. Статус:"
$COMPOSE ps
