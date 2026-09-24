# ELFAR data lifecycle

## Мета

Основна PostgreSQL база лишається OLTP-сховищем для поточних замовлень,
клієнтів, каталогу, фінансових рухів і актуальних статусів. Дані, які ростуть
безмежно, не повинні роками залишатися у гарячих таблицях з усіма індексами.

ELFAR використовує три класи даних:

1. **Hot** — те, що активно читається/змінюється зараз.
2. **Cold** — історія, яку треба зберегти, але читають рідко.
3. **Ephemeral** — технічні/оперативні дані з обмеженим строком життя.

Окрему PostgreSQL-базу для архіву навмисно не введено. На поточному масштабі
вона дала б дві транзакції, два backup/restore контури та додаткову точку
відмови. Cold-tier зберігається атомарно в тій самій БД, але у стиснених
chunk-рядках без hot-індексів.

## Поточна політика

| Дані | Hot tier | Cold / retention |
|---|---:|---|
| Замовлення / order_items | постійно | не видаляються автоматично |
| BonusTx / PromoUsage | постійно | фінансова/аудитна історія |
| Order chat | 180 днів після terminal state | gzip-json cold archive |
| Support chat | 180 днів після закриття | gzip-json cold archive |
| Telegram attachment file_id | 3 дні після завершення | ключ доступу видаляється, текст лишається |
| Panel notifications | 90 днів | видаляються |
| Notification read-all | 1 cursor / viewer | окремі read rows тільки після cursor |
| Логи | за log retention | файловий retention |
| Автоматичні backup | за backup retention | pg_dump -Fc |

Unread chat/support ніколи не переноситься в cold-tier.

## Чому compressed cold-tier зменшує навантаження

У hot history кожне повідомлення — окремий heap row плюс кілька B-tree index
entries. Після архівації сотні рядків одного завершеного діалогу стають одним
gzip chunk. Текст не втрачається, IDs і timestamps зберігаються, а API
дочитує cold history прозоро.

Це зменшує:

- active working set PostgreSQL;
- кількість index pages для чатів;
- VACUUM/autovacuum роботу по історії;
- розмір pg_dump;
- час backup/restore;
- cache pollution від даних, які майже ніколи не читаються.

## Фізичний розмір PostgreSQL після архівації

DELETE не зобов'язаний одразу зменшити файл relation на диску. PostgreSQL
позначає сторінки як reusable і autovacuum готує їх для повторного
використання. Це нормально: наступні записи займають уже звільнений простір.

`VACUUM FULL` може фізично стиснути relation, але блокує таблицю і потребує
додаткового вільного місця під rewrite. Тому ELFAR не запускає його
автоматично. Його варто робити лише у maintenance window після дуже великого
одноразового очищення, а не як щоденну процедуру.

## Контроль росту

Sysadmin сторінка резервних копій показує:

- `pg_database_size(current_database())`;
- найбільші таблиці;
- окремо heap / index bytes;
- live/dead tuple estimates;
- кількість і payload size cold archives.

Це дозволяє приймати рішення по фактичних цифрах, а не ділити базу наперед.

## Коли вже справді потрібна окрема archive DB / object storage

Фізичне винесення cold-tier варто планувати, коли виконується хоча б одна з
умов:

- archive займає приблизно третину або більше primary DB;
- primary DB виростає до десятків GB і backup/restore перестає вкладатися в
  потрібне вікно;
- cold history створює помітний I/O pressure для checkout/orders;
- потрібні різні retention/backup SLA для бізнес-даних і листування;
- з'являється кілька PostgreSQL replicas / окремий analytics pipeline.

Тоді інтерфейс archive storage можна переключити на окремий PostgreSQL,
S3-compatible object storage або ClickHouse/warehouse для аналітики. Робити це
раніше означає платити складністю за масштаб, якого ще немає.
