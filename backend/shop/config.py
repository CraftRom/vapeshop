import os
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
    admin_ids: str = ""             # "123,456" — хто має доступ до /admin у боті

    # --- Вибір бази ---
    # sql — Postgres/SQLite (власний сервер); firestore — Firebase (Vercel)
    db_backend: str = "sql"
    firebase_project: str = ""
    # Ідентифікатор бази Firestore. Порожньо — база за замовчуванням.
    firebase_database: str = ""

    # --- База (для db_backend=sql) ---
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
    cron_secret: str = ""           # Bearer-токен для /api/cron/*
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

    @field_validator("firebase_database", mode="after")
    @classmethod
    def _clean_database_id(cls, value: str) -> str:
        """Нормалізує ідентифікатор бази Firestore.

        З адреси консолі Firebase значення копіюється закодованим:
        «%28default%29» замість «(default)». Firestore такий рядок не приймає
        і відповідає «400 Invalid database id» — а падає при цьому кожен
        запит до бази, тобто застосунок цілком.

        Форми «(default)» і «default» означають базу за замовчуванням: для
        неї клієнт має отримати None, а не рядок.
        """
        if not value:
            return ""

        from urllib.parse import unquote

        cleaned = unquote(value).strip()
        if cleaned.lower() in ("(default)", "default"):
            return ""
        return cleaned


    def missing_required(self) -> list[str]:
        """Змінні, без яких магазин не працюватиме. Значень не розкриваємо."""
        problems = []
        if not self.bot_token:
            problems.append("BOT_TOKEN")
        if self.jwt_secret in ("", "change-me"):
            problems.append("JWT_SECRET")
        if self.dashboard_password in ("", "admin"):
            problems.append("DASHBOARD_PASSWORD")
        if self.db_backend == "firestore" and not self.firebase_project:
            problems.append("FIREBASE_PROJECT")
        if self.db_backend not in ("sql", "firestore"):
            problems.append("DB_BACKEND (має бути sql або firestore)")
        return problems


    def environment_report(self, runtime=None) -> list[dict]:
        """Стан змінних оточення для панелі. Значень не розкриваємо.

        Показуємо саме інфраструктуру й секрети — усе, що не редагується
        з панелі. Без цього адміністратор дізнається про незадану змінну
        лише тоді, коли щось перестане працювати, і шукатиме причину
        в логах замість одного екрана.
        """
        serverless = self.serverless
        firestore = self.db_backend == "firestore"

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
                  "Захищає службові точки: setup вебхука й запуск розсилок"),
            entry("REDIS_URL", self.redis_url, "important" if serverless else "optional",
                  "Без нього оформлення в чаті бота може обірватися на середині"),
            entry("DB_BACKEND", self.db_backend in ("sql", "firestore"), "critical",
                  "Має бути sql або firestore"),
        ]

        if firestore:
            report.append(entry("FIREBASE_PROJECT", self.firebase_project, "critical",
                                "Ідентифікатор проєкту Firestore"))
            # Найдорожча змінна в списку: невалідне значення кладе не окрему
            # функцію, а весь застосунок — кожен запит до бази йде в помилку.
            # Типова причина — значення, скопійоване з адреси консолі Firebase
            # у вигляді «%28default%29».
            raw_db = os.environ.get("FIREBASE_DATABASE", "")
            report.append(entry(
                "FIREBASE_DATABASE",
                raw_db == self.firebase_database,
                "critical",
                "Для бази за замовчуванням лишіть порожнім. "
                f"Зараз в оточенні: {raw_db!r}" if raw_db else
                "Порожньо — база за замовчуванням, це правильно",
            ))
            report.append(entry(
                "GOOGLE_APPLICATION_CREDENTIALS_JSON",
                os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
                or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
                "critical", "Ключ сервісного акаунта для доступу до бази",
            ))
        else:
            report.append(entry("DATABASE_URL", self.db_url, "critical",
                                "Адреса Postgres"))

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
