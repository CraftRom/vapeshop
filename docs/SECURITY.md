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
- Справжня адреса покупця з-за Cloudflare: nginx довіряє `CF-Connecting-IP` лише від офіційних адрес Cloudflare (`deploy/nginx/cloudflare-realip.conf`). Ліміти, журнал безпеки й бани працюють з адресою покупця, а не вузла CDN; підробити адресу запитом на origin в обхід CDN неможливо.
- Бани fail2ban виконує nginx (`deploy/nginx/deny.d/`), а не фаєрвол хоста: за Cloudflare і портами, опублікованими Docker, правило фаєрвола на адресу сканера не спрацьовує.
- uvicorn не довіряє `X-Forwarded-For`; застосунок читає лише `X-Real-IP`, який nginx перезаписує сам.
- Паролі менеджерів — від 12 символів, без однотипних повторів і популярних паролів відповідної довжини.

## Після оновлення на сервері

1. `sudo bash deploy/bootstrap.sh` — ставить нову дію бану fail2ban (`elfar-nginx-deny`) замість `nftables-multiport`.
2. `docker compose -f deploy/docker-compose.prod.yml up -d --force-recreate nginx api` — nginx підхоплює `cloudflare-realip.conf` і `deny.d`, api — команду без `--forwarded-allow-ips`.
3. `bash deploy/security-check.sh` — обидва нові пункти мають бути `OK`.
4. Раз на кілька місяців: `sudo bash deploy/update-cloudflare-ips.sh` (список Cloudflare змінюється рідко; скрипт не зіпсує робочий файл і відкотиться, якщо nginx не прийме новий).

## Межі

Application-level hardening не замінює шифрування диска VPS, SSH ключі, MFA у провайдера/Cloudflare та незалежні off-site backups.
