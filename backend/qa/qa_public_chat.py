"""ПУБЛІЧНІ ЧАТИ: що бот каже в групі, а що лишає приватним."""
import os
import sys

sys.path.insert(0, "/tmp")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  BOT_USERNAME="elfar1_bot",
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_public.db")

from qa_common import Report                      # noqa: E402

r = Report("ПУБЛІЧНІ ЧАТИ")

from bot import faq, texts                        # noqa: E402
from bot.greeting import (                        # noqa: E402
    PRIVATE_ONLY_COMMANDS, PUBLIC_COMMANDS,
    is_command_trigger, is_private_only_command,
)
from bot.middlewares import PUBLIC_COOLDOWN, _may_speak, _last_fallback  # noqa: E402
from shop.services.shop_settings import ShopSettings  # noqa: E402


# --------------------------------------------------------------- команди

print("\n--- /shop працює в групі ---")
for text in ("/shop", "/shop@elfar1_bot", "/SHOP", "  /shop  ", "/shop покажи"):
    r.check(is_command_trigger(text), f"публічна команда: {text!r}")

print("\n--- /start у групі мовчить ---")
for text in ("/start", "/start@elfar1_bot", "/START", "/start ref_123"):
    r.check(not is_command_trigger(text), f"не відповідає на {text!r}")
    r.check(is_private_only_command(text), f"розпізнано як приватну: {text!r}")

print("\n--- інші приватні команди теж мовчать ---")
for text in ("/cart", "/profile", "/orders", "/magazin"):
    r.check(not is_command_trigger(text), f"не публічна: {text}")
    r.check(is_private_only_command(text), f"приватна: {text}")

r.check("/start" not in PUBLIC_COMMANDS, "/start не в переліку публічних")
r.check("/shop" in PUBLIC_COMMANDS, "/shop у переліку публічних")
r.check("/start" in PRIVATE_ONLY_COMMANDS, "/start у переліку приватних")

print("\n--- випадковий текст не збуджує бота ---")
for text in ("привіт усім", "хтось брав тут щось?", "shop", "старт", ""):
    r.check(not is_command_trigger(text), f"мовчить на {text!r}")


# ------------------------------------------------------ захист від спаму

shop = ShopSettings.from_env()

print("\n--- відпочинок між відповідями ---")
_last_fallback.clear()
r.check(_may_speak(-100500, "delivery"), "перша відповідь проходить")
r.check(not _may_speak(-100500, "delivery"), "друга поспіль на ту саму тему — ні")
r.check(not _may_speak(-100500, "delivery"), "третя теж ні")
r.check(_may_speak(-100500, "payment"), "інша тема не заблокована сусідньою")
r.check(_may_speak(-100777, "delivery"), "інший чат не заблокований сусіднім")
r.check(PUBLIC_COOLDOWN >= 60, f"пауза не символічна: {PUBLIC_COOLDOWN} с")

_last_fallback[(-100500, "delivery")] -= PUBLIC_COOLDOWN + 1
r.check(_may_speak(-100500, "delivery"), "після паузи бот знову відповідає")

print("\n--- ключові слова працюють без згадки ---")
# Саме те, чого бракувало: у групі бот мовчав, поки його не покличуть.
for question in ("яка доставка", "як оплатити", "як зробити замовлення",
                 "з якого віку", "де каталог"):
    rule = faq.match(question, shop, public=True)
    r.check(rule is not None, f"є відповідь на {question!r} без згадки",
            rule.key if rule else None)

print("\n--- у групі відповідь стисліша ---")
shortened = 0
for rule in faq.RULES:
    if not rule.public:
        continue
    group_text = faq.render(rule, shop, public=True)
    private_text = faq.render(rule, shop)
    r.check(len(group_text) <= len(private_text),
            f"{rule.key}: групова не довша за приватну",
            (len(group_text), len(private_text)))
    if len(group_text) < len(private_text):
        shortened += 1
r.check(shortened >= 4, f"скорочено правил: {shortened}")

print("\n--- стислі варіанти нікого не викривають ---")
for rule in faq.RULES:
    if not rule.public or not rule.public_answer:
        continue
    body = faq.render(rule, shop, public=True).lower()
    r.check("№" not in body and "t.me/" not in body,
            f"{rule.key}: без номерів і посилань")


# ------------------------------------------------- персональне не витікає

print("\n--- у публічний чат ідуть лише загальні правила ---")

public_rules = [rule for rule in faq.RULES if rule.public]
private_rules = [rule for rule in faq.RULES if not rule.public]
r.check(public_rules, f"публічних правил: {len(public_rules)}")
r.check(private_rules, f"приватних правил: {len(private_rules)}")

# Жодне публічне правило не має тягнути персональні дані
PERSONAL_MARKERS = ("бонус", "реферал", "ваше замовлення", "ваш кошик",
                    "ваші бали", "статус замовлення")
leaks = []
for rule in public_rules:
    body = faq.render(rule, shop).lower()
    for marker in PERSONAL_MARKERS:
        if marker in body and "потрібен" not in body:
            leaks.append((rule.groups, marker))
r.check(not leaks, "жодне публічне правило не згадує персональних даних", leaks[:3])

print("\n--- питання про чуже замовлення не отримує відповіді в групі ---")
for question in ("де моє замовлення", "який статус мого замовлення",
                 "скільки в мене бонусів", "дай реферальне посилання",
                 "я замовляв учора, коли прийде"):
    rule = faq.match(question, shop, public=True)
    r.check(rule is None, f"мовчить у групі: {question!r}",
            rule.groups if rule else None)
    # А в приватному чаті відповідь має бути
    private_rule = faq.match(question, shop, public=False)
    r.check(private_rule is not None, f"але відповідає приватно: {question!r}")

print("\n--- загальні питання відповідаються і там, і там ---")
for question in ("як оплатити", "яка доставка", "як зробити замовлення"):
    public_rule = faq.match(question, shop, public=True)
    r.check(public_rule is not None, f"відповідає в групі: {question!r}")

print("\n--- текст переадресації нікого не викриває ---")
fallback = texts.PUBLIC_FALLBACK.lower()
for forbidden in ("замовлення №", "http://", "t.me/", "@"):
    r.check(forbidden not in fallback,
            f"у переадресації немає {forbidden!r}")
r.check(len(texts.PUBLIC_FALLBACK) < 300, "переадресація коротка")

# ------------------------------------------------- адмінський чат не всеїдний

print("\n--- щілина для персоналу вузька ---")
from bot.middlewares import PrivateOnlyMiddleware      # noqa: E402

mw = PrivateOnlyMiddleware
r.check("/stats" in mw.ADMIN_COMMANDS, "/stats дозволений персоналу")
r.check("ao:" in mw.ADMIN_CALLBACKS, "кнопки статусу замовлень дозволені")

# Найважливіше: у щілину не має пролізти нічого зайвого. Саме через широкий
# виняток бот відповідав у групі на випадковий набір літер.
for forbidden in ("/start", "/cart", "/profile", "/orders", "/shop"):
    r.check(forbidden not in mw.ADMIN_COMMANDS,
            f"{forbidden} не проходить як адмінська команда")
for forbidden in ("chat:", "faq:", "age:", "cart:"):
    r.check(forbidden not in mw.ADMIN_CALLBACKS,
            f"кнопка {forbidden} не проходить як адмінська")

r.check(len(mw.ADMIN_COMMANDS) <= 3,
        f"перелік команд короткий: {mw.ADMIN_COMMANDS}")

print("\n--- випадковий текст в адмінському чаті ---")
# Те, що бачив користувач на скріншоті: «Члвлв» отримувало відповідь
# оператора. Тепер такий текст не є ні публічною командою, ні згадкою.
for junk in ("Члвлв", "Члвлвьвж", "асдф", "?"):
    r.check(not is_command_trigger(junk), f"не команда: {junk!r}")
    r.check(not is_private_only_command(junk), f"не приватна команда: {junk!r}")

print("\n--- живі формулювання з групи ---")
# Саме ті фрази, на які бот у групі не відреагував.
LIVE = [
    ("Друже де я можу купити це", "order"),
    ("Друже де я можу придбати це", "order"),
    ("хтось знає де взяти", "order"),
    ("підкажіть будь ласка як замовити", "order"),
    ("скільки коштує", "price"),
    ("яка доставка по Україні", "delivery"),
    ("чим можна оплатити", "payment"),
]
for phrase, expected in LIVE:
    rule = faq.match(phrase, shop, public=True)
    r.check(rule is not None and rule.key == expected,
            f"{phrase!r} → {expected}", rule.key if rule else None)

print("\n--- друкарські помилки ---")
TYPOS = [
    ("замвити можна?", "order"),
    ("яка доствка", "delivery"),
    ("як оплтити", "payment"),
    ("де я можу купить", "order"),
]
for phrase, expected in TYPOS:
    rule = faq.match(phrase, shop, public=True)
    r.check(rule is not None and rule.key == expected,
            f"з помилкою: {phrase!r} → {expected}", rule.key if rule else None)

print("\n--- допуск не ловить зайвого ---")
# Найбільший ризик нечіткого збігу — реакція на сторонню розмову.
NOISE = ["котик", "як справи", "доброго ранку всім", "поставив чайник",
         "заморозки вночі", "заправив авто", "закінчив роботу",
         "документи готові", "домовились", "оплакую понеділок"]
for phrase in NOISE:
    rule = faq.match(phrase, shop, public=True)
    r.check(rule is None or rule.key in {"greeting", "thanks"},
            f"не вигадує відповідь: {phrase!r}", rule.key if rule else None)

print("\n--- відстань правок ---")
r.check(faq._close("замов", "замов"), "однакові")
r.check(faq._close("замв", "замов"), "пропущена буква")
r.check(faq._close("заммов", "замов"), "зайва буква")
r.check(faq._close("замав", "замов"), "замінена буква")
r.check(not faq._close("завм", "замов"), "дві правки — вже ні")
r.check(not faq._close("оплата", "замов"), "різні слова")

r.done()
