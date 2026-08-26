"""Розпізнавання питань: збіги, межі, вимкнені модулі."""
import os
os.environ.update(BOT_TOKEN="1:t", JWT_SECRET="t"*32)
from bot import faq

fails=[]
def check(c,l,d=""):
    print(f"  {'✓' if c else '✗'} {l}"+("" if c else f" — {d}")); (None if c else fails.append(l))

CASES = [
    ("Де замовити?", "order"), ("як замовити", "order"), ("Де купити", "order"),
    ("як купити ?", "order"), ("Як оформити замовлення", "order"),
    ("хочу заказать", "order"), ("где купить", "order"),
    ("скільки коштує", "price"), ("Ціна яка?", "price"), ("почому", "price"),
    ("як доставка працює", "delivery"), ("відправляєте новою поштою?", "delivery"),
    ("як оплатити", "payment"), ("накладений платіж є?", "payment"),
    ("Де моє замовлення", "status"), ("дайте ттн", "status"), ("коли прийде", "status"),
    ("можна повернути?", "returns"), ("товар бракований", "returns"), ("гарантія є", "returns"),
    ("з якого віку", "age"), ("мені 18 можна?", "age"),
    ("є промокод?", "promo"), ("які знижки", "promo"),
    ("що з бонусами", "bonus"), ("реферальна програма", "referral"),
    ("опт цікавить", "wholesale"), ("як звʼязатися з оператором", "contacts"),
    ("який графік роботи", "hours"), ("Привіт", "greeting"), ("дякую!", "thanks"),
    ("Що є в наявності", "catalog"),
]
print("--- розпізнавання ---")
for text, expected in CASES:
    got = faq.match(text)
    check(got and got.key == expected, f"«{text}» → {expected}", got and got.key)

print("\n--- бот мовчить, коли не впевнений ---")
for text in ["Відділення 12", "+380671112233", "Шевченко Тарас Григорович",
             "ок", "", "   ", "3 шт", "Іван"]:
    check(faq.match(text) is None, f"без відповіді: «{text}»", faq.match(text) and faq.match(text).key)

print("\n--- вимкнені модулі ---")
class Shop:
    bonus_enabled=False; referral_enabled=False; min_age=21
    bonus_max_percent=30; referral_percent=5; currency="грн"
check(faq.match("бонуси", Shop()) is None, "про бонуси мовчимо, коли модуль вимкнено")
check(faq.match("реферальна програма", Shop()) is None, "про рефералів так само")
class On(Shop):
    bonus_enabled=True; referral_enabled=True
check(faq.match("бонуси", On()).key == "bonus", "з увімкненим модулем відповідає")

print("\n--- підстановка даних ---")
r = faq.match("з якого віку", Shop())
check("21" in faq.render(r, Shop()), "вік береться з налаштувань", faq.render(r, Shop()))
r = faq.match("бонуси", On())
check("30" in faq.render(r, On()), "ліміт бонусів підставлено", faq.render(r, On()))

print("\n--- нормалізація ---")
check(faq.match("ЯК ЗАМОВИТИ???") is not None, "регістр і знаки")
check(faq.match("як   замовити") is not None, "зайві пробіли")
check(faq.match("🛍 як замовити") is not None, "емодзі на початку")

import sys
total = len(CASES) + 16
print(f"\nFAQ: {total - len(fails)}/{total}")
print(f"{'ПРОВАЛЕНО: '+str(len(fails)) if fails else 'усе витримано'}")
for f in fails: print("  -", f)
