"""FAQ у групах і каналах: без витоку персональних даних."""
import asyncio, os
os.environ.update(BOT_TOKEN="1:t", JWT_SECRET="t"*32, ADMIN_CHAT_ID="-100111",
                  BOT_USERNAME="elfar1_bot", MINIAPP_SHORT_NAME="elfar",
                  PUBLIC_URL="https://www.elfar.pp.ua",
                  DATABASE_URL="sqlite+aiosqlite:///:memory:")
from types import SimpleNamespace
from bot.middlewares import PrivateOnlyMiddleware
from bot import faq

fails=[]
def check(c,l,d=""):
    print(f"  {'✓' if c else '✗'} {l}"+("" if c else f" — {d}")); (None if c else fails.append(l))

# Успадковуємо справжній Message: мідлвар перевіряє тип через isinstance,
# і на самописному класі вся публічна гілка мовчки не спрацьовувала
from aiogram.types import Message as TgMessage

class Msg(TgMessage):
    model_config = {"extra": "allow"}
    async def answer(s, text, **kw):
        s.replies.append(text)
        return None

def msg(text):
    m = Msg.model_construct(message_id=1, date=None, chat=None, text=text, caption=None)
    object.__setattr__(m, "replies", [])
    return m

async def send(text, chat_type="supergroup", chat_id=-100999):
    mw=PrivateOnlyMiddleware()
    reached=[]
    async def h(e,d): reached.append(1); return "OK"
    m=msg(text)
    r=await mw(h, m, {"event_chat": SimpleNamespace(type=chat_type, id=chat_id)})
    return m.replies, bool(reached)

async def main():
    print("--- у групі: загальні питання зі згадкою ---")
    for text, must in [("@elfar1_bot як замовити?", "Замовити просто"),
                       ("@elfar1_bot яка доставка", "Доставка"),
                       ("@elfar1_bot скільки коштує", "Ціни"),
                       ("@elfar1_bot з якого віку", "нікотин")]:
        replies,_ = await send(text)
        check(replies and must.lower() in replies[0].lower(), f"«{text}» → відповідь", replies)
        check(replies and "особистому чаті" in replies[0], "з відсиланням в особистий чат")

    print("\n--- персональні питання в групі не розкриваються ---")
    # На них бот відповідає загальним привітанням із кнопкою в особистий чат:
    # мовчання виглядало б як несправність, а деталі замовлення чи бонусів
    # у спільний чат віддавати не можна
    # Перевіряємо не окремі слова, а факт витоку: у публічний чат не має
    # потрапити ні номер замовлення, ні сума, ні персональне посилання.
    # Слово «бонуси» саме по собі безпечне — воно є в загальному привітанні.
    import re as _re
    def leaks(body):
        found = []
        if _re.search(r"№\s*\d", body): found.append("номер замовлення")
        if "startapp=" in body: found.append("реферальне посилання")
        if _re.search(r"\d+\s*(грн|uah|₴)", body): found.append("сума")
        if _re.search(r"баланс\s*[:—-]?\s*\d", body): found.append("баланс")
        return found
    for text in ["@elfar1_bot де моє замовлення", "@elfar1_bot скільки в мене бонусів",
                 "@elfar1_bot дай реферальне посилання", "@elfar1_bot як повернути товар"]:
        replies,_ = await send(text)
        body = " ".join(replies).lower()
        check(not leaks(body), f"без персональних деталей: «{text}»", leaks(body))
        check(not replies or "особист" in body, "є перехід в особистий чат", replies)

    print("\n--- без згадки бот не втручається ---")
    for text in ["як замовити?", "яка доставка", "привіт усім"]:
        replies,_ = await send(text)
        check(not replies, f"без згадки мовчимо: «{text}»", replies)

    print("\n--- згадка чужого бота ---")
    replies,_ = await send("@інший_бот як замовити")
    check(not replies, "чужа згадка ігнорується", replies)

    print("\n--- у каналі так само ---")
    replies,_ = await send("@elfar1_bot як замовити", chat_type="channel", chat_id=-100888)
    check(replies and "Замовити" in replies[0], "канал отримує загальну відповідь", replies)
    replies,_ = await send("@elfar1_bot де моє замовлення", chat_type="channel", chat_id=-100888)
    body = " ".join(replies).lower()
    check(not leaks(body), "канал не отримує персональних деталей", replies)

    print("\n--- приватний чат не зачеплено ---")
    replies, reached = await send("як замовити", chat_type="private", chat_id=5)
    check(reached, "приватне повідомлення йде до хендлерів", (replies, reached))

    print("\n--- перелік правил ---")
    priv=[r.key for r in faq.RULES if not r.public]
    check(set(priv) >= {"status","bonus","referral","contacts"},
          "персональні теми закриті для публіки", priv)

    print(f"\n{'ПРОВАЛЕНО: '+str(len(fails)) if fails else 'усе витримано'}")
    for f in fails: print("  -", f)

asyncio.run(main())
