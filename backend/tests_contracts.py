"""Схеми API мають збігатися з моделями даних.

Розходження тут не ловиться жодним юніт-тестом: код імпортується, тести
проходять, а падає воно аж у відповіді FastAPI — 500 у бойовій панелі.
Саме так і сталося з прапорцями модулів.
"""
import os
os.environ.update(BOT_TOKEN="1:t", JWT_SECRET="t"*32)
from dataclasses import fields as dfields

fails=[]
def check(c,l,d=""):
    print(f"  {'✓' if c else '✗'} {l}"+("" if c else f" — {d}")); (None if c else fails.append(l))

from shop.services.shop_settings import ShopSettings
from shop.entities import Order, User, Operator, OrderMessage
from api.schemas import (ShopSettingsOut, ShopSettingsIn, OrderOut, OperatorOut,
                         OrderMessageOut, CustomerOut)

def compare(schema, model, label, ignore=()):
    have={f.name for f in dfields(model)} | {p for p in dir(model) if isinstance(getattr(model,p,None),property)}
    want=set(schema.model_fields) - set(ignore)
    missing=sorted(want-have)
    check(not missing, f"{label}: усі поля схеми є в моделі", missing)

compare(ShopSettingsOut, ShopSettings, "ShopSettingsOut")
compare(ShopSettingsIn, ShopSettings, "ShopSettingsIn")
compare(OrderOut, Order, "OrderOut", ignore={"status_label"})
compare(OperatorOut, Operator, "OperatorOut")
compare(OrderMessageOut, OrderMessage, "OrderMessageOut")
compare(CustomerOut, User, "CustomerOut")

# конфіг мусить мати дефолт для кожного поля налаштувань
from shop.config import settings
missing=[f.name for f in dfields(ShopSettings) if not hasattr(settings, f.name)]
check(not missing, "у .env є дефолт для кожного налаштування", missing)

print(f"\n{'ПРОВАЛЕНО: '+str(len(fails)) if fails else 'усі контракти узгоджені'}")
