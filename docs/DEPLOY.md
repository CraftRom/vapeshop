# Розгортання

Магазин розгортається на власному сервері з Ubuntu. Усе своє: Postgres
у контейнері поруч, власний планувальник розсилок, власні бекапи. Зовнішніх
залежностей, крім Telegram і Let's Encrypt, немає.

> **Найшвидший шлях — `sudo bash deploy/bootstrap.sh` на чистому сервері.**
> Він робить усе з частини 2 нижче за один прохід. Читайте далі, щоб
> розуміти, що саме він зробив і де шукати, якщо щось пішло не так.

Повний довідник із поясненнями рішень — [SERVER.md](SERVER.md).

# Покроково

## 1. Сервер

Мінімум: 2 vCPU, 2 ГБ RAM, 20 ГБ диска, Ubuntu 22.04/24.04.

```bash
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh

adduser --disabled-password --gecos "" shop
usermod -aG docker shop

apt install -y ufw
ufw allow OpenSSH && ufw allow 80 && ufw allow 443
ufw --force enable
```

Домен: A-запис на IP сервера. Перевірка: `dig +short ваш-домен.com`.

## 2. Код і конфігурація

```bash
su - shop
git clone <ваш-репозиторій> shop && cd shop
cp .env.example .env
nano .env
```

```bash
DB_BACKEND=sql
SERVERLESS=false

BOT_TOKEN=1234567890:AA...
BOT_USERNAME=your_shop_bot
ADMIN_CHAT_ID=-1001234567890
ADMIN_IDS=123456789

POSTGRES_USER=shop
POSTGRES_PASSWORD=<openssl rand -hex 24>
POSTGRES_DB=shop
# DATABASE_URL не задавайте — збереться з POSTGRES_* автоматично
# PUBLIC_URL обов'язковий: з нього будується адреса вітрини /app
# BOT_USERNAME обов'язковий: кнопка переходу з групи в особистий чат

REDIS_URL=redis://redis:6379/0

JWT_SECRET=<openssl rand -hex 32>
DASHBOARD_LOGIN=admin
DASHBOARD_PASSWORD=<надійний пароль>
CORS_ORIGINS=https://ваш-домен.com

SHOP_NAME=Назва магазину
CARD_NUMBER=0000 0000 0000 0000
CARD_HOLDER=Прізвище Імя
```

> **Пароль Postgres задається лише при створенні тому.** Якщо змінити його
> потім, база залишиться зі старим і API не підключиться. Оберіть одразу.

Домен у конфігу nginx:

```bash
sed -i 's/example\.com/ваш-домен.com/g' deploy/nginx/app.conf
```

## 3. Сертифікат

nginx із блоком `443` не стартує без сертифіката, тому спершу піднімаємо
тільки HTTP:

```bash
cd deploy

cp nginx/app.conf nginx/app.conf.bak
sed -i '/listen 443 ssl/,$d' nginx/app.conf
echo '}' >> nginx/app.conf

docker compose -f docker-compose.prod.yml up -d nginx

docker compose -f docker-compose.prod.yml run --rm certbot \
  certonly --webroot -w /var/www/certbot \
  -d ваш-домен.com -d www.ваш-домен.com \
  --email ваш@email.com --agree-tos --no-eff-email

mv nginx/app.conf.bak nginx/app.conf
docker compose -f docker-compose.prod.yml restart nginx
```

Далі сертифікат оновлюється сам — сервіс `certbot` перевіряє двічі на добу.

## 4. Запуск

```bash
./deploy.sh
```

Скрипт зробить бекап, збере образи, накотить міграції, підніме сервіси
й дочекається, поки API стане здоровим. Якщо в `.env` лишились дефолтні
секрети — зупиниться з помилкою.

Каталог:

```bash
docker compose -f docker-compose.prod.yml exec api python seed.py
```

## 5. Перевірка

```bash
curl https://ваш-домен.com/api/health          # бекенд
curl -I https://ваш-домен.com/                 # панель, очікуємо 200
curl -I https://ваш-домен.com/app              # вітрина, очікуємо 301 → /app/
```

`nginx` роздає три речі з одного домену: `/` — панель, `/app` — вітрину
Mini App, `/api/` — бекенд. Якщо `/app` віддає 404, перевірте, що контейнер
`miniapp` піднявся:

```bash
docker compose -f docker-compose.prod.yml ps miniapp
```

Бот тут працює через **polling** — окремих дій не потрібно, він уже
підключений. Напишіть `/start`.

Кнопка «Відкрити магазин» з'явиться в меню лише за заданого `PUBLIC_URL`,
причому обов'язково `https://` — Telegram відхиляє Mini App на http.

Якщо бот мовчить:

```bash
docker compose -f docker-compose.prod.yml logs bot
```

Найчастіша причина — лишився активний вебхук від попередніх спроб:

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/deleteWebhook"
docker compose -f docker-compose.prod.yml restart bot
```

## 6. Бекапи

```bash
crontab -e
```

```cron
0 3 * * * /home/shop/shop/deploy/backup.sh >> /home/shop/backup.log 2>&1
30 3 * * * rsync -az /home/shop/shop/deploy/backups/ user@інший-хост:/backups/shop/
```

Копії за межами сервера обов'язкові — диск може померти разом із ними.

Відновлення: `./restore.sh backups/db_2026-08-19_0300.sql.gz`

---

# Як усе пов'язано

```
              Telegram
                 │
          polling / вебхук
                 │
                 ▼
        ┌─────────────────┐        ┌──────────────┐
        │   Хендлери      │───────▶│  Repository  │
        │   бота          │        │  (інтерфейс) │
        └─────────────────┘        └──────┬───────┘
                                          │
        ┌─────────────────┐               │
        │  API + панель   │──────────────▶├──▶ Postgres (свій контейнер)
        └─────────────────┘               │
                 ▲                        │
        ┌─────────────────┐               │
        │  Планувальник   │──────────────▶┘
        │  розсилки,бекап │
        └─────────────────┘

   усе в одному docker compose, автозапуск — systemd (elfar.service)
```

Бот і панель працюють з однією базою через спільний інтерфейс `Repository`.
Тому замовлення з бота одразу видно в панелі, а зміна статусу в панелі
надсилає клієнту повідомлення в Telegram.

---

# Типові помилки

| Симптом | Причина | Виправлення |
|---|---|---|
| «Бекенд не налаштований» | Бракує змінних | Дивіться список у самому повідомленні |
| Бекенд відповідає 500 | База недоступна | `curl /api/debug/database`, далі `docker compose logs api db` |
| Не пускає з правильним паролем | Змінна не перечиталась | `docker compose up -d --force-recreate api` |
| Бот мовчить | Лишився активний вебхук | `deleteWebhook`, перезапуск бота |
| Бот забуває крок оформлення | Немає `REDIS_URL` | Додати Redis |
| Замовлення не падають у групу | Невірний `ADMIN_CHAT_ID` | Має бути від'ємне число |
| Кнопки статусів не працюють | Ваш ID не в `ADMIN_IDS` | Додати через кому |
| Розсилка висить у «Надсилається» | Планувальник не працює | `docker compose logs scheduler` |
| Відкладена не стартувала | Тихі години або ще не настав тік | Планувальник тікає раз на годину |
| Після ребуту нічого не піднялось | Юніт вимкнено | `systemctl enable --now elfar`, `systemctl is-enabled docker` |

## Діагностика

```bash
curl https://ваш-домен/api/health           # конфігурація й версія збірки
curl https://ваш-домен/api/debug/database   # чи жива база просто зараз
curl https://ваш-домен/api/debug/routing    # маршрутизація
```

```bash
systemctl status elfar
docker compose -f docker-compose.prod.yml logs -f api bot scheduler
```

При невдалому вході API пише в лог, який логін очікує й яка довжина пароля
підвантажилась — сам пароль у логи не потрапляє.
