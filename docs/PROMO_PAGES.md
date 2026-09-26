# Конструктор промо-сторінок

Модуль **Промо-сторінки** створює landing pages за одним контрольованим шаблоном. Менеджер не має доступу до CSS, JavaScript або довільного HTML: редагуються лише тексти, промокод, CTA, локальні зображення, домен і SEO.

## Права менеджера

Промо-сторінки доступні звичайному авторизованому менеджеру. Для щоденної роботи не потрібні SSH, root, Docker, certbot або доступ до серверної консолі.

Менеджер може з панелі:

- створити сторінку;
- змінити контент та SEO;
- вказати домен;
- перевірити DNS;
- підключити домен;
- автоматично отримати TLS/HTTPS;
- побачити термін дії сертифіката;
- публікувати та повторно публікувати сторінку;
- відключити домен;
- переглядати views/clicks/CTR.

## Ізоляція доменів

Інфраструктурні операції винесені з основного API у окремий контейнер **promo-controller**.

Він навмисно обмежений:

- не має Docker socket;
- не має доступу до PostgreSQL;
- не має доступу до Redis;
- не бачить логи, бекапи та дані магазину;
- не має зовнішнього порту;
- доступний API лише у окремій Docker network `promo_control`, яка має `internal: true`;
- бачить тільки окремий volume `promo-nginx-conf`, ACME webroot та `/etc/letsencrypt`;
- nginx бачить `promo-nginx-conf` лише read-only;
- ділить PID namespace тільки з nginx;
- має лише capability `KILL`, потрібну для `SIGHUP` nginx після атомарної зміни конфігурації або TLS renew.

Основний API звертається до контролера через внутрішній bearer secret `PROMO_CONTROLLER_TOKEN`. Цей секрет не передається браузеру.

## Підключення домену без консолі

У вкладці **Домен і деплой** менеджер вводить домен та натискає **Підключити домен**.

Система виконує:

1. нормалізацію та сувору перевірку доменного імені;
2. DNS lookup A/AAAA;
3. тимчасовий HTTP route тільки для ACME challenge;
4. отримання/повторне використання Let's Encrypt сертифіката;
5. створення production HTTPS route;
6. `SIGHUP` nginx без restart контейнера;
7. повернення у UI статусів DNS, route, TLS та дати завершення сертифіката.

Якщо DNS ще не оновився або ACME не підтвердив домен, менеджер отримує зрозумілу помилку у панелі та може повторити операцію пізніше.

Після підключення домен блокується від редагування. Щоб змінити його, менеджер спочатку натискає **Відключити домен**. Це прибирає nginx route та автоматично знімає сторінку з публікації. Сертифікат навмисно не стирається одразу — це забезпечує безпечний rollback/reconnect.

## TLS renew

`promo-controller` раз на 12 годин запускає `certbot renew`. Після успішної перевірки він посилає nginx `SIGHUP`, тому nginx перечитує оновлені сертифікати без ручного втручання та без downtime.

## Модель публікації

- `draft_config` — поточна чернетка редактора.
- `published_config` — snapshot останньої успішної публікації.
- «Зберегти» не змінює живий сайт.
- «Опублікувати» дозволено лише для вже підключеного домену.
- «Опублікувати» копіює чернетку в production snapshot і збільшує version.
- «Зняти» вимикає сторінку без видалення конфігурації та статистики.

## Зображення

Промо-сторінки приймають тільки `/media/...`. Файли завантажуються через наявне локальне сховище та віддаються nginx напряму. Зовнішні hotlink-зображення API відхиляє.

## SEO

Шаблон автоматично формує semantic HTML5, title, description, robots, canonical, Open Graph, Twitter Card, JSON-LD `WebPage`, абсолютні social-image URL, responsive viewport та один H1.

## Статистика

Зберігаються денні агрегати `views` і `clicks`; CTR обчислюється як `clicks / views`. IP, cookies та окремі event rows не зберігаються. Відомі crawler/bot User-Agent не збільшують views.

CTA на production веде через `/go`: API збільшує click counter та робить 302 redirect на налаштований URL.

## Одноразова конфігурація сервера

Під час звичайного deployment системний адміністратор має один раз задати у `.env`:

- `PROMO_CONTROLLER_TOKEN` — bootstrap генерує його автоматично.

`CERTBOT_EMAIL` необов’язковий: якщо він заданий, Let’s Encrypt може використовувати його для службових сповіщень; якщо порожній, підключення доменів із панелі все одно працює. Після deployment усі домени керуються з панелі.


## SEO help and contextual generation (v1.55.0)

Every SEO input in the dashboard has a keyboard-accessible `?` help control. The tooltip explains what the field is, where it is consumed, and what practical effect it has.

New pages receive an initial SEO configuration automatically. The generator derives facts only from the page name, domain, promo content, CTA context and local media. It uses multiple title/description/OG/Schema composition families selected from a seeded hash, extracts offer signals such as percentage or UAH discount when present, deduplicates keywords, clamps output to field limits and never injects arbitrary HTML. Explicit **Generate SEO** produces another wording family; normal Save never silently overwrites manual SEO edits.

The `keywords` tooltip explicitly notes that Google does not use `meta keywords` as a direct ranking signal; the field remains for compatibility and other consumers.
