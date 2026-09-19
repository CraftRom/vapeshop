"""FAQ доставки не обіцяє покупцеві вимкненого курʼєра."""
from bot import faq

fails: list[str] = []
checks = 0


def check(condition: bool, label: str, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  {'✓' if condition else '✗'} {label}" + ("" if condition else f" — {detail}"))
    if not condition:
        fails.append(label)


class BaseShop:
    min_age = 18
    bonus_enabled = True
    referral_enabled = True
    bonus_max_percent = 30
    referral_percent = 5
    currency = "грн"
    delivery_days = "2–4 дні"
    delivery_cost_from = 95
    cod_commission_percent = 2
    cod_commission_fixed = 20
    delivery_courier_enabled = False


class CourierShop(BaseShop):
    delivery_courier_enabled = True


def rule(key: str):
    return next(item for item in faq.RULES if item.key == key)


print("--- FAQ доставки з налаштувань ---")
off = BaseShop()
on = CourierShop()

delivery_off = faq.render(rule("delivery"), off)
delivery_on = faq.render(rule("delivery"), on)
check("• у відділення Нової пошти" in delivery_off,
      "відділення завжди показується")
check("курʼєр" not in delivery_off.lower(),
      "вимкнений курʼєр не згадується у приватній відповіді", delivery_off)
check("• адресна доставка курʼєром Нової пошти" in delivery_on,
      "увімкнений курʼєр додається окремим пунктом", delivery_on)
check("2–4 дні" in delivery_on and "95 грн" in delivery_on,
      "строк і мінімальна вартість теж беруться з налаштувань", delivery_on)

public_off = faq.render(rule("delivery"), off, public=True)
public_on = faq.render(rule("delivery"), on, public=True)
check("курʼєр" not in public_off.lower(),
      "групова автовідповідь не рекламує вимкненого курʼєра", public_off)
check("адресно курʼєром" in public_on.lower(),
      "групова автовідповідь знає про увімкненого курʼєра", public_on)

payment_off = faq.render(rule("payment"), off)
payment_on = faq.render(rule("payment"), on)
check("або курʼєру" not in payment_off.lower(),
      "накладений платіж без курʼєра описує лише відділення", payment_off)
check("у відділенні або курʼєру" in payment_on.lower(),
      "накладений платіж адаптується до курʼєрської доставки", payment_on)

order_off = faq.render(rule("order"), off)
order_on = faq.render(rule("order"), on)
check("піб, телефон і відділення нової пошти" in order_off.lower(),
      "оформлення без курʼєра просить відділення", order_off)
check("курʼєр" not in order_off.lower(),
      "оформлення без курʼєра не створює хибного вибору", order_off)
check("оберіть спосіб доставки" in order_on.lower() and "курʼєром" in order_on.lower(),
      "оформлення з курʼєром пояснює реальний вибір", order_on)

# Без нового поля старий ShopSettings/тестовий обʼєкт поводиться безпечно:
# курʼєр вимкнений, а не вважається доступним за замовчуванням.
class LegacyShop:
    currency = "грн"

legacy = faq.render(rule("delivery"), LegacyShop())
check("курʼєр" not in legacy.lower(),
      "для старих налаштувань дефолт fail-closed", legacy)

print(f"\nDYNAMIC DELIVERY FAQ: {checks - len(fails)}/{checks}")
if fails:
    print(f"ПРОВАЛЕНО: {len(fails)}")
    raise SystemExit(1)
print("усе витримано")
