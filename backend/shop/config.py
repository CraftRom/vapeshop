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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
