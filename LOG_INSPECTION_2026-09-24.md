# ELFAR — інспекція production-логів 2026-09-24

Перевірено:
- elfar-api-full (1).log
- elfar-storefront (6).log
- elfar-bot (6).log
- elfar-security-full (1).log

## Головна знайдена проблема

Mini App після завершення 24-годинного `initData` не зупиняв фонову активність.
Одна довго відкрита Desktop-сесія створила:
- 147 `security.initdata.rejected`;
- 352 HTTP 401 на `/api/shop/*`;
- 205 повторних 401 лише на `/api/shop/orders/stream`.

Після першого 401 SSE продовжував reconnect до 15 секунд, а background polling
продовжував читати orders/profile/cart/config. Це не витік даних — сервер правильно
відхиляв запити, але це створювало шум у security/API logs і зайве навантаження.

Також прострочений, але криптографічно правильний `initData` класифікувався тією
самою security-подією, що і підроблений підпис. Це хибна класифікація.

## Виправлено в 1.51.9 / Mini App 2.16.6 / API 1.14.9

- будь-який 401 Mini App стає terminal auth failure для поточного WebView;
- після першого 401 зупиняються SSE, polling і background refresh;
- UI показує одну зрозумілу причину замість reconnect-loop;
- після повторного відкриття Mini App модульний стан скидається і Telegram
  передає свіжий `initData`;
- `security.initdata.expired` — окрема подія рівня `info`;
- підроблений/зіпсований підпис лишається `security.initdata.rejected` рівня notice;
- network disconnect під час hidden WebView не пишеться як warning;
- успішний legacy `www → apex` bridge тепер `info`, warning лишається лише коли
  Telegram-підпис справді не вдалося отримати.

## Інші результати логів

### SalesDrive
- 311 watchdog cycles;
- checked/refreshed: 1136/1136;
- failed: 0;
- deferred: 522;
- створення SalesDrive заявок №67–76 видно в логах;
- webhook і background reconciler працюють;
- оновлення ТТН приходять із `source=salesdrive`.

Ознак повторення старої проблеми «статус оновлюється лише після відкриття картки»
в цих логах немає.

### Bot
- 4 error-записи — тимчасові `TelegramServerError: Bad Gateway`;
- aiogram автоматично повторив polling;
- SIGTERM — штатні рестарти/deploy, не падіння процесу.

Два повідомлення клієнтам не доставлені, бо користувачі заблокували бота:
`TelegramForbiddenError: bot was blocked by the user`. Замовлення при цьому не
скасовувались.

### Security
- 1 SalesDrive webhook із неправильним токеном — відхилений;
- зовнішні probe-запити `/api/mcp`, `/api/gql`, `/api/session/properties`,
  version endpoints отримали 404;
- ознак успішного обходу авторизації або доступу до даних у наданих логах немає.

## Deployment observation

Storefront logs показують клієнтів на `2.16.3` і `2.16.4`.
Остання збірка до цього hotfix була `2.16.5`, отже на момент логів частина
клієнтів/production ще працювала не на останній Mini App збірці. Після deploy
треба перевірити `appVersion=2.16.6` у storefront logs.
