"""Інструкції мають описувати те, що код справді робить."""
import pathlib, re, sys, os
os.environ.update(BOT_TOKEN="1:t", JWT_SECRET="t"*32)
# Корінь проєкту — на два рівні вище цього файлу (backend/qa/…)
root = pathlib.Path(__file__).resolve().parents[2]
guide = (root/"dashboard/src/pages/Instructions.jsx").read_text()

fails=[]
def check(c,l,d=""):
    print(f"  {'✓' if c else '✗'} {l}"+("" if c else f" — {d}")); (None if c else fails.append(l))

print("--- послідовність статусів ---")
from shop.services.shop_service import ALLOWED_TRANSITIONS
from shop.entities import OrderStatus as S
# інструкція обіцяє два ланцюги — залежно від способу оплати
from shop.services.shop_service import route_for
for payment, chain in (
    ("card", [S.NEW, S.ACCEPTED, S.PAID, S.SHIPPED, S.DONE]),
    ("cod", [S.NEW, S.ACCEPTED, S.SHIPPED, S.DONE]),
):
    route = route_for(payment)
    for a, b in zip(chain, chain[1:]):
        check(b in route[a], f"{payment}: {a.value} → {b.value} дозволено")
check(S.PAID not in route_for("cod")[S.ACCEPTED],
      "накладений платіж не має кроку «Оплачено», як і написано")
check("Підтверджено" not in guide,
      "інструкція більше не обіцяє крок «Підтверджено»")
check(S.DONE not in ALLOWED_TRANSITIONS[S.NEW], "стрибок «Нове → Виконано» заборонено, як і написано")
check(not ALLOWED_TRANSITIONS[S.CANCELLED], "зі скасованого шляху немає, як і написано")

print("\n--- ролі описані так само, як працюють ---")
from shop.entities import CREATABLE_ROLES, ROLE_TITLES, OperatorRole

for role in OperatorRole:
    check(ROLE_TITLES[role] in guide,
          f"роль «{ROLE_TITLES[role]}» згадана в інструкції")
check("створити тут не можна" in guide or "не можна: його логін" in guide,
      "інструкція каже, що системного адміністратора в панелі не створюють")

# Розділи, закриті для всіх, крім системного адміністратора, мають бути
# названі в інструкції — інакше менеджер шукатиме кнопки, яких немає.
from api.routers.settings import INFRA_FIELDS
for section in ("Telegram-груп", "Mini App", "розсилк", "тих", "бекап"):
    check(section.lower() in guide.lower(),
          f"інструкція згадує закритий розділ: {section}")

print("\n--- сторінка журналу описана ---")
check("Журнал" in guide, "розділ про журнал є")
check("requestId" in guide, "інструкція вчить шукати за requestId")
check("sysadminOnly" in guide, "розділ журналу закритий у самій інструкції")

print("\n--- права менеджера ---")
from api.routers.settings import OPERATOR_FIELDS
promised = {"referral_enabled","referral_percent","bonus_enabled","bonus_max_percent",
            "volume_discount_enabled","volume_discount_min","volume_discount_percent"}
check(OPERATOR_FIELDS == promised, "менеджеру доступні саме модулі лояльності",
      OPERATOR_FIELDS ^ promised)

print("\n--- інші обіцянки ---")
from shop.services.shop_settings import CACHE_TTL_SECONDS
check(CACHE_TTL_SECONDS <= 60, "зміни доїжджають за півхвилини", CACHE_TTL_SECONDS)
from shop.services.passwords import MIN_LENGTH
check(MIN_LENGTH == 8, "пароль від 8 символів", MIN_LENGTH)
from shop.services.wishlist import MAX_LISTS
check(MAX_LISTS >= 1, "списки бажаного існують")
from bot import faq
pub = {r.key for r in faq.RULES if r.public}
check({"delivery","payment","age","order"} <= pub, "бот сам відповідає про доставку, оплату, вік", pub)

print("\n--- розділи інструкції відповідають меню ---")
app = (root/"dashboard/src/App.jsx").read_text()
nav = set(re.findall(r"label: '([^']+)'", app))
titles = set(re.findall(r"title: '([^']+)'", guide))
for label in ("Замовлення","Каталог","Клієнти","Промокоди","Розсилки","Налаштування","Огляд","Менеджери"):
    check(label in nav and label in titles, f"розділ «{label}» є в меню й описаний")

print("\n--- нічого не обіцяно зайвого ---")
check("adminOnly" in guide, "адмінські розділи приховані від менеджера")
check("Інструкції" in nav, "розділ доданий у меню")

print(f"\n{'ПРОВАЛЕНО: '+str(len(fails)) if fails else 'інструкції відповідають коду'}")
sys.exit(1 if fails else 0)
