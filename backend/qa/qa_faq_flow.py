"""FAQ у потоці бота: не заважає менеджеру, не мовчить новачкам."""
import asyncio, os
from decimal import Decimal
os.environ.update(BOT_TOKEN="1:t", JWT_SECRET="t"*32, ADMIN_CHAT_ID="-100111",
                  BOT_USERNAME="elfar1_bot", MINIAPP_SHORT_NAME="elfar",
                  PUBLIC_URL="https://www.elfar.pp.ua",
                  DATABASE_URL="sqlite+aiosqlite:////tmp/faqflow.db")
from types import SimpleNamespace
from shop.entities import Order, OrderLine
from bot.handlers import chat as handler

fails=[]
def check(c,l,d=""):
    print(f"  {'✓' if c else '✗'} {l}"+("" if c else f" — {d}")); (None if c else fails.append(l))

class Msg:
    def __init__(s, text, reply=False):
        s.text=text; s.caption=None; s.replies=[]
        s.reply_to_message = SimpleNamespace(message_id=1) if reply else None
        s.bot = SimpleNamespace(send_message=s._send)
    async def _send(s, *a, **k): return SimpleNamespace(message_id=99)
    async def answer(s, text, **kw):
        s.replies.append((text, kw.get("reply_markup"))); return None

class State:
    async def get_state(s): return None

async def run(repo, label):
    print(f"\n=== {label} ===")
    cat=await repo.create_category({"name":"К","sort_order":0,"is_active":True})
    p=await repo.create_product({"category_id":cat.id,"name":"Т","price":Decimal(100),"stock":9,"is_active":True})
    u=await repo.create_user(tg_id=1,username="a",first_name="A",referrer_id=None)

    # 1. Новачок без замовлень питає «як замовити»
    m=Msg("Як замовити?")
    await handler.incoming(m, repo=repo, user=await repo.get_user(u.id), state=State())
    check(m.replies and "Замовити просто" in m.replies[0][0], "новачок отримав інструкцію", m.replies)
    check(m.replies[0][1] is not None, "під відповіддю є кнопки")

    # 2. Раніше такий клієнт отримував відмову
    m=Msg("Привіт")
    await handler.incoming(m, repo=repo, user=await repo.get_user(u.id), state=State())
    check("активне замовлення" not in m.replies[0][0], "жодних відмов на привітання", m.replies[0][0])

    # 3. Клієнт із замовленням: побутове повідомлення йде менеджеру
    o=await repo.create_order(Order(id=0,user_id=u.id,subtotal=Decimal(100),discount=Decimal(0),
        bonus_used=Decimal(0),total=Decimal(100),promo_code_id=None,payment_method="cod",
        contact_name="A",contact_phone="+380671112233"),
        [OrderLine(product_id=p.id,name="Т",price=Decimal(100),qty=1)])
    m=Msg("Відділення 12, будь ласка")
    await handler.incoming(m, repo=repo, user=await repo.get_user(u.id), state=State())
    check("Передали менеджеру" in m.replies[0][0], "звичайне повідомлення — менеджеру", m.replies[0][0])
    msgs=await repo.list_order_messages(o.id)
    check(len(msgs)==1, "повідомлення збережено в стрічці", len(msgs))

    # 4. Відповідь на цитату НІКОЛИ не перехоплюється FAQ
    m=Msg("як оплатити?", reply=True)
    await handler.incoming(m, repo=repo, user=await repo.get_user(u.id), state=State())
    check("Передали менеджеру" in m.replies[0][0], "цитата завжди веде до менеджера", m.replies[0][0])
    msgs=await repo.list_order_messages(o.id)
    check(len(msgs)==2, "і теж потрапила в стрічку", len(msgs))

    # 5. Без цитати типове питання бот бере на себе
    m=Msg("яка у вас доставка?")
    await handler.incoming(m, repo=repo, user=await repo.get_user(u.id), state=State())
    check("Доставка" in m.replies[0][0], "питання про доставку — автовідповідь", m.replies[0][0])
    msgs=await repo.list_order_messages(o.id)
    check(len(msgs)==2, "менеджера не турбували", len(msgs))

    # 6. Кнопка «питання менеджеру» не веде в глухий кут
    cb=SimpleNamespace(message=Msg(""), answer=lambda *a, **k: asyncio.sleep(0))
    await handler.ask_human(cb, repo=repo, user=await repo.get_user(u.id))
    check(cb.message.replies and "менеджер" in cb.message.replies[0][0].lower(),
          "перехід до менеджера пояснено", cb.message.replies)

async def main():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from shop.models import Base
    from shop.repo.sql import SqlRepository
    e=create_async_engine("sqlite+aiosqlite:////tmp/faqflow.db")
    async with e.begin() as c: await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(e,expire_on_commit=False)() as s:
        await run(SqlRepository(s),"SQL")
    print(f"\n{'ПРОВАЛЕНО: '+str(len(fails)) if fails else 'усе витримано'}")
    for f in set(fails): print("  -",f)

asyncio.run(main())
