# Розгортання: покроково

Інструкція для чистого сервера з Ubuntu 22.04 або 24.04. Наприкінці ви маєте
робочий магазин: бот у Telegram, панель керування, вітрину Mini App, власну
базу й автозапуск після перезавантаження.

**Мінімум:** 2 vCPU, 2 ГБ RAM, 20 ГБ диска. Цього вистачає з великим запасом.

Кожен крок закінчується перевіркою. Не переходьте далі, поки перевірка не
пройшла — інакше причину доведеться шукати серед п'яти кроків замість одного.

---

## Що знадобиться заздалегідь

| Що | Де взяти | Навіщо |
|---|---|---|
| Токен бота | [@BotFather](https://t.me/BotFather) → `/newbot` | Без нього нічого не працює |
| ID групи замовлень | Додайте [@getmyid_bot](https://t.me/getmyid_bot) у групу, потім приберіть | Куди падають нові замовлення |
| Ваш Telegram ID | [@userinfobot](https://t.me/userinfobot) | Доступ до `/admin` у боті |
| Домен | Реєстратор | TLS і Mini App без домену неможливі |
| Сервер | Будь-який VPS | Ubuntu 22.04/24.04 |

Домен має вказувати на IP сервера **до** початку: сертифікат видається за
фактом того, що домен уже резолвиться.

```bash
dig +short ваш-домен.com     # має вивести IP сервера
```

---

## Швидкий шлях

Якщо все з таблиці вище готове:

```bash
ssh root@ваш-сервер
git clone <ваш-репозиторій> /opt/elfar
cd /opt/elfar
sudo bash deploy/bootstrap.sh
```

Скрипт зупиниться й попросить заповнити `BOT_TOKEN`, `PUBLIC_URL` та
`ADMIN_CHAT_ID`. Після цього:

```bash
nano /opt/elfar/.env
systemctl start elfar
```

Далі — крок 6 (сертифікат) і крок 8 (перевірка). Решта кроків нижче описує
те саме вручну: читайте їх, якщо щось пішло не так або хочете розуміти, що
саме скрипт зробив із вашим сервером.

---

## Крок 1. Підготовка сервера

```bash
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
```

Docker має підніматися сам після перезавантаження — інакше автозапуск магазину
не спрацює, скільки б налаштувань не стояло далі:

```bash
systemctl enable --now docker
systemctl is-enabled docker      # має вивести: enabled
```

**Перевірка:**

```bash
docker run --rm hello-world      # має вивести привітання
```

---

## Крок 2. Користувач

Магазин не повинен працювати від root. Створюємо окремого користувача:

```bash
adduser --disabled-password --gecos "" shop
usermod -aG docker shop
```

> Членство в групі `docker` фактично дорівнює root: хто може запускати
> контейнери, той може змонтувати `/` і зробити з системою що завгодно. Це
> свідомий компроміс заради зручності. Якщо сервером користується більше
> однієї людини — краще лишити запуск за `sudo` і не додавати нікого в групу.

**Перевірка:**

```bash
id shop                          # запам'ятайте uid= — знадобиться в кроці 4
sudo -u shop docker ps           # має відпрацювати без помилки прав
```

---

## Крок 3. Фаєрвол

```bash
apt install -y ufw
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

Postgres і Redis назовні **не відкриваємо**. Вони живуть у внутрішній мережі
Docker, і сервіси ходять до них за іменами `db` і `redis`. Порт 5432,
відкритий «щоб підключитися клієнтом», — найкоротший шлях до вкраденої бази.

**Перевірка:**

```bash
ufw status                       # у списку лише 22, 80, 443
```

---

## Крок 4. Код і конфігурація

```bash
su - shop
git clone <ваш-репозиторій> ~/elfar
cd ~/elfar
cp .env.example .env
```

Згенеруйте секрети — не вигадуйте їх руками:

```bash
echo "JWT_SECRET=$(openssl rand -hex 32)"
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)"
echo "DASHBOARD_PASSWORD=$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-16)"
echo "CRON_SECRET=$(openssl rand -hex 16)"
echo "WEBHOOK_SECRET=$(openssl rand -hex 16)"
```

Тепер `nano .env`. Заповніть:

| Змінна | Значення |
|---|---|
| `BOT_TOKEN` | Токен від BotFather |
| `PUBLIC_URL` | `https://ваш-домен.com` — саме https, без слеша в кінці |
| `ADMIN_CHAT_ID` | ID групи, від'ємне число виду `-1001234567890` |
| `ADMIN_IDS` | Ваш ID, через кому якщо кілька |
| `JWT_SECRET` та інші секрети | Згенеровані вище |
| `DATABASE_URL` | Той самий пароль, що в `POSTGRES_PASSWORD` |
| `APP_UID`, `APP_GID` | `id -u shop` та `id -g shop` з кроку 2 |

Два місця, де найчастіше помиляються:

**Пароль бази — у двох змінних.** `POSTGRES_PASSWORD` створює користувача
в Postgres, `DATABASE_URL` до нього підключається. Якщо вони розійдуться,
API не зайде у власну базу, а помилка виглядатиме як `password authentication
failed` глибоко в логах.

**`APP_UID` — не косметика.** За ним збирається образ бекенду, і процеси
всередині контейнерів працюють від цього числового користувача. Якщо він не
збігається з власником каталогу `deploy/backups`, планувальник або не зможе
писати дампи, або запише файли, які ви не видалите без sudo. Докладніше —
[розділ про користувача в контейнерах](#користувач-у-контейнерах).

Закрийте файл від сторонніх — у ньому всі паролі магазину:

```bash
chmod 600 .env
mkdir -p deploy/backups && chmod 750 deploy/backups
```

**Перевірка:**

```bash
grep -c 'change_this\|1234567890:AA\|-1001234567890' .env    # має бути 0
```

---

## Крок 5. Перший запуск

```bash
cd ~/elfar/deploy
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml run --rm migrate
docker compose -f docker-compose.prod.yml up -d
```

Збірка на слабкому сервері займає кілька хвилин — це нормально.

Порядок не випадковий: `migrate` накочує схему й завершується, і лише потім
стартують `api`, `bot` і `scheduler`. У compose це закріплено умовою
`service_completed_successfully`, тож навіть при простому `up -d` схема буде
накочена раніше за перший запит.

**Перевірка:**

```bash
docker compose -f docker-compose.prod.yml ps
```

Усі сервіси мають бути `Up`, а `db` і `redis` — ще й `(healthy)`. Сервіс
`migrate` у списку буде `Exited (0)` — так і має бути, він одноразовий.

```bash
docker compose -f docker-compose.prod.yml exec api \
    python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/api/health').read().decode())"
```

Очікується `"status":"ok"` і порожній `missing_env`.

Наповніть каталог демо-даними, якщо потрібно:

```bash
docker compose -f docker-compose.prod.yml exec api python seed.py
```

---

## Крок 6. Сертифікат

```bash
docker compose -f docker-compose.prod.yml run --rm certbot \
    certonly --webroot -w /var/www/certbot \
    -d ваш-домен.com --agree-tos --no-eff-email -m ваш@email.com

docker compose -f docker-compose.prod.yml restart nginx
```

Продовження працює само — контейнер `certbot` перевіряє строк двічі на добу.

**Перевірка:**

```bash
curl -sI https://ваш-домен.com | head -1        # HTTP/2 200
```

---

## Крок 7. Автозапуск

```bash
exit    # назад у root
cd /home/shop/elfar

install -m 644 deploy/elfar.service /etc/systemd/system/elfar.service
sed -i -e "s|__REPO_DIR__|/home/shop/elfar|g" -e "s|__USER__|shop|g" \
    /etc/systemd/system/elfar.service
systemctl daemon-reload
systemctl enable elfar
```

Чому це потрібно, якщо в compose уже стоїть `restart: always`. Ця політика
піднімає контейнер, який **упав**. Але якщо стек зупинили командою
`docker compose down` — а саме так виглядає коректне вимкнення сервера —
після перезавантаження контейнери лишаться зупиненими. Юніт дивиться на це
інакше: його цікавить стан «стек має працювати», а не стан окремих
контейнерів.

**Перевірка — обов'язкова, і саме зараз, а не тоді, коли сервер
перезавантажиться сам:**

```bash
reboot
# зачекайте хвилину-дві, зайдіть знову
systemctl status elfar
curl -s https://ваш-домен.com/api/health
```

---

## Крок 8. Telegram і перевірка наскрізь

Бот за замовчуванням працює через polling — сам ходить по оновлення. Нічого
реєструвати не треба, але старий вебхук, якщо він лишився від попереднього
розгортання, забиратиме оновлення собі:

```bash
curl "https://api.telegram.org/bot<ВАШ_ТОКЕН>/deleteWebhook?drop_pending_updates=true"
```

Найважливіша перевірка в усій інструкції:

1. Напишіть боту `/start` — має відповісти
2. Пройдіть підтвердження віку, відкрийте каталог
3. Оформіть тестове замовлення
4. Замовлення має впасти у вашу групу
5. Відкрийте панель `https://ваш-домен.com`, увійдіть із `DASHBOARD_PASSWORD`
6. Замовлення має бути в списку; змініть статус — клієнту прийде повідомлення

Якщо всі шість пунктів пройшли — розгортання завершено.

---

## Користувач у контейнерах

За замовчуванням процес усередині контейнера працює від **root**. Це root
не вашого сервера, але два наслідки неприємні: діра в будь-якій залежності
дає повні права всередині контейнера, а файли, які контейнер пише в
примонтований каталог, належать root уже на хості.

Друге видно одразу на бекапах: планувальник пише дампи в `deploy/backups`,
і без налаштування вони належали б root, а користувач `shop` не зміг би ні
скопіювати їх кудись, ні видалити.

Тому образ бекенду створює користувача `shop` із тими самими UID/GID, що й
на хості, і перемикається на нього:

```dockerfile
ARG APP_UID=1000
ARG APP_GID=1000
...
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd -g "$APP_GID" shop \
    && useradd -u "$APP_UID" -g "$APP_GID" -m -s /usr/sbin/nologin shop

COPY . .
RUN chown -R shop:shop /app
USER shop
```

Порядок має значення: залежності ставляться ще від root у `/usr/local`, куди
застосунку писати не потрібно й не можна. Перемикання на `shop` — останнім,
після `chown` на код.

Числа приходять зі збірки, а не зашиті в образ:

```yaml
x-backend-build: &backend-build
  context: ../backend
  args:
    APP_UID: ${APP_UID:-1000}
    APP_GID: ${APP_GID:-1000}
```

Той самий якір використовують `migrate`, `api`, `bot` і `scheduler` — образ
один, різниця лише в команді.

**Перевірка:**

```bash
cd ~/elfar/deploy
docker compose -f docker-compose.prod.yml exec api id
# uid=1000(shop) gid=1000(shop)

ls -l backups/
# дампи належать shop, а не root
```

Якщо `id` показує `uid=0(root)` — образ зібрано до того, як `APP_UID`
з'явився в `.env`. Пересоберіть із нуля:

```bash
docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d
```

### Чому не всі контейнери такі

`postgres` і `redis` в офіційних образах уже перемикаються на власних
непривілейованих користувачів — втручатися не треба й шкідливо.

`nginx` стартує від root навмисно: щоб зайняти порт 80 всередині контейнера,
потрібні права, а робочі процеси він одразу скидає на користувача `nginx`.
Це стандартна й безпечна поведінка.

### Якщо UID уже зайнятий

Буває, що `id -u shop` дає число, зайняте в базовому образі. Тоді збірка
впаде з `useradd: UID ... is not unique`. Візьміть інше:

```bash
usermod -u 1500 shop
groupmod -g 1500 shop
chown -R shop:shop /home/shop/elfar
```

Далі оновіть `APP_UID`/`APP_GID` у `.env` і пересоберіть образ.

---

## Оновлення

```bash
su - shop
cd ~/elfar
git pull
deploy/deploy.sh
```

Скрипт сам робить бекап перед оновленням, збирає образи, накочує міграції,
перезапускає сервіси й чекає, поки API стане здоровим. Якщо API не піднявся
за хвилину — скрипт зупиняється й показує логи, а не лишає вас із мовчазним
сервером.

---

## Бекапи

Регулярні знімки робить планувальник за розкладом із панелі
(Налаштування → Бекапи). Формат — `pg_dump -Fc`: стискається вдвічі проти
звичайного SQL і дозволяє відновлювати окремі таблиці.

Позаплановий знімок:

```bash
deploy/backup.sh
```

Відновлення розуміє обидва формати — і новий `.dump`, і старий `.sql.gz`
з попередніх версій:

```bash
deploy/restore.sh backups/elfar-2026-08-19.dump
```

Скрипт зупиняє бота, API й планувальник, відновлює базу, накочує міграції
(бекап може бути старішим за поточну схему) і запускає все назад.

**Копіюйте бекапи за межі сервера.** Диск може померти разом з ними:

```cron
30 4 * * * rsync -az /home/shop/elfar/deploy/backups/ user@інший-хост:/backups/elfar/
```

Це єдине, що лишається за системним cron: воно стосується не магазину,
а того, що сервер може зникнути цілком.

---

## Якщо щось не працює

| Симптом | Причина | Що робити |
|---|---|---|
| `migrate` падає | База ще не готова | `docker compose ps db` — має бути `healthy` |
| API: password authentication failed | `POSTGRES_PASSWORD` ≠ пароль у `DATABASE_URL` | Вирівняйте, `up -d --force-recreate api db` |
| Панель: «Бекенд не налаштований» | Бракує змінних | Список — у самому повідомленні на екрані |
| Панель не пускає з правильним паролем | Змінна не перечиталась | `up -d --force-recreate api` |
| Бот мовчить | Лишився активний вебхук | `deleteWebhook`, потім `restart bot` |
| Бот забуває крок оформлення | Немає `REDIS_URL` | Додайте Redis у `.env` |
| Замовлення не падають у групу | `ADMIN_CHAT_ID` невірний | Має бути від'ємне число |
| Кнопки статусів не працюють | Вашого ID немає в `ADMIN_IDS` | Додайте через кому |
| Дампи належать root | Образ зібрано без `APP_UID` | `build --no-cache`, див. розділ вище |
| Відкладена розсилка не пішла | Тихі години або ще не було тіку | Планувальник тікає раз на годину |
| Після ребуту нічого не піднялось | Юніт або docker вимкнено | `systemctl enable --now elfar docker` |

### Діагностика

```bash
curl https://ваш-домен/api/health            # конфігурація й версія збірки
curl https://ваш-домен/api/debug/database    # чи жива база просто зараз
curl https://ваш-домен/api/debug/routing     # маршрутизація

systemctl status elfar
docker compose -f docker-compose.prod.yml logs -f api bot scheduler
```

При невдалому вході API пише в лог, який логін очікує й яка довжина пароля
підвантажилась — сам пароль у логи не потрапляє.

---

Довідник із поясненнями архітектурних рішень — [SERVER.md](SERVER.md).
