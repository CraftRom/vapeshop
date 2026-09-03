from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Telegram ---
    # Без значення за замовчуванням застосунок падав ще на імпорті, і панель
    # бачила лише 500 без пояснення. Тепер він піднімається, а про брак
    # налаштувань повідомляє /api/health.
    bot_token: str = ""
    # Публічна документація API — лише для розробки: вона розкриває
    # повну карту адмінських маршрутів будь-кому.
    enable_api_docs: bool = False
    bot_username: str = "your_shop_bot"
    # Коротка назва Mini App із BotFather (/newapp). Без неї пряме
    # посилання на вітрину побудувати неможливо — лишиться тільки кнопка.
    miniapp_short_name: str = ""
    admin_chat_id: int = 0          # куди падають нові замовлення
    # Номер гілки в адмінському каналі для замовлень. 0 — загальна стрічка.
    # --- Доставка й оплата ---
    # Цифри перевізника. Змінюються не нами, тож лежать у налаштуваннях,
    # а не в текстах: інакше після підвищення тарифу довелося б шукати
    # їх по всьому проєкту.
    delivery_cost_from: int = 80
    delivery_days: str = "1–3 дні"
    cod_commission_percent: float = 2.0
    cod_commission_fixed: float = 20.0
    # Ключ API Нової пошти. Дефолт порожній: без нього форма замовлення
    # працює як раніше — місто й відділення вписуються руками.
    novaposhta_api_key: str = ""

    admin_topic_id: int = 0
    # Гілка для помилок сервера, бота й планувальника. Окремо від замовлень:
    # менеджер не має продиратись крізь трейсбеки, а системний
    # адміністратор — крізь замовлення.
    # Гілка для повідомлень клієнтів із чату замовлення. Окремо від
    # самих замовлень: замовлення читають раз, а переписку ведуть далі,
    # і в спільній стрічці нові замовлення тонули б у відповідях.
    chat_topic_id: int = 0
    error_topic_id: int = 0
    admin_ids: str = ""             # "123,456" — хто має доступ до /admin у боті


    # --- Розсилки й планувальник ---
    # Дефолти; редагуються з панелі й перекриваються значеннями з бази.
    timezone: str = "Europe/Kyiv"
    broadcast_rate_per_second: int = 25
    quiet_hours_enabled: bool = True
    quiet_hours_start: int = 22
    quiet_hours_end: int = 9
    broadcast_chunk: int = 100
    # Як часто планувальник перевіряє чергу, у секундах. Година — компроміс
    # між точністю запуску й навантаженням на базу.
    scheduler_interval_seconds: int = 3600

    # --- Обслуговування сервера ---
    backup_enabled: bool = True
    backup_hour: int = 4
    backup_retention_days: int = 14
    log_retention_days: int = 30

    # --- Журнал ---
    # Ті самі значення читає shop/logging_setup.py напряму з оточення.
    # Дублювання навмисне: логування налаштовується найпершим, ще до збірки
    # налаштувань — інакше помилку самої конфігурації нікуди було б записати.
    # Куди лягають завантажені зображення. Той самий каталог віддає nginx
    # за адресою /media/ — застосунок у роздачі не бере участі.
    log_json: bool = True
    log_level: str = "INFO"

    # --- База ---
    # Розмір пулу зʼєднань. Один воркер тримає стільки паралельних
    # запитів до бази; решта чекає. Значення підібране під VPS із 2–4 ГБ,
    # де поруч живуть бот і планувальник зі своїми пулами.
    db_pool_size: int = 10
    db_pool_overflow: int = 20
    # DATABASE_URL можна не задавати — тоді збереться з POSTGRES_*.
    # Так пароль БД зберігається в одному місці й не розходиться.
    postgres_user: str = "shop"
    postgres_password: str = "shop"
    postgres_db: str = "shop"
    postgres_host: str = "db"
    postgres_port: int = 5432
    database_url: str | None = None

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        # quote — інакше пароль зі спецсимволами (@ : / #) ламає рядок підключення
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # --- Режим роботи ---
    # serverless=true вимикає пул з'єднань (Vercel створює процес на запит)
    serverless: bool = False
    public_url: str = ""            # https://your-app.vercel.app — для вебхука
    webhook_secret: str = ""        # секрет у шляху вебхука, згенеруйте випадковий
    cron_secret: str = ""           # Bearer-токен для службових точок (setup вебхука)
    redis_url: str = ""             # якщо задано — FSM переживає рестарт бота

    # --- Дашборд ---
    jwt_secret: str = "change-me"
    jwt_ttl_hours: int = 12
    dashboard_login: str = "admin"
    dashboard_password: str = "admin"   # змінити при першому запуску
    cors_origins: str = "http://localhost:5173"

    # --- Магазин ---
    shop_name: str = "Lux Opt"
    currency: str = "грн"
    min_age: int = 18
    referral_enabled: bool = True
    bonus_enabled: bool = True
    volume_discount_enabled: bool = False
    volume_discount_min: float = 0
    volume_discount_percent: float = 0
    referral_percent: float = 5.0       # % від суми замовлення рефералу
    bonus_max_percent: float = 30.0     # макс. частка замовлення, яку можна закрити бонусами
    card_number: str = "0000 0000 0000 0000"
    card_holder: str = ""

    # Реквізити продавця для юридичних документів вітрини.
    # Без них оферта й політика обробки даних не мають сили, тому вітрина
    # показує попередження, поки поля порожні.
    seller_name: str = ""
    seller_code: str = ""
    seller_address: str = ""
    seller_email: str = ""
    seller_phone: str = ""

    @model_validator(mode="before")
    @classmethod
    def _ignore_empty_values(cls, data):
        """Порожня змінна оточення = не задана.

        Інтерфейс Vercel дозволяє створити змінну без значення, і тоді сюди
        приходить '' — для int/float/bool це помилка валідації, яка валить
        застосунок ще на імпорті. Для таких полів порожнє значення просто
        відкидаємо, щоб застосувався дефолт. Рядкові поля не чіпаємо: для них
        '' — легітимне значення (напр. порожній CARD_HOLDER).
        """
        if not isinstance(data, dict):
            return data

        cleaned = {}
        for key, value in data.items():
            field = cls.model_fields.get(key)
            if value == "" and field is not None and field.annotation is not str:
                continue
            cleaned[key] = value
        return cleaned

    @field_validator("dashboard_login", "dashboard_password", mode="after")
    @classmethod
    def _strip_credentials(cls, value: str) -> str:
        """Знімає зайві пробіли й лапки, які легко лишити в .env.

        DASHBOARD_PASSWORD="secret" і DASHBOARD_PASSWORD=secret мають
        працювати однаково — інакше причину невдалого входу не видно очима.
        """
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.split(",") if x.strip()]

    @property
    def cors_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


    @model_validator(mode="before")
    @classmethod
    def _trim_pasted_values(cls, data):
        """Прибирає сміття, яке чіпляється при копіюванні значень.

        Змінні оточення заповнюють вручну: копіюють токен із BotFather,
        адресу з панелі хостингу, ідентифікатор із консолі. Разом зі
        значенням приїжджають пробіли, лапки з .env-файлу, слеш на кінці
        адреси. Кожен такий символ дає збій, у якому значення виглядає
        правильним — а помилка вилазить десь далеко, як «невірний токен»
        або «база не знайдена».
        """
        if not isinstance(data, dict):
            return data

        cleaned = {}
        for key, value in data.items():
            if isinstance(value, str):
                value = value.strip().strip('"').strip("'").strip()
            cleaned[key] = value
        return cleaned


    @field_validator("public_url", mode="after")
    @classmethod
    def _clean_url(cls, value: str) -> str:
        # Слеш на кінці подвоївся б при склеюванні шляхів: «//app/»
        return value.rstrip("/") if value else value

    @field_validator("bot_username", "miniapp_short_name", mode="after")
    @classmethod
    def _clean_handle(cls, value: str) -> str:
        # «@bot» і «/app» копіюють просто з адреси або з профілю
        return value.lstrip("@").strip("/") if value else value

    def missing_required(self) -> list[str]:
        """Змінні, без яких магазин не працюватиме. Значень не розкриваємо."""
        problems = []
        if not self.bot_token:
            problems.append("BOT_TOKEN")
        if self.jwt_secret in ("", "change-me"):
            problems.append("JWT_SECRET")
        if self.dashboard_password in ("", "admin"):
            problems.append("DASHBOARD_PASSWORD")
        if not self.db_url:
            problems.append("DATABASE_URL")
        return problems


    def environment_report(self, runtime=None) -> list[dict]:
        """Стан змінних оточення для панелі. Значень не розкриваємо.

        Показуємо саме інфраструктуру й секрети — усе, що не редагується
        з панелі. Без цього адміністратор дізнається про незадану змінну
        лише тоді, коли щось перестане працювати, і шукатиме причину
        в логах замість одного екрана.
        """
        serverless = self.serverless

        # Частина значень задається і в оточенні, і в панелі; панель має
        # пріоритет. Без цього адміністратор, який заповнив адресу сайту
        # в налаштуваннях, бачив би тут «не задано» і шукав неіснуючу проблему.
        def effective(name):
            value = getattr(runtime, name, None) if runtime is not None else None
            return value or getattr(self, name)

        def entry(key, ok, level, note):
            return {"key": key, "ok": bool(ok), "level": level, "note": note}

        report = [
            entry("BOT_TOKEN", self.bot_token, "critical",
                  "Без нього бот не працює зовсім"),
            entry("JWT_SECRET", self.jwt_secret not in ("", "change-me"), "critical",
                  "Дефолтне значення означає, що вхід у панель можна підробити"),
            entry("DASHBOARD_PASSWORD", self.dashboard_password not in ("", "admin"), "critical",
                  "Дефолтний пароль відомий будь-кому"),
            entry("WEBHOOK_SECRET", self.webhook_secret, "critical" if serverless else "optional",
                  "Адреса, на яку Telegram шле оновлення. Потрібен у serverless"),
            entry("Адреса сайту", str(effective("public_url")).startswith("https://"), "critical",
                  "Обовʼязково https і точний домен. Редагується в налаштуваннях"),
            entry("Юзернейм бота",
                  effective("bot_username") and effective("bot_username") != "your_shop_bot",
                  "important", "Потрібен для кнопки переходу з групи в особистий чат"),
            entry("Коротка назва Mini App", effective("miniapp_short_name"), "important",
                  "Без неї реферальні посилання не відкривають вітрину напряму"),
            entry("CRON_SECRET", self.cron_secret, "important",
                  "Захищає службові точки: setup і видалення вебхука"),
            entry("REDIS_URL", self.redis_url, "important" if serverless else "optional",
                  "Без нього оформлення в чаті бота може обірватися на середині"),
        ]

        report.append(entry("DATABASE_URL", self.db_url, "critical",
                            "Адреса Postgres"))
        from shop.logging_setup import resolve_level

        _level, _bad = resolve_level(self.log_level)
        report.append(entry(
            "LOG_LEVEL", not _bad, "important",
            f"Рівень журналу: {self.log_level} ({_level})" if not _bad else
            f"Невідомий рівень {self.log_level!r} — діє INFO. "
            "Доступні: NOTSET, DEBUG, INFO, WARNING, ERROR, CRITICAL або число 0–100",
        ))

        report.append(entry("ADMIN_CHAT_ID", self.admin_chat_id, "important",
                            "Чат, куди падають нові замовлення. Задається й у панелі"))
        return report

    def environment_problems(self) -> list[dict]:
        """Лише те, що справді потребує уваги."""
        return [e for e in self.environment_report()
                if not e["ok"] and e["level"] != "optional"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
