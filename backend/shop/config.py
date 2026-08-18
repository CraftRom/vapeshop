from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Telegram ---
    bot_token: str
    bot_username: str = "your_shop_bot"
    admin_chat_id: int = 0          # куди падають нові замовлення
    admin_ids: str = ""             # "123,456" — хто має доступ до /admin у боті

    # --- База ---
    database_url: str = "postgresql+asyncpg://shop:shop@db:5432/shop"

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
    referral_percent: float = 5.0       # % від суми замовлення рефералу
    bonus_max_percent: float = 30.0     # макс. частка замовлення, яку можна закрити бонусами
    card_number: str = "0000 0000 0000 0000"
    card_holder: str = ""

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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
