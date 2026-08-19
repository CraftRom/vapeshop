"""Налаштування магазину, які редагуються з панелі.

Значення з .env лишаються дефолтами: якщо в базі нічого не збережено,
працює те саме, що й раніше. Щойно адміністратор змінює параметр у панелі,
запис іде в базу і перекриває змінну оточення.

Читання кешується на короткий час: ці значення потрібні майже в кожному
кроці бота, а тягнути їх з бази щоразу — зайва затримка й квота Firestore.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, fields
from decimal import Decimal

from shop.config import settings

# Скільки секунд довіряти закешованому значенню. У serverless процес живе
# менше, тож кеш майже не грає; на власному сервері він гарантує, що зміна
# з панелі доїде максимум за цей час.
CACHE_TTL_SECONDS = 30


@dataclass
class ShopSettings:
    """Те, що можна змінити без редеплою."""

    shop_name: str
    currency: str
    min_age: int
    referral_percent: Decimal
    bonus_max_percent: Decimal
    card_number: str
    card_holder: str

    @classmethod
    def from_env(cls) -> ShopSettings:
        return cls(
            shop_name=settings.shop_name,
            currency=settings.currency,
            min_age=settings.min_age,
            referral_percent=Decimal(str(settings.referral_percent)),
            bonus_max_percent=Decimal(str(settings.bonus_max_percent)),
            card_number=settings.card_number,
            card_holder=settings.card_holder,
        )

    def to_storage(self) -> dict[str, str]:
        """Усе зберігаємо рядками — так лягає і в SQL-таблицю, і в Firestore."""
        return {key: str(value) for key, value in asdict(self).items()}

    @classmethod
    def from_storage(cls, raw: dict[str, str]) -> ShopSettings:
        """Складає значення з бази поверх дефолтів із .env.

        Невідомі ключі ігноруються, зіпсовані числа відкидаються — інакше
        один кривий запис у базі поклав би весь бот.
        """
        base = cls.from_env()
        for f in fields(cls):
            if f.name not in raw:
                continue
            value = raw[f.name]
            try:
                if f.type is int or f.name == "min_age":
                    setattr(base, f.name, int(value))
                elif f.name in ("referral_percent", "bonus_max_percent"):
                    setattr(base, f.name, Decimal(str(value)))
                else:
                    setattr(base, f.name, str(value))
            except (ValueError, ArithmeticError):
                continue
        return base


_cache: tuple[float, ShopSettings] | None = None


def invalidate_cache() -> None:
    """Викликається після збереження, щоб зміна була видна одразу."""
    global _cache
    _cache = None


async def get_shop_settings(repo) -> ShopSettings:
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < CACHE_TTL_SECONDS:
        return _cache[1]

    try:
        raw = await repo.get_settings_map()
    except Exception:
        # Проблема з базою не має валити бота — відкочуємось до .env
        return ShopSettings.from_env()

    resolved = ShopSettings.from_storage(raw or {})
    _cache = (now, resolved)
    return resolved


async def save_shop_settings(repo, data: dict) -> ShopSettings:
    current = await get_shop_settings(repo)
    merged = ShopSettings.from_storage({**current.to_storage(), **{
        key: str(value) for key, value in data.items() if value is not None
    }})
    await repo.save_settings_map(merged.to_storage())
    invalidate_cache()
    return merged
