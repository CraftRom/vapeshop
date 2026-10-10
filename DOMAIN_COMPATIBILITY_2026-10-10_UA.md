# Старий домен, кнопки Telegram та Cloudflare 520 — 10.10.2026

Основна адреса: **https://elfar.pp.ua**. Історична адреса: **www.elfar.pp.ua**.
API 1.18.2; бот 1.15.2. Вітрина і дашборд зберігають свої версії.

## Причина

На скриншоті 520 стосується www.elfar.pp.ua, час 2026-10-10 05:56:40 UTC.
У попередній конфігурації основний server_name обслуговував лише elfar.pp.ua,
а невідомі хости отримували Nginx 444: закриття з'єднання без HTTP-відповіді.
Це конкретний дефект, який узгоджується з Cloudflare 520. Для підтвердження
саме цього інциденту потрібні журнали origin за вказаний час та CF-Ray.
520 може мати й інші причини; виправлення цього маршруту не гарантує
відсутності будь-яких майбутніх мережевих або серверних збоїв.

## Що змінено

- Nginx приймає старий www на HTTP і HTTPS та повертає 308 на основний домен.
  Шлях і query зберігаються; 308 також зберігає HTTP-метод. Наприклад:
  `https://www.elfar.pp.ua/app/?tgWebAppStartParam=product_19`
  → `https://elfar.pp.ua/app/?tgWebAppStartParam=product_19`.
- Старий домен віддає ACME challenge на HTTP для випуску і поновлення TLS.
  Невідомі хости продовжують отримувати 444; відкритого редиректу немає.
- PUBLIC_URL, рендер Nginx, сертифікат і перевірки використовують спільний
  валідований список доменів. www для ELFAR додається автоматично.
  Інші контрольовані старі адреси можна додати через MAIN_DOMAIN_ALIASES;
  для кожної потрібні DNS і покриття сертифікатом.
- Certbot зберігає **обидва домени в SAN**, стабільний cert-name elfar.pp.ua
  і розширює чинний сертифікат. Повторний запуск не примушує новий випуск.
  Виправлено визначення домену, яке раніше могло брати server_name `_`.
  Чинний Nginx перечитує конфігурацію без restart; відсутній контейнер
  відновлюється через recreate. Staging не замінює керований сертифікат.
- Кнопка меню Telegram у polling і webhook використовує спільну канонічну
  адресу; після запису код читає меню назад і перевіряє URL. Тимчасові
  помилки повторюються обмежено, з урахуванням retry_after.
- Стандартні кнопки магазину, чату та рефералів використовують Named Mini App
  `https://t.me/elfarshop_bot/elfar`, зберігаючи Telegram-авторизацію.
  URL цієї Mini App зберігається в BotFather і потребує окремого оновлення.
- Нові кнопки розсилок нормалізуються при збереженні. Для раніше запланованих
  розсилок нормалізація відбувається також перед відправленням; шлях, query і
  fragment зберігаються. Посилання на сторонні сервіси не переписуються.
- При налаштуванні webhook pending updates більше не видаляються.
- Deploy перевіряє API JSON, HTML вітрини, реальний JavaScript bundle та
  HTTP/HTTPS старих доменів. Закриття з'єднання або HTML замість JS зупиняє
  реліз і запускає наявний rollback. Локальний bootstrap probe допускає
  self-signed TLS; зовнішній probe перевіряє довірений сертифікат і DNS.
- Shell-скрипти deploy збережено з Unix LF та правом виконання, щоб після
  розпакування не виникали помилки CRLF або permission denied.
- Додано repair-main-domain.sh для перечитування Nginx без міграцій і
  перебудови застосунків; також зовнішню перевірку та опційний systemd timer.

## Як встановити на /opt/elfar

Це повний архів проєкту. Скопіюйте вміст його верхньої теки в /opt/elfar,
зберігши власний кореневий .env, deploy/data, Docker volumes і сертифікати.
Файл .env та робочі дані в архів не включені.

1. У Cloudflare DNS залиште правильний A/AAAA для elfar.pp.ua. Для www додайте
   CNAME → elfar.pp.ua (або виправте наявний запис). Перевірте, що немає
   конфліктного старого A/AAAA. Якщо використовується Cloudflare proxy,
   обидві адреси мають бути покриті edge-сертифікатом.
2. У /opt/elfar/.env: `PUBLIC_URL=https://elfar.pp.ua`.
   Збережіть таку саму адресу в налаштуваннях магазину, якщо PUBLIC_URL
   перевизначений через дашборд. Старе www також нормалізується кодом.
3. Після розпакування виконайте:

```bash
cd /opt/elfar/deploy
bash certbot-init.sh elfar.pp.ua www.elfar.pp.ua
bash deploy.sh
python3 check-public-routes.py --external
```

Certbot запитає email, якщо CERTBOT_EMAIL не переданий. DNS обох адрес і
порт 80 повинні працювати до випуску. Не використовуйте --staging на
production: тестовий сертифікат не довірений. SSL/TLS Cloudflare має працювати
в Full (strict) після отримання чинного origin-сертифіката на обидві адреси.
HTTPS-редирект сам по собі не виправляє сертифікат: TLS-перевірка передує йому.

Якщо SAN уже покриває обидві адреси, для швидкого виправлення лише Nginx:

```bash
cd /opt/elfar/deploy
bash repair-main-domain.sh
python3 check-public-routes.py --external
```

Повний deploy все одно потрібен для оновлення коду бота/API. У режимі polling
меню оновиться при старті бота. У режимі webhook виконайте наявну авторизовану
процедуру /api/telegram-setup після деплою, щоб і URL webhook став канонічним;
не покладайтеся на HTTP-редирект для доставлення Telegram updates.

4. У **@BotFather** виберіть Mini App `elfar` для `@elfarshop_bot` через
   керування застосунками `/myapps` і змініть її web URL на
   **https://elfar.pp.ua/app/**. Перевірте також Main Mini App / кнопку запуску
   в профілі бота, якщо вона увімкнена. Menu Button оновлюється кодом.
   Bot API не редагує реєстрацію Named/Main Mini App замість BotFather.
5. Перевірте зі старого повідомлення і з меню Telegram: каталог, товар,
   кошик, чат, реферальний запуск. Закрийте та знову відкрийте Mini App.
   Старі повідомлення масово не редагуються: доступ забезпечує редирект.

## Додатковий захист від повторення

**Редирект на Cloudflare edge:** можна додати точне правило Single Redirect
для `http.host eq "www.elfar.pp.ua"`, зі збереженням query, статусом 308 і
ціллю `concat("https://elfar.pp.ua", http.request.uri.path)`.
Виключіть `/.well-known/acme-challenge/` з правила, щоб ACME йшов прямо на
webroot. Повний фільтр:

```text
(http.host eq "www.elfar.pp.ua" and not starts_with(http.request.uri.path, "/.well-known/acme-challenge/"))
```

Це окремий рівень редиректу: старий хост не потребуватиме origin-запиту для
звичайних сторінок. Основний домен усе одно має працювати. Не вимикайте
Full (strict) чи загальний захист сайту для обходу помилки.

**Періодична зовнішня перевірка:** виконувати check-public-routes.py --external
і сповіщати при ненульовому exit code. Для сервера /opt/elfar з користувачем
shop у комплекті готовий timer (5 хвилин). Якщо шлях/користувач інший,
відредагуйте service перед встановленням.

```bash
cd /opt/elfar/deploy
sudo cp elfar-public-check.service elfar-public-check.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now elfar-public-check.timer
sudo systemctl start elfar-public-check.service
sudo journalctl -u elfar-public-check.service -n 30 --no-pager
```

Timer веде журнал, але сам не надсилає сповіщення і не перезапускає сервіси.
Підключіть його exit status до наявного моніторингу або додайте незалежний
uptime monitor. При 403 перевірте Cloudflare WAF/bot challenge і правила для
адреси монітора; це не автоматичний доказ несправності origin.

**Під час нового 520:** запишіть UTC-час, URL без секретних параметрів і CF-Ray;
перевірте nginx/API логи, локальний route probe та зовнішній probe окремо.
Контролюйте поновлення origin TLS і запас місця/пам'яті. Для усунення короткого
простою під час recreate потрібен окремий перехід на два API-інстанси або
blue/green deploy; поточний реліз зберігає фазовий deploy і rollback.

## Перевірки релізу

- 27/27 на справжньому Nginx 1.30.5: редиректи HTTP/HTTPS, GET/POST,
  шлях/query, ACME, TLS SAN, API, JS bundle, негативні route gates, захист
  невідомих host, rate limit, медіа, CSP і промо-домен.
- 12 поведінкових тестів міграції доменів, SAN аргументів certbot,
  кнопок розсилок, читання меню назад, retry та flood control.
- 6 тестів фазового deploy, включно з реальним FastAPI TrustedHost та
  rollback при збої публічного маршруту.
- Супутні перевірки security, production deploy, .env, scheduler і wiring.
  Логи: qa/output/domain-*.log.

Production VPS і Cloudflare з цього середовища не змінювалися. В архіві
готові зміни; DNS, SAN, BotFather та фактичний доступ потрібно перевірити
після встановлення.

Первинні джерела:
- https://nginx.org/en/docs/http/request_processing.html
- https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-520/
- https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/
- https://developers.cloudflare.com/rules/url-forwarding/single-redirects/settings/
- https://core.telegram.org/bots/webapps
