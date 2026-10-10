"""One canonical URL and verified Telegram menu update for polling and webhook setup."""
import asyncio
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.types import MenuButtonWebApp, WebAppInfo
from shop.config import canonical_public_url


def storefront_url(public_url: str) -> str:
    base = canonical_public_url(public_url)
    return base.rstrip('/') + '/app/' if base else ''


async def sync_menu(bot, public_url: str) -> bool:
    url = storefront_url(public_url)
    if not url.startswith('https://'):
        return False
    menu = MenuButtonWebApp(text='Магазин', web_app=WebAppInfo(url=url))
    for attempt in range(3):
        try:
            await bot.set_chat_menu_button(menu_button=menu)
            actual = await bot.get_chat_menu_button()
            if not isinstance(actual, MenuButtonWebApp) or actual.web_app.url != url:
                raise RuntimeError('Telegram menu URL did not match the canonical storefront')
            return True
        except (TelegramNetworkError, TelegramServerError):
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)
        except TelegramRetryAfter as exc:
            if attempt == 2 or exc.retry_after > 30:
                raise
            await asyncio.sleep(exc.retry_after)
    return False
