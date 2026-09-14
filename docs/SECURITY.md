# Security hardening

Цей реліз додає захист секретів і зменшує blast radius контейнерів.

## Обов’язково перед production

1. `.env` має режим `600`; згенеруйте `JWT_SECRET`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `CRON_SECRET`, `WEBHOOK_SECRET`, `DATA_ENCRYPTION_KEY`.
2. Не додавайте сервісного користувача `shop` у групу `docker`: членство в `docker` фактично дорівнює root. Деплой виконуйте через root/systemd.
3. Відкриті назовні лише 22, 80, 443. Postgres/Redis портів на host не мають.
4. Зберігайте зашифрований off-site backup окремо від VPS. Локальна копія на тому самому диску не захищає від компрометації/видалення сервера.
5. `DATA_ENCRYPTION_KEY` резервуйте окремо від дампа БД. Без нього зашифровані інтеграційні ключі не відновити.
6. `/api/telegram-setup` і `/api/telegram-detach` приймають `CRON_SECRET` тільки через `Authorization: Bearer ...`; не передавайте секрети в URL.
7. Після ротації `BOT_TOKEN`, `JWT_SECRET`, паролів БД/Redis перезапустіть стек і перевірте `deploy/security-check.sh`.

## Що захищено кодом

- Telegram Mini App initData: HMAC, TTL, верхня межа розміру, дублікати критичних полів, майбутній `auth_date`.
- Nova Poshta API key шифрується Fernet перед записом у БД.
- query-secret-и і відомі секрети редагуються в логах.
- debug endpoints доступні лише sysadmin; public health не видає build/config.
- Redis має пароль; backend контейнери працюють без capabilities, `no-new-privileges`, read-only root FS.
- Бот не має доступу до media/backups, scheduler не має доступу до media.
- бекапи створюються з `0600`.

## Межі

Application-level hardening не замінює шифрування диска VPS, SSH ключі, MFA у провайдера/Cloudflare та незалежні off-site backups.
