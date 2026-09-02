"""ЗАГОЛОВКИ: політика безпеки віддається і не ламає застосунків.

Заголовки безпеки мають дві симетричні небезпеки, і обидві мовчазні.

Занадто слабка політика нічого не боронить, але виглядає як боронить —
у конфізі рядок є, і його бачать. Занадто сувора ламає застосунок так,
що причину видно лише в консолі браузера: сторінка порожня, у журналі
сервера чисто, запит навіть не вийшов.

Тому набір перевіряє і те, і те: що політика справді закриває головні
шляхи атаки, і що вона пропускає рівно те, без чого панель і вітрина не
працюють.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, "/tmp")
from qa_common import Report                              # noqa: E402

r = Report("ЗАГОЛОВКИ")

root = Path(__file__).resolve().parents[2]
conf = (root / "deploy/nginx/app.conf.template").read_text()


def block(name: str) -> str:
    """Тіло location за точною назвою — з HTTPS-блоку, який і працює."""
    start = conf.rindex(f"location {name} {{")
    depth, i = 0, start
    while i < len(conf):
        if conf[i] == "{":
            depth += 1
        elif conf[i] == "}":
            depth -= 1
            if depth == 0:
                return conf[start:i]
        i += 1
    return conf[start:]


def directives(body: str) -> str:
    """Тіло без коментарів.

    Пояснення до правил згадують і X-Frame-Options, і 401 — саме тому, що
    там сказано, чому їх немає. Перевірка по всьому тексту спрацьовувала б
    на власне пояснення, як це вже було з переліком відсічення сканерів.
    """
    return "\n".join(
        line for line in body.splitlines() if not line.strip().startswith("#")
    )


def csp(body: str) -> dict[str, str]:
    """Політика як словник директив."""
    m = re.search(r'Content-Security-Policy\s+"([^"]+)"', body)
    if not m:
        return {}
    out = {}
    for part in m.group(1).split(";"):
        part = part.strip()
        if part:
            name, _, value = part.partition(" ")
            out[name] = value
    return out


panel = directives(block("/"))
shop = directives(block("/app"))

print("\n--- політика є в обох застосунках ---")
r.check(bool(csp(panel)), "панель віддає CSP")
r.check(bool(csp(shop)), "вітрина віддає CSP")

print("\n--- головний шлях крадіжки токена закритий ---")
# Токен панелі лежить у localStorage: будь-який виконаний на сторінці
# чужий скрипт забирає повний доступ до замовлень і клієнтів.
p = csp(panel)
r.check("'unsafe-inline'" not in p.get("script-src", ""),
        "панель не виконує вбудованих скриптів", p.get("script-src"))
r.check("'unsafe-eval'" not in p.get("script-src", ""),
        "панель не виконує eval", p.get("script-src"))
r.check(p.get("object-src") == "'none'", "панель не вантажить плагінів")
r.check(p.get("base-uri") == "'self'",
        "чужий <base> не переспрямує запити панелі", p.get("base-uri"))

s = csp(shop)
r.check("'unsafe-inline'" not in s.get("script-src", ""),
        "вітрина не виконує вбудованих скриптів", s.get("script-src"))
r.check("'unsafe-eval'" not in s.get("script-src", ""),
        "вітрина не виконує eval", s.get("script-src"))

print("\n--- політика пропускає те, без чого застосунки мертві ---")
# SDK Telegram: без нього немає ні initData, ні теми, ні кнопки «назад».
r.check("https://telegram.org" in s.get("script-src", ""),
        "вітрина вантажить SDK Telegram", s.get("script-src"))
# Шрифти панелі приходять з Google — без них інтерфейс лишиться
# на системному шрифті, але верстка попливе.
r.check("fonts.googleapis.com" in p.get("style-src", ""),
        "панель вантажить таблицю стилів шрифтів", p.get("style-src"))
r.check("fonts.gstatic.com" in p.get("font-src", ""),
        "панель вантажить самі файли шрифтів", p.get("font-src"))
# style={{...}} у React — це атрибути елементів, а не сторонній код.
for label, policy in (("панель", p), ("вітрина", s)):
    r.check("'unsafe-inline'" in policy.get("style-src", ""),
            f"{label}: інлайнові стилі React дозволені", policy.get("style-src"))
# Фото товарів можуть лежати і на чужому хостингу — так було до появи
# власного сховища, і старі картки досі посилаються назовні.
for label, policy in (("панель", p), ("вітрина", s)):
    r.check("https:" in policy.get("img-src", ""),
            f"{label}: зовнішні фото товарів не заблоковані",
            policy.get("img-src"))

print("\n--- вбудовування в рамку ---")
# Telegram Desktop і телефони відкривають Mini App у власному WebView,
# але Telegram Web — у звичайному iframe зі свого домену. Спільний для
# сервера SAMEORIGIN такий iframe забороняє, і вітрина в браузері
# показує порожнє вікно без жодного пояснення причини.
r.check("telegram.org" in s.get("frame-ancestors", ""),
        "вітрину дозволено вбудовувати Telegram", s.get("frame-ancestors"))
r.check("X-Frame-Options" not in shop,
        "у вітрині немає X-Frame-Options — він переважив би frame-ancestors "
        "у старих браузерах і закрив би Telegram Web")
r.check(p.get("frame-ancestors") == "'none'",
        "панель не вбудовується нікуди — це клікджекінг", p.get("frame-ancestors"))
r.check('X-Frame-Options "DENY"' in panel,
        "панель закрита й старим заголовком теж")

print("\n--- успадковані заголовки не загублені ---")
# add_header у location скасовує всі успадковані від server: це заміна,
# а не доповнення. Забути повторити — значить лишити застосунок узагалі
# без заголовків, і жодної помилки при цьому не буде.
for label, body in (("панель", panel), ("вітрина", shop)):
    r.check("X-Content-Type-Options" in body,
            f"{label}: nosniff повторено в location")
    r.check("Referrer-Policy" in body,
            f"{label}: Referrer-Policy повторено в location")
    r.check("hsts.d" in body, f"{label}: HSTS повторено в location")

r.done()
sys.exit(1 if r.fails else 0)
