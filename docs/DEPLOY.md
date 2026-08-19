# Розгортання: повний посібник

Два сценарії. Обирайте один — вони не поєднуються.

| | **Vercel** | **Власний сервер** |
|---|---|---|
| База | Firestore | Postgres |
| Бот | вебхук | polling |
| Розсилки | порціями, планувальник | фоном, без пауз |
| Складність | нижча | вища |
| Ціна на старті | 0 | від $5/міс за VPS |
| Коли обирати | перевірити ідею | бойовий магазин |

Обидва сценарії — **один домен для панелі й API**. Це принципово: інакше
панель не знаходить бекенд і ви бачите «API недоступний».

---

# ЧАСТИНА 1. Vercel

## 1.1. Готуємо облікові записи

Знадобляться три безкоштовні сервіси:

- **[Firebase](https://console.firebase.google.com)** — база даних
- **[Upstash](https://upstash.com)** — Redis для стану оформлення замовлення
- **[cron-job.org](https://cron-job.org)** — планувальник розсилок

## 1.2. Firestore

1. [console.firebase.google.com](https://console.firebase.google.com) →
   **Create project** → назва → Google Analytics можна вимкнути
2. **Build → Firestore Database → Create database**
3. Режим **Production mode**, регіон **`europe-central2`** (Варшава)
4. **Project settings** (шестерня) → **Service accounts** →
   **Generate new private key** → завантажиться JSON

Цей JSON — ключ від бази. Поводьтесь як із паролем: не комітьте в репозиторій.

Накотіть індекси й правила з кореня проєкту:

```bash
npm install -g firebase-tools
firebase login
firebase use --add          # оберіть щойно створений проєкт
firebase deploy --only firestore:indexes,firestore:rules
```

Без індексів Firestore відмовлятиме в частині запитів (списки замовлень,
сегменти розсилок).

## 1.3. Redis

[Upstash](https://upstash.com) → **Create Database** → регіон ближче до Європи
→ скопіюйте **`rediss://`** URL з розділу Redis Connect.

Без Redis багатокрокове оформлення замовлення розсиплеться: кожен крок може
потрапити в інший процес, який не пам'ятає попереднього.

## 1.4. Бот у Telegram

1. [@BotFather](https://t.me/BotFather) → `/newbot` → назва → юзернейм
2. Збережіть **токен** виду `1234567890:AA...`
3. Створіть **групу** для замовлень, додайте туди свого бота
4. Додайте в групу [@getmyid_bot](https://t.me/getmyid_bot) — він покаже
   **ID групи** (від'ємне число виду `-1001234567890`), потім приберіть його
5. Напишіть [@userinfobot](https://t.me/userinfobot) — він покаже **ваш ID**

## 1.5. Проєкт на Vercel

**Це найважливіший крок — саме тут виникає помилка «API недоступний».**

New Project → імпорт репозиторію → у **Root Directory** має бути **корінь
репозиторію**, а не `dashboard` і не `backend`.

> Якщо Root Directory вказує на `dashboard`, Vercel бачить лише статику,
> кореневий `vercel.json` ігнорується, функцій API немає — і панель отримує 404.
> Це виправляється в **Settings → General → Root Directory** вже після
> створення проєкту.

`vercel.json` у корені вже налаштований: збирає панель із `dashboard/`
і піднімає `api/index.py` як serverless-функцію на тому самому домені.

## 1.6. Змінні оточення

**Settings → Environment Variables.** Додайте всі одразу — без них функція
працює, але не пускає в панель.

```
SERVERLESS=true
DB_BACKEND=firestore

FIREBASE_PROJECT=ваш-проєкт-id
GOOGLE_APPLICATION_CREDENTIALS_JSON=<увесь вміст JSON ключа одним рядком>

BOT_TOKEN=1234567890:AA...
BOT_USERNAME=your_shop_bot
ADMIN_CHAT_ID=-1001234567890
ADMIN_IDS=123456789

REDIS_URL=rediss://...upstash...

JWT_SECRET=<openssl rand -hex 32>
DASHBOARD_LOGIN=admin
DASHBOARD_PASSWORD=<надійний пароль>

WEBHOOK_SECRET=<openssl rand -hex 16>
CRON_SECRET=<openssl rand -hex 32>
PUBLIC_URL=https://ваш-домен

SHOP_NAME=Назва магазину
CARD_NUMBER=0000 0000 0000 0000
CARD_HOLDER=Прізвище Імя
```

`CORS_ORIGINS` і `VITE_API_URL` **не потрібні** — усе на одному домені.

`PUBLIC_URL` заповніть після першого деплою, коли Vercel видасть адресу
(або підключите свій домен), і задеплойте ще раз.

Генерація секретів:

```bash
openssl rand -hex 32
```

## 1.7. Перша перевірка

```bash
curl https://ваш-домен/api/health
```

Очікується:

```json
{"status":"ok","db_backend":"firestore","missing_env":[]}
```

Що означають інші відповіді:

| Відповідь | Причина | Дія |
|---|---|---|
| 404 | Функцій API немає | Root Directory → корінь (крок 1.5) |
| `"status":"misconfigured"` | Бракує змінних | Дивіться `missing_env`, додайте, передеплойте |
| 500 | Функція падає | Vercel → Logs, найчастіше ключ Firebase |

Панель на `https://ваш-домен` тепер сама покаже причину, якщо щось не так,
і не дасть натиснути «Увійти», поки бекенд не готовий.

## 1.8. Каталог

```bash
cd backend && pip install -r requirements.txt
DB_BACKEND=firestore \
  FIREBASE_PROJECT=ваш-проєкт \
  GOOGLE_APPLICATION_CREDENTIALS=/шлях/до/ключа.json \
  PYTHONPATH=$PWD python seed.py
```

Або просто додайте товари вручну через панель.

## 1.9. Підключення бота

Бот на Vercel працює **лише через вебхук** — довгих процесів там немає.
Реєстрація одноразова:

```bash
curl "https://ваш-домен/api/telegram-setup?token=<CRON_SECRET>"
```

Очікується:

```json
{"webhook_url":"https://ваш-домен/api/telegram/<WEBHOOK_SECRET>","pending_updates":0}
```

Перевірка: напишіть боту `/start` — має відповісти підтвердженням віку.

## 1.10. Планувальник розсилок

Вбудований cron Vercel на тарифі Hobby спрацьовує **раз на добу** — для
розсилок замало. Візьміть зовнішній:

[cron-job.org](https://cron-job.org) → Create cronjob:

- **URL:** `https://ваш-домен/api/cron/broadcast-tick`
- **Метод:** GET
- **Заголовок:** `Authorization: Bearer <CRON_SECRET>`
- **Інтервал:** кожні 2 хвилини

Кожен виклик відправляє до 100 повідомлень і рухає курсор. Розсилка на
1000 осіб займе близько 20 хвилин — це нормально й безпечно щодо лімітів
Telegram.

На тарифі Pro можна лишити вбудований cron, замінивши в `vercel.json`
розклад на `*/2 * * * *`.

## 1.11. Фінальна перевірка

```bash
DOMAIN=https://ваш-домен

curl $DOMAIN/api/health                     # status: ok
curl $DOMAIN/api/debug/routing              # routing_ok: true
curl $DOMAIN/api/cron/broadcast-tick \
     -H "Authorization: Bearer <CRON_SECRET>"   # status: idle
```

Далі в боті: `/start` → підтвердити вік → каталог → додати товар → оформити.
Замовлення має впасти в адмін-групу з кнопками статусів і з'явитись у панелі.

---

# ЧАСТИНА 2. Власний сервер

## 2.1. Сервер

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

## 2.2. Код і конфігурація

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

## 2.3. Сертифікат

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

## 2.4. Запуск

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

## 2.5. Перевірка

```bash
curl https://ваш-домен.com/api/health
```

Бот тут працює через **polling** — окремих дій не потрібно, він уже
підключений. Напишіть `/start`.

Якщо бот мовчить:

```bash
docker compose -f docker-compose.prod.yml logs bot
```

Найчастіша причина — лишився активний вебхук від попередніх спроб:

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/deleteWebhook"
docker compose -f docker-compose.prod.yml restart bot
```

## 2.6. Бекапи

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
      ┌──────────┴──────────┐
      │                     │
 вебхук (Vercel)      polling (сервер)
      │                     │
      └──────────┬──────────┘
                 ▼
        ┌─────────────────┐        ┌──────────────┐
        │   Хендлери      │───────▶│  Repository  │
        │   бота          │        │  (інтерфейс) │
        └─────────────────┘        └──────┬───────┘
                                          │
        ┌─────────────────┐               ├──▶ Firestore  (Vercel)
        │  API + панель   │──────────────▶│
        └─────────────────┘               └──▶ Postgres   (сервер)
                 ▲
                 │
          планувальник ──▶ /api/cron/broadcast-tick
```

Бот і панель працюють з однією базою через спільний інтерфейс `Repository`.
Тому замовлення з бота одразу видно в панелі, а зміна статусу в панелі
надсилає клієнту повідомлення в Telegram.

---

# Типові помилки

| Симптом | Причина | Виправлення |
|---|---|---|
| «Бекенд не знайдено», 404 | Root Directory = `dashboard` | Змінити на корінь, передеплоїти |
| «Бекенд не налаштований» | Бракує змінних | Дивіться список у самому повідомленні |
| Бекенд відповідає 500 | Зламаний ключ Firebase або `DATABASE_URL` | Логи функції / `docker compose logs api` |
| Не пускає з правильним паролем | Змінна не перечиталась | Vercel: передеплой. Сервер: `up -d --force-recreate api` |
| Бот мовчить (Vercel) | Вебхук не зареєстровано | Крок 1.9 |
| Бот мовчить (сервер) | Лишився активний вебхук | `deleteWebhook`, перезапуск бота |
| Бот забуває крок оформлення | Немає `REDIS_URL` | Додати Redis |
| Замовлення не падають у групу | Невірний `ADMIN_CHAT_ID` | Має бути від'ємне число |
| Кнопки статусів не працюють | Ваш ID не в `ADMIN_IDS` | Додати через кому |
| Розсилка висить у «Надсилається» | Планувальник не налаштований | Крок 1.10 |
| Firestore: помилка про індекс | Індекси не накочені | `firebase deploy --only firestore:indexes` |

## Діагностика

```bash
curl https://ваш-домен/api/health          # конфігурація
curl https://ваш-домен/api/debug/routing   # маршрутизація
```

Vercel: **проєкт → Logs**.
Сервер: `docker compose -f docker-compose.prod.yml logs -f api bot`.

При невдалому вході API пише в лог, який логін очікує й яка довжина пароля
підвантажилась — сам пароль у логи не потрапляє.
