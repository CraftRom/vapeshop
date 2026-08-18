from aiogram.fsm.state import State, StatesGroup


class Checkout(StatesGroup):
    name = State()
    phone = State()
    city = State()
    address = State()
    promo = State()
    bonus = State()
    payment = State()
    comment = State()
    confirm = State()
    receipt = State()
