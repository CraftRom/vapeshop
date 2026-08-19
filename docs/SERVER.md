# Розгортання на власному сервері

Повний продакшн-стек: Postgres, Redis, API, бот, дашборд, nginx з TLS,
автоматичні бекапи. Все в Docker, назовні відкриті лише 80 і 443.

**Мінімум:** 2 vCPU, 2 ГБ RAM, 20 ГБ диска. Ubuntu 22.04/24.04.
Цього вистачає з великим запасом.

---

## Крок 1. Підготовка сервера

```bash
# Оновлення й Docker
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh

# Окремий користувач замість root
adduser --disabled-password --gecos "" shop
usermod -aG docker shop

# Фаєрвол: тільки SSH і веб
apt install -y ufw
ufw allow OpenSSH && ufw allow 80 && ufw allow 443
ufw --force enable
```

Домен: створіть A-запис, що вказує на IP сервера. Перевірка: `dig +short ваш-домен.com`.

## Крок 2. Код і конфігурація

```bash
su - shop
git clone <ваш-репозиторій> shop && cd shop
cp .env.example .env
nano .env
```

Заповніть обов'язкове:

```bash
DB_BACKEND=sql          # Postgres поруч у Docker — швидше й без оплати за операції

BOT_TOKEN=...
BOT_USERNAME=your_shop_bot
ADMIN_CHAT_ID=-100...
ADMIN_IDS=123456789

POSTGRES_USER=shop
POSTGRES_PASSWORD=<openssl rand -hex 24>
POSTGRES_DB=shop
# DATABASE_URL не задавайте — він збереться з POSTGRES_* автоматично

REDIS_URL=redis://redis:6379/0

JWT_SECRET=<openssl rand -hex 32>
DASHBOARD_LOGIN=admin
DASHBOARD_PASSWORD=<надійний пароль>
CORS_ORIGINS=https://ваш-домен.com

CARD_NUMBER=...
CARD_HOLDER=...
```

> **Пароль Postgres задається лише при першому створенні тому.** Якщо змінити
> його потім, база залишиться зі старим і API не підключиться. Тому оберіть
> пароль одразу. Якщо все ж треба змінити — `docker compose down -v`
> (**зітре дані**) або `ALTER USER` всередині контейнера.

Домен у nginx:

```bash
sed -i 's/example\.com/ваш-домен.com/g' deploy/nginx/app.conf
```

## Крок 3. Сертифікат

nginx з блоком `443` не стартує, поки немає сертифіката. Тому спершу
піднімаємо все без нього:

```bash
cd deploy

# Тимчасово вимикаємо HTTPS-блок
cp nginx/app.conf nginx/app.conf.bak
sed -i '/listen 443 ssl/,$d' nginx/app.conf
echo '}' >> nginx/app.conf

docker compose -f docker-compose.prod.yml up -d nginx

# Отримуємо сертифікат
docker compose -f docker-compose.prod.yml run --rm certbot \
  certonly --webroot -w /var/www/certbot \
  -d ваш-домен.com -d www.ваш-домен.com \
  --email ваш@email.com --agree-tos --no-eff-email

# Повертаємо повний конфіг
mv nginx/app.conf.bak nginx/app.conf
docker compose -f docker-compose.prod.yml restart nginx
```

Оновлення сертифіката автоматичне — сервіс `certbot` перевіряє його двічі на добу.

## Крок 4. Запуск

```bash
./deploy.sh
```

Скрипт зробить бекап, збере образи, накотить міграції, підніме сервіси й
дочекається, поки API стане здоровим. Якщо у `.env` лишились дефолтні секрети —
зупиниться з помилкою.

Демо-каталог (за бажанням):

```bash
docker compose -f docker-compose.prod.yml exec api python seed.py
```

Панель: `https://ваш-домен.com`.

## Крок 5. Бекапи за розкладом

```bash
crontab -e
```

```cron
0 3 * * * /home/shop/shop/deploy/backup.sh >> /home/shop/backup.log 2>&1
```

Зберігається 14 останніх копій у `deploy/backups/`. Скрипт падає з помилкою,
якщо дамп вийшов підозріло малим — так ви дізнаєтесь про проблему одразу,
а не в момент, коли бекап знадобиться.

Відновлення:

```bash
./restore.sh backups/db_2026-08-19_0300.sql.gz
```

**Копіюйте бекапи ще й за межі сервера** — диск може померти разом з ними:

```cron
30 3 * * * rsync -az /home/shop/shop/deploy/backups/ user@інший-хост:/backups/shop/
```

---

## Щоденна експлуатація

```bash
cd ~/shop/deploy
C="docker compose -f docker-compose.prod.yml"

$C ps                      # статус
$C logs -f bot             # логи бота
$C logs --tail=100 api     # останні логи API
$C restart bot             # перезапуск сервісу
$C exec db psql -U shop shop   # консоль бази
```

**Оновлення версії:**

```bash
git pull && ./deploy.sh
```

**Зміна `.env`:** обов'язково перестворіть контейнери — `restart` не перечитує
змінні оточення:

```bash
$C up -d --force-recreate api bot
```

---

## Polling чи вебхук

За замовчуванням бот працює через polling. Це простіше й надійніше: не залежить
від того, чи доступний ваш домен ззовні, і переживає короткі проблеми з мережею.

Вебхук має сенс при великому потоці повідомлень (менше затримка, менше запитів
до Telegram). Щоб увімкнути:

```bash
# у .env
PUBLIC_URL=https://ваш-домен.com
WEBHOOK_SECRET=<openssl rand -hex 16>
CRON_SECRET=<openssl rand -hex 32>
```

```bash
$C stop bot                                   # polling і вебхук несумісні
$C up -d --force-recreate api
curl "https://ваш-домен.com/api/telegram-setup?token=<CRON_SECRET>"
```

Апдейти прийматиме сервіс `api`. Повернутись назад: зупинити вебхук
(`curl https://api.telegram.org/bot<TOKEN>/deleteWebhook`) і запустити `bot`.

---

## Міграції бази

Схему змінює лише Alembic — `create_all` у продакшні не використовується.

```bash
# після зміни моделей у shop/models.py
$C run --rm migrate alembic revision --autogenerate -m "опис зміни"
$C run --rm migrate                    # накотити
```

Згенеровану міграцію **перечитайте перед накатом**: autogenerate добре бачить
нові таблиці й колонки, але перейменування розпізнає як «видалив + додав»,
що втратить дані.

---

## Безпека

Що вже зроблено:

- назовні відкриті лише 80/443, база й Redis — у внутрішній мережі
- TLS з HSTS, автоматичне оновлення сертифіката
- rate limit: 5 спроб входу за хвилину з IP, 30 запитів/с на API
- JWT з обмеженим часом життя
- ротація логів, ліміти пам'яті на контейнери

Що варто додати:

- **Fail2ban** для SSH
- **Вхід по ключу**, `PasswordAuthentication no` у `/etc/ssh/sshd_config`
- **Моніторинг** — [Uptime Kuma](https://github.com/louislam/uptime-kuma) на
  `/api/health` попередить про падіння раніше за клієнтів
- **Кілька адмінів** з ролями замість одного логіна в `.env`

---

## Діагностика

| Симптом | Що перевірити |
|---|---|
| Панель не відкривається | `$C ps` — чи живий nginx; `$C logs nginx` |
| 502 від nginx | API впав: `$C logs api`. Найчастіше — пароль бази |
| Не пускає в панель | `$C logs api \| grep "очікує логін"` — покаже, який логін підвантажився |
| Бот не відповідає | `$C logs bot`. Перевірте, чи не лишився активний вебхук |
| Бот забуває крок замовлення | `REDIS_URL` не заданий або Redis не піднявся |
| `too many connections` | Зменште `--workers` у команді api |
| Диск закінчився | `docker system prune -a`, перевірте `deploy/backups/` |

Стан бази:

```bash
$C exec db psql -U shop shop -c "
  SELECT status, count(*), sum(total) FROM orders GROUP BY status;"
```
