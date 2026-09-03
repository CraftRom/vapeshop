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
    # Реквізити продавця для оферти й політики обробки даних
    seller_name: str
    seller_code: str
    seller_address: str
    seller_email: str
    seller_phone: str
    # Telegram-група
    admin_chat_id: int
    # Гілки форуму в адмінському каналі. 0 — писати в загальну стрічку.
    #
    # У каналі з темами повідомлення без message_thread_id падають у
    # «General», де їх ніхто не читає. Розділення потрібне ще й тому, що
    # замовлення й помилки сервера — різні за терміновістю потоки.
    # Умови доставки й оплати. Тримаємо тут, а не в текстах: ці цифри
    # міняє перевізник, і правити їх у трьох місцях — гарантія, що
    # десь лишиться стара.
    delivery_cost_from: int
    delivery_days: str
    cod_commission_percent: Decimal
    cod_commission_fixed: Decimal
    # Ключ до довідника Нової пошти. Єдине налаштування, яке не читається
    # назад: панель бачить лише ознаку «підключено» (novaposhta_connected).
    novaposhta_api_key: str
    novaposhta_sender_city: str
    delivery_weight_per_item: Decimal

    admin_topic_id: int
    chat_topic_id: int
    error_topic_id: int
    admin_ids: str
    # Бот і Mini App
    bot_username: str
    miniapp_short_name: str
    public_url: str
    # Скільки годин живе вхід у панель. Політика, а не інфраструктура,
    # тож місце їй тут, а не в змінних оточення
    jwt_ttl_hours: int

    # --- Розсилки ---
    # Часовий пояс, у якому адміністратор задає час запуску й тихі години.
    # Зберігається як назва зони IANA, а не зсув: зсув ламається двічі на рік
    # на переході, і розсилка о 9:00 поїхала б на 8:00.
    timezone: str
    # Швидкість відправки. Telegram ріже приблизно на 30 повідомленнях за
    # секунду; менше значення — довша розсилка, але менший ризик 429.
    broadcast_rate_per_second: int
    # Тихі години: у цей проміжок розсилки не йдуть, дозрілі чекають ранку.
    # Рівні значення = тихих годин немає.
    quiet_hours_enabled: bool
    quiet_hours_start: int
    quiet_hours_end: int

    # --- Сервер ---
    # Нічний дамп бази. Робить планувальник — окремий cron на хості не
    # потрібен, і бекап не залежить від того, чи не зламався crontab.
    backup_enabled: bool
    backup_hour: int
    backup_retention_days: int
    # Скільки днів тримати файли логів застосунку
    log_retention_days: int
    # Верхня межа на порцію розсилки за один прохід
    broadcast_chunk: int

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
            seller_name=settings.seller_name,
            seller_code=settings.seller_code,
            seller_address=settings.seller_address,
            seller_email=settings.seller_email,
            seller_phone=settings.seller_phone,
            admin_chat_id=settings.admin_chat_id,
            delivery_cost_from=settings.delivery_cost_from,
            delivery_days=settings.delivery_days,
            cod_commission_percent=Decimal(str(settings.cod_commission_percent)),
            cod_commission_fixed=Decimal(str(settings.cod_commission_fixed)),
            novaposhta_api_key=settings.novaposhta_api_key,
            novaposhta_sender_city=settings.novaposhta_sender_city,
            delivery_weight_per_item=Decimal(str(settings.delivery_weight_per_item)),
            admin_topic_id=settings.admin_topic_id,
            chat_topic_id=settings.chat_topic_id,
            error_topic_id=settings.error_topic_id,
            admin_ids=settings.admin_ids,
            bot_username=settings.bot_username,
            miniapp_short_name=settings.miniapp_short_name,
            public_url=settings.public_url,
            jwt_ttl_hours=settings.jwt_ttl_hours,
            timezone=settings.timezone,
            broadcast_rate_per_second=settings.broadcast_rate_per_second,
            quiet_hours_enabled=settings.quiet_hours_enabled,
            quiet_hours_start=settings.quiet_hours_start,
            quiet_hours_end=settings.quiet_hours_end,
            backup_enabled=settings.backup_enabled,
            backup_hour=settings.backup_hour,
            backup_retention_days=settings.backup_retention_days,
            log_retention_days=settings.log_retention_days,
            broadcast_chunk=settings.broadcast_chunk,
        )

    @property
    def novaposhta_connected(self) -> bool:
        """Чи заданий ключ. Саме це, а не сам ключ, бачить панель.

        Секрет, який віддається назад, рано чи пізно опиняється в журналі
        браузера, у скріншоті підтримки або в кеші проксі. Ознаки досить,
        щоб зрозуміти стан: підключено чи ні.
        """
        return bool((self.novaposhta_api_key or "").strip())

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
    def tz(self):
        """Обʼєкт часової зони. Незнайома назва не має валити розсилку."""
        from datetime import timezone as _utc
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            return ZoneInfo(self.timezone or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            return _utc.utc

    def in_quiet_hours(self, moment) -> bool:
        """Чи потрапляє момент у тихі години (за часом магазину).

        Проміжок може перетинати північ — 22→8 означає «з десятої вечора до
        восьмої ранку», і саме цей випадок на практиці і потрібен.
        """
        if not self.quiet_hours_enabled:
            return False
        start, end = self.quiet_hours_start, self.quiet_hours_end
        if start == end:
            return False
        hour = moment.astimezone(self.tz).hour
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def next_active_moment(self, moment):
        """Найближчий час, коли розсилати вже можна."""
        if not self.in_quiet_hours(moment):
            return moment
        local = moment.astimezone(self.tz)
        target = local.replace(hour=self.quiet_hours_end, minute=0, second=0, microsecond=0)
        if target <= local:
            from datetime import timedelta

            target += timedelta(days=1)
        return target.astimezone(moment.tzinfo) if moment.tzinfo else target

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

    # Зміна ключа знецінює все, що вже привезли старим. Інакше магазин
    # ще півдоби показував би відповіді, отримані попереднім ключем, і
    # той, хто щойно вписав новий, вирішив би, що він не спрацював.
    if current.novaposhta_api_key != merged.novaposhta_api_key:
        from shop.services import novaposhta

        novaposhta.reset_cache()
    return merged
