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
    # Модулі лояльності. Вимкнений модуль має бути невидимим для клієнта,
    # а не просто неактивним: інакше в профілі висять нулі, а в оформленні —
    # перемикач, який нічого не робить.
    referral_enabled: bool
    referral_percent: Decimal
    bonus_enabled: bool
    bonus_max_percent: Decimal
    # Автоматична знижка за суму: від volume_discount_min дається
    # volume_discount_percent. Нульовий поріг або відсоток = модуль вимкнено.
    volume_discount_enabled: bool
    volume_discount_min: Decimal
    volume_discount_percent: Decimal
    card_number: str
    card_holder: str
    # Telegram-група
    admin_chat_id: int
    admin_ids: str
    # Бот і Mini App
    bot_username: str
    miniapp_short_name: str
    public_url: str

    @classmethod
    def from_env(cls) -> ShopSettings:
        return cls(
            shop_name=settings.shop_name,
            currency=settings.currency,
            min_age=settings.min_age,
            referral_enabled=settings.referral_enabled,
            referral_percent=Decimal(str(settings.referral_percent)),
            bonus_enabled=settings.bonus_enabled,
            bonus_max_percent=Decimal(str(settings.bonus_max_percent)),
            volume_discount_enabled=settings.volume_discount_enabled,
            volume_discount_min=Decimal(str(settings.volume_discount_min)),
            volume_discount_percent=Decimal(str(settings.volume_discount_percent)),
            card_number=settings.card_number,
            card_holder=settings.card_holder,
            admin_chat_id=settings.admin_chat_id,
            admin_ids=settings.admin_ids,
            bot_username=settings.bot_username,
            miniapp_short_name=settings.miniapp_short_name,
            public_url=settings.public_url,
        )

    def volume_discount_for(self, subtotal: Decimal) -> Decimal:
        """Автоматична знижка за суму замовлення. Нуль — якщо не діє."""
        if not self.volume_discount_enabled:
            return Decimal(0)
        if self.volume_discount_min <= 0 or self.volume_discount_percent <= 0:
            return Decimal(0)
        if subtotal < self.volume_discount_min:
            return Decimal(0)
        raw = subtotal * self.volume_discount_percent / Decimal(100)
        return min(raw.quantize(Decimal("0.01")), subtotal)

    @property
    def admin_id_list(self) -> list[int]:
        out = []
        for chunk in (self.admin_ids or "").replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk.lstrip("-").isdigit():
                out.append(int(chunk))
        return out

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
            # Тип визначаємо з анотації поля, а не з переліку імен: інакше
            # кожне нове числове налаштування мовчки лишалося б рядком
            # і падало при першому ж порівнянні
            annotation = f.type if not isinstance(f.type, str) else {
                "int": int, "bool": bool, "Decimal": Decimal, "str": str,
            }.get(f.type, str)
            try:
                if annotation is bool:
                    # У базі все рядками, тож «False» треба розпізнати явно
                    setattr(base, f.name, str(value).strip().lower()
                            in ("1", "true", "yes", "on", "так"))
                elif annotation is int:
                    setattr(base, f.name, int(value))
                elif annotation is Decimal:
                    setattr(base, f.name, Decimal(str(value)))
                else:
                    setattr(base, f.name, str(value))
            except (ValueError, ArithmeticError):
                continue
        return base


_cache: tuple[float, ShopSettings] | None = None


def invalidate_cache() -> None:
    """Скидає кеш — наступне читання піде в базу."""
    global _cache
    _cache = None


def prime_cache(value: ShopSettings) -> None:
    """Кладе свіже значення в кеш одразу після збереження.

    Просто скинути кеш замало: current() — синхронний і бази не читає, тож
    до першого асинхронного запиту він віддавав би дефолти з .env. На
    практиці це означало б, що менеджер змінив чат для замовлень у панелі,
    а бот ще якийсь час шле їх у старий.
    """
    global _cache
    _cache = (time.monotonic(), value)


def current() -> ShopSettings:
    """Останні прочитані налаштування, без звернення до бази.

    Потрібно там, де репозиторію немає: мідлвар приватності працює до його
    відкриття, а клавіатури будуються синхронно. Кеш прогрівається першим
    же запитом, тож на практиці значення свіже; до прогріву застосовуються
    дефолти з .env — рівно та поведінка, що була до появи налаштувань.
    """
    return _cache[1] if _cache else ShopSettings.from_env()


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
    prime_cache(merged)
    return merged
