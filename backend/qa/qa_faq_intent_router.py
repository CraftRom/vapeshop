"""Консервативний FAQ intent-router: відповідає лише коли готовий текст справді релевантний."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.update(BOT_TOKEN="1:t", JWT_SECRET="t" * 32)

from bot import faq  # noqa: E402

fails: list[str] = []
checks = 0


def check(cond: bool, label: str, detail=""):
    global checks
    checks += 1
    print(f"  {'✓' if cond else '✗'} {label}" + ("" if cond else f" — {detail}"))
    if not cond:
        fails.append(label)


class Shop:
    bonus_enabled = True
    referral_enabled = True
    min_age = 18
    bonus_max_percent = 30
    referral_percent = 5
    currency = "грн"
    delivery_days = "1–3 дні"
    delivery_cost_from = 80
    delivery_courier_enabled = False
    cod_commission_percent = 2
    cod_commission_fixed = 20


shop = Shop()

print("--- конкретний намір сильніший за побічні слова ---")
for text, expected in (
    ("Привіт, як оплатити?", "payment"),
    ("Дякую, а де моя накладна?", "status"),
    ("Як оформити замовлення", "order"),
    ("Як доставка працює?", "delivery"),
    ("Дайте ТТН", "status"),
    ("Що є в наявності?", "catalog"),
):
    d = faq.decide(text, shop=shop)
    check(d.rule is not None and d.rule.key == expected,
          f"{text!r} → {expected}", f"{d.rule.key if d.rule else None} / {d.reason}")

print("\n--- кейс зі скріну та персональні умови йдуть менеджеру ---")
for text in (
    "Як мені отримати промокод, я завжди замовляю тільки у вас?",
    "Є промокод?",
    "Промокод є для постійних клієнтів?",
    "Де взяти промокод?",
    "Дайте промокод будь ласка",
    "Для постійних клієнтів знижка є?",
    "Скиньте ціну",
    "Можна персональну знижку?",
):
    d = faq.decide(text, shop=shop)
    check(d.rule is None, f"не вгадує персональну promo-відповідь: {text!r}", d.reason)

print("\n--- готова promo-відповідь використовується лише у своєму scope ---")
for text in (
    "Де вводити промокод?",
    "Як використати промокод?",
    "Куди ввести промокод?",
    "Які зараз знижки?",
):
    d = faq.decide(text, shop=shop)
    check(d.rule is not None and d.rule.key == "promo",
          f"promo FAQ доречний: {text!r}", d.reason)

print("\n--- проблема/помилка не маскується статичною довідкою ---")
for text in (
    "Промокод не працює",
    "Не можу оплатити",
    "Не виходить оформити замовлення",
    "Оплата не проходить",
    "Не застосовується знижка",
):
    d = faq.decide(text, shop=shop)
    check(d.rule is None, f"problem → менеджер: {text!r}", d.reason)

# Дефект товару — виняток: existing returns-відповідь якраз пояснює, що робити.
for text in ("Не заряджається", "Протікає", "Прислали не те"):
    d = faq.decide(text, shop=shop)
    check(d.rule is not None and d.rule.key == "returns",
          f"товарна проблема має готовий returns flow: {text!r}", d.reason)

print("\n--- дані замовлення не плутаються з питанням ---")
for text in (
    "Нова пошта, відділення 12",
    "Накладений платіж",
    "Картка монобанк",
    "Нова пошта 7",
):
    d = faq.decide(text, shop=shop)
    check(d.rule is None, f"транзакційні дані → менеджер: {text!r}", d.reason)

for text, expected in (
    ("Новою поштою відправляєте?", "delivery"),
    ("Накладений платіж можна?", "payment"),
    ("Як оплатити карткою?", "payment"),
):
    d = faq.decide(text, shop=shop)
    check(d.rule is not None and d.rule.key == expected,
          f"питання лишається FAQ: {text!r}", d.reason)

print("\n--- multi-intent не отримує половину відповіді ---")
for text in (
    "Як оплатити і яка доставка?",
    "Яка доставка і чи є повернення?",
    "Скільки коштує і як оплатити?",
):
    d = faq.decide(text, shop=shop)
    check(d.rule is None and d.reason == "confidence:multi-intent",
          f"кілька незалежних питань → менеджер: {text!r}", d.reason)

print("\n--- побутовий шум не запускає FAQ ---")
for text in (
    "Новинки кіно дивились",
    "Менеджер обіцяв написати",
    "Не хочу замовляти",
    "Ок, зрозумів",
    "Завтра Нова пошта працює біля дому",
):
    d = faq.decide(text, shop=shop)
    check(d.rule is None, f"шум/контекст не перехоплено: {text!r}", d.reason)

print("\n--- conversation context: менеджер і повтори мають пріоритет ---")
now = datetime.now(timezone.utc)
manager_history = [
    SimpleNamespace(id=1, direction="out", author="elfarmanager", text="Відповідь", is_automatic=False,
                    created_at=now - timedelta(minutes=5)),
    SimpleNamespace(id=2, direction="in", author="Наталя", text="Як оплатити?", is_automatic=False,
                    created_at=now),
]
ctx = faq.context_from_history(manager_history, shop=shop, current_message_id=2, now=now)
check(ctx.human_active, "недавня відповідь менеджера вмикає human takeover")
d = faq.decide("Як оплатити?", shop=shop, context=ctx)
check(d.rule is None and d.reason == "context:human-active",
      "FAQ не встряє в активну розмову менеджера", d.reason)

promo_rule = next(r for r in faq.RULES if r.key == "payment")
auto_text = faq.render(promo_rule, shop)
auto_history = [
    SimpleNamespace(id=10, direction="out", author="Бот", text=auto_text, is_automatic=True,
                    created_at=now - timedelta(minutes=15)),
    SimpleNamespace(id=11, direction="in", author="Наталя", text="Як оплатити?", is_automatic=False,
                    created_at=now),
]
ctx = faq.context_from_history(auto_history, shop=shop, current_message_id=11, now=now)
check("payment" in ctx.recent_auto_keys, "попередня FAQ-тема відновлюється з історії")
d = faq.decide("Як оплатити?", shop=shop, context=ctx)
check(d.rule is None and d.reason == "context:repeat",
      "однакову довідку не повторюємо — питання піде менеджеру", d.reason)

old_manager = [
    SimpleNamespace(id=20, direction="out", author="elfarmanager", text="Відповідь", is_automatic=False,
                    created_at=now - timedelta(hours=2)),
]
ctx = faq.context_from_history(old_manager, shop=shop, now=now)
check(not ctx.human_active, "старий діалог не блокує FAQ назавжди")

print("\n--- короткі follow-up без контекстного вгадування ---")
for text in ("А де?", "А як?", "Куди саме?"):
    d = faq.decide(text, shop=shop)
    check(d.rule is None and d.reason == "context:short-followup",
          f"короткий follow-up → менеджер: {text!r}", d.reason)

print("\n--- wiring: smart decision реально використовується у потоках ---")
root = Path(__file__).resolve().parents[1]
handler = (root / "bot/handlers/chat.py").read_text()
repo_src = (root / "shop/repo/sql.py").read_text()
check("decision = faq.decide(text, shop=shop, context=context)" in handler,
      "support handler використовує context-aware decide()")
check("has_attachment=True" in handler,
      "caption вкладення не запускає FAQ")
check("_order_faq_context" in handler and "context.human_active" in handler,
      "order chat має human takeover")
check("async def recent_support_messages" in repo_src and ".order_by(m.SupportMessage.id.desc())" in repo_src,
      "support context читає лише останні hot messages")
check("rule = faq.match(text, shop)" not in handler,
      "старий first-match шлях прибрано з приватного chat handler")

print(f"\nSMART FAQ ROUTER: {checks - len(fails)}/{checks}")
if fails:
    print("ПРОВАЛЕНО:", len(fails))
    for item in fails:
        print(" -", item)
    raise SystemExit(1)
print("усе витримано")
