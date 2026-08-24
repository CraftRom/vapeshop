from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot import texts
from shop.config import settings
from shop.services.shop_settings import get_shop_settings
from shop.entities import User
from shop.repo.base import Repository

router = Router()


@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def cmd_start(
    message: Message, command: CommandObject | None,
    repo: Repository, user: User, state: FSMContext,
) -> None:
    await state.clear()

    # Реферальне посилання: t.me/bot?start=ABCD1234
    payload = command.args if command else None
    if payload and not user.referrer_id:
        referrer = await repo.get_user_by_referral_code(payload.strip())
        if referrer and referrer.id != user.id:
            await repo.set_user_referrer(user, referrer.id)

    if not user.age_confirmed:
        shop = await get_shop_settings(repo)
        await message.answer(texts.age_gate(shop.min_age), reply_markup=kb.age_gate())
        return

    shop = await get_shop_settings(repo)
    await message.answer(
        texts.WELCOME.format(shop=shop.shop_name), reply_markup=kb.main_menu()
    )


@router.callback_query(F.data == "age:yes")
async def age_yes(callback: CallbackQuery, repo: Repository, user: User) -> None:
    await repo.confirm_age(user)
    shop = await get_shop_settings(repo)
    await callback.message.edit_text(
        f"Дякуємо. Пам'ятайте: нікотин викликає залежність.\n"
        f"Продаж — від {shop.min_age} років."
    )
    await callback.message.answer(
        texts.WELCOME.format(shop=shop.shop_name), reply_markup=kb.main_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "age:no")
async def age_no(callback: CallbackQuery, repo: Repository) -> None:
    shop = await get_shop_settings(repo)
    await callback.message.edit_text(texts.age_denied(shop.min_age))
    await callback.answer()


@router.message(F.text == "ℹ️ Довідка")
@router.message(Command("shop", "magazin", "katalog"))
async def cmd_shop(message: Message, repo: Repository, user: User) -> None:
    """Головна команда магазину.

    Окремо від /start: /start у Telegram — це «почати спочатку», його
    натискають раз. Для повернення в магазин потрібна своя команда, яка
    видно в меню поруч із полем вводу.
    """
    shop = await get_shop_settings(repo)
    if not user.age_confirmed:
        await message.answer(texts.age_gate(shop.min_age), reply_markup=kb.age_gate())
        return
    await message.answer(
        texts.WELCOME.format(shop=shop.shop_name), reply_markup=kb.main_menu()
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP, reply_markup=kb.main_menu())


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()
