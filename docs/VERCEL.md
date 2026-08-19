# Розгортання на Vercel

> **Основна інструкція — [DEPLOY.md](DEPLOY.md).** Там покроковий
> сценарій для Vercel від початку до перевірки. Цей файл лишено як
> довідник із деталями та поясненнями рішень.


## Спершу прочитайте це

Vercel — serverless-платформа. Вона не тримає довгих процесів, і це накладає
реальні обмеження. Вони обходяться, але їх треба знати **до** початку:

| Що | Наслідок | Як обходимо |
|---|---|---|
| Немає постійного процесу | Polling неможливий | Бот працює через вебхук |
| Ліміт часу функції: 10 с (Hobby), 60 с (Pro) | Розсилка на 5000 осіб не влізе в один виклик | Порції по 100 + планувальник |
| Cron на Hobby — раз на добу | Розсилка стартувала б наступного дня | Зовнішній планувальник (безкоштовно) |
| Пам'ять не переживає запит | Багатокрокове оформлення замовлення ламається | **Обов'язково** Redis (Upstash) |
| Холодний старт 1–3 с | Перша відповідь бота повільна | Мириться, або Pro з Fluid Compute |
| Немає своєї БД | — | Firestore (типово) або Neon |

**Якщо очікується більше кількох сотень замовлень на місяць або розсилки по
великій базі — власний сервер вийде і простішим, і дешевшим.** Vercel добре
підходить, щоб швидко підняти й перевірити ідею.

---

## Крок 1. База даних — Firestore

На Vercel типова база — **Firestore**: немає лімітів на з'єднання, немає
холодного конекту, безкоштовна квота покриває невеликий магазин.
Повна інструкція — **[docs/FIREBASE.md](FIREBASE.md)**, коротко:

1. [console.firebase.google.com](https://console.firebase.google.com) →
   Create project → Firestore Database → Production mode, регіон `europe-central2`
2. Project settings → Service accounts → Generate new private key
3. Накотіть індекси й правила:
   ```bash
   npm install -g firebase-tools && firebase login && firebase use --add
   firebase deploy --only firestore:indexes,firestore:rules
   ```

**Альтернатива — Postgres.** Якщо потрібна саме реляційна база, візьміть
[Neon](https://neon.tech) і задайте `DB_BACKEND=sql`. Обов'язково **pooled**
рядок підключення (містить `-pooler`), схема `postgresql+asyncpg://`,
без `?sslmode=require` — asyncpg його не розуміє.

## Крок 2. Redis

[Upstash](https://upstash.com) → Create Database → скопіюйте `rediss://` URL.

Без нього оформлення замовлення (ім'я → телефон → місто → …) розсипатиметься:
кожен крок може потрапити в інший процес, який нічого не пам'ятає про попередній.

## Крок 3. Наповнення каталогу

Firestore не потребує міграцій — колекції створюються при першому записі.
Демо-каталог (за бажанням):

```bash
cd backend && pip install -r requirements.txt
DB_BACKEND=firestore FIREBASE_PROJECT=ваш-проєкт \
  GOOGLE_APPLICATION_CREDENTIALS=/шлях/ключ.json \
  PYTHONPATH=$PWD python seed.py
```

Якщо обрали Postgres — замість цього накотіть міграції:
`PYTHONPATH=$PWD alembic upgrade head`

## Крок 4. Деплой — ОДИН проєкт

Панель і API живуть в одному проєкті Vercel і на одному домені. Так немає
CORS і немає ризику, що панель не знайде бекенд.

New Project → імпорт репозиторію → **Root Directory лишити кореневим**
(не `dashboard`, не `backend`). `vercel.json` уже налаштований: збирає панель
із `dashboard/`, а `api/index.py` віддає як serverless-функцію.

Змінні оточення (Settings → Environment Variables):

```
SERVERLESS=true
DB_BACKEND=firestore
FIREBASE_PROJECT=ваш-проєкт-id
GOOGLE_APPLICATION_CREDENTIALS_JSON=<увесь вміст JSON ключа>
BOT_TOKEN=...
BOT_USERNAME=your_shop_bot
ADMIN_CHAT_ID=-100...
ADMIN_IDS=123456789
REDIS_URL=rediss://...upstash...
JWT_SECRET=<openssl rand -hex 32>
DASHBOARD_LOGIN=admin
DASHBOARD_PASSWORD=<надійний пароль>
WEBHOOK_SECRET=<openssl rand -hex 16>
CRON_SECRET=<openssl rand -hex 32>
PUBLIC_URL=https://ваш-домен
CARD_NUMBER=...
CARD_HOLDER=...
```

`CORS_ORIGINS` і `VITE_API_URL` **не потрібні** — все на одному домені.

`PUBLIC_URL` заповніть після першого деплою, коли з'явиться домен,
і задеплойте ще раз.

Перевірка:

```bash
curl https://ваш-домен/api/health
# {"status":"ok","shop":"..."}
```

Екран входу тепер сам перевіряє API і скаже, якщо той недоступний.

## Крок 5. Реєстрація вебхука

Одноразово після деплою:

```bash
curl "https://ваш-домен/api/telegram-setup?token=<CRON_SECRET>"
```

Відповідь має містити `webhook_url`. Напишіть боту `/start` — має відповісти.

## Крок 6. Якщо все ж потрібні два проєкти

Такий поділ має сенс, лише якщо панель і API мусять жити на різних доменах.
Тоді:

1. Проєкт панелі: Root Directory `dashboard`, змінна
   `VITE_API_URL=https://ваш-api-домен/api`
2. Проєкт API: Root Directory кореневий
3. У бекенді задайте `CORS_ORIGINS=https://домен-панелі`

**Саме пропуск кроку 1 дає помилку «Ендпоінт не знайдено»**: без
`VITE_API_URL` панель стукає на власний домен, де функцій немає.

## Крок 7. Планувальник розсилок

`vercel.json` уже містить cron, але на Hobby він відпрацює лише раз на добу —
для розсилок цього замало.

Візьміть будь-який зовнішній планувальник, наприклад
[cron-job.org](https://cron-job.org) (безкоштовно):

- URL: `https://your-api.vercel.app/api/cron/broadcast-tick`
- Метод: GET
- Заголовок: `Authorization: Bearer <CRON_SECRET>`
- Інтервал: кожні 2 хвилини

Кожен виклик відправляє до 100 повідомлень і рухає курсор далі. Розсилка на
1000 осіб розтягнеться приблизно на 20 хвилин — це нормально й безпечно щодо
лімітів Telegram.

Якщо у вас Pro — можна лишити вбудований cron, замінивши в `vercel.json`
розклад на `*/2 * * * *`.

---

## Перевірка після деплою

```bash
API=https://your-api.vercel.app

curl $API/api/health
# {"status":"ok","shop":"..."}

curl -X POST $API/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"login":"admin","password":"ваш-пароль"}'
# має повернути access_token

curl $API/api/cron/broadcast-tick -H "Authorization: Bearer <CRON_SECRET>"
# {"status":"idle",...}
```

Далі — `/start` боту й вхід у панель.

## Якщо щось не працює

| Симптом | Причина |
|---|---|
| «Ендпоінт не знайдено» на вході | Панель і API в різних проєктах, а `VITE_API_URL` не задано. Розгорніть одним проєктом (крок 4) |
| Бот мовчить | Вебхук не зареєстровано — крок 5 |
| Бот забуває крок оформлення | Немає `REDIS_URL` |
| 500 на всіх запитах | Перевірте `GOOGLE_APPLICATION_CREDENTIALS_JSON` і `FIREBASE_PROJECT` |
| Помилка про відсутній індекс | Накотіть `firebase deploy --only firestore:indexes` |
| Панель не бачить API (два проєкти) | Домен панелі не доданий у `CORS_ORIGINS` |
| Розсилка висить у «Надсилається» | Планувальник не налаштовано — крок 7 |

Логи: Vercel → проєкт → Logs.
