# Браузерна перевірка інтерфейсу

Перевіряє реальні React-застосунки з тестовими відповідями API та тестовим Telegram SDK. Не потребує доступу до робочих облікових записів.

1. У `dashboard` та `miniapp` встановіть залежності: `npm ci`.
2. У цьому каталозі виконайте `npm ci`, `npx playwright install chromium`, `npm test`.

Скрипт сам запускає та зупиняє панель на порту 5173 і вітрину на порту 5174. Перед запуском ці порти мають бути вільні. Для сценарію оновленого каталогу окремо: `npm run test:catalog`.

За потреби задайте `DASHBOARD_URL`, `MINIAPP_URL`, `QA_OUTPUT_DIR` або `PLAYWRIGHT_EXECUTABLE_PATH`. Знімки екрана зберігаються в `output/`.

Сценарії: прокручування меню панелі, горизонтальних категорій і фільтрів, довгого списку бажаного; загальний вимикач і мінімальне збереження налаштувань; пошук налаштувань; клавіатурний фокус/Escape; блокування й відновлення скролу; помилка мережі та повторне завантаження каталогу; відсутність помилок JavaScript і зайвого горизонтального скролу сторінки.

`browser-catalog.mjs` перевіряє створення товару без груп, автоматичний SKU, окремі блоки сторінки товару, помилки ціни, відповіді збереження у зворотному порядку, категорії/субкатегорії та однакові новинки, акції, опис і ціни у панелі та вітрині. Тестові товари — нейтральні аксесуари.


## Безпека — 09.10.2026

- `backend/qa/qa_modern_security.py` входить у повний `backend/qa/run_all.sh`.
- `bash qa/run-security-browser.sh`: реальний API, SQLite і браузерний вхід/CSRF/вихід. Потрібен `backend/.qa-venv` або задайте `QA_PYTHON` та встановіть `requirements-qa.txt`.
- `NGINX_BINARY=/path/to/nginx python3 qa/qa-nginx-security.py`: синтаксис та HTTP/TLS/Host/CSP/media/rate-limit/log-redaction на Nginx 1.30.5+. Використовуються лише локальні порти 5080, 5443, 5780 та самопідписаний QA-сертифікат.
- `npm audit --json` у `dashboard`/`miniapp`; `pip-audit -r backend/requirements-lock.txt` для зафіксованих Python-залежностей.
- `PYTHONPATH=backend:backend/qa python3 backend/qa/qa_deploy_security.py`: перевірка пароля до Docker/БД та фактичного середовища backend; Docker підмінений, production-сервіси не використовуються.
- `PYTHONPATH=backend:backend/qa python3 backend/qa/qa_deploy_health.py`: усі фази deploy.sh із підміненим Docker, доступність Nginx/API та відкат при справжній відмові маршруту.


## F16: відтворюваний повний прогін

Із кореня: `python3 -m venv backend/.qa-venv`, потім
`backend/.qa-venv/bin/pip install -r backend/requirements-lock.txt -r backend/requirements-qa.txt`.
Запуск Python + Node: `PY="$PWD/backend/.qa-venv/bin/python" bash backend/qa/run_all.sh`.
Кожен прогін створює власний каталог SQLite, який видаляється після завершення.
Шлях журналів друкується на початку. Окремі Python-набори також самі отримують
тимчасову базу; production `DATABASE_URL` не використовується стандартними сценаріями.
Тест розсилок з явним `QA_BROADCAST_DATABASE_URL` лишається винятком: це тільки
спеціально надана одноразова БД з наявним запобіжником назви.

`qa/qa_bot_text_receipts.py`: справжній dispatcher + транспорт без мережі,
120 позицій кошика, крайові HTML-назви й emoji, довгі описи, квитанції,
втрата Telegram та rollback БД. `qa/qa_isolation.py`: два одночасні процеси,
чужий файл-сентинел і очищення лише власних баз.

У `browser-ui.mjs` уже застосований перемикач `Наявність товарів` з `aria-pressed`
з етапу 2; решта F16 — повний прогін і включення всіх нових регресій у CI.
`.github/workflows/qa.yml` запускає стандартну матрицю, обидві production-збірки
та весь браузерний прогін. API/Telegram браузерних сценаріїв підмінені тестовими
відповідями; це перевірка React-інтерфейсу, а не production/VPS.
