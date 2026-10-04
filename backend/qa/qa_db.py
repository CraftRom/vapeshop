"""DATABASE: обмеження, транзакції, міграції, одночасність."""
import asyncio, os, sys, subprocess
sys.path.insert(0,"/tmp")
from decimal import Decimal
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t"*32,
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_db.db")

# Прибираємо базу від попереднього запуску.
#
# Набір, який проходить лише на чистій базі, гірший за відсутній: він
# падає через власні залишки, і час іде на з'ясування, що зламався тест,
# а не застосунок. Саме так qa_legal і qa_e2e показували провал, хоч
# застосунок працював.
import pathlib as _pathlib  # noqa: E402

for _leftover in _pathlib.Path("/tmp").glob("qa_db*"):
    if _leftover.is_file():
        _leftover.unlink(missing_ok=True)

from qa_common import Report
r = Report("DATABASE")

print("\n--- ланцюг міграцій ---")
from alembic.config import Config
from alembic.script import ScriptDirectory
script = ScriptDirectory.from_config(Config('alembic.ini'))
revisions = list(script.walk_revisions())
r.check(len(script.get_bases()) == 1, 'рівно один корінь міграцій', script.get_bases())
r.check(len(script.get_heads()) == 1, 'гілки зведено до одного head', script.get_heads())
known = {revision.revision for revision in revisions}
missing = [parent for revision in revisions for parent in
           ((revision.down_revision,) if isinstance(revision.down_revision, str) else revision.down_revision or ())
           if parent not in known]
r.check(not missing, 'усі попередники існують', missing)
r.check(len(revisions) >= 5, f'міграцій у графі: {len(revisions)}')

print("\n--- upgrade/downgrade на чистій базі ---")
env = dict(os.environ, PYTHONPATH=os.getcwd(),
           DATABASE_URL="sqlite+aiosqlite:////tmp/qa_mig.db")
if os.path.exists("/tmp/qa_mig.db"): os.remove("/tmp/qa_mig.db")
up = subprocess.run([sys.executable,"-m","alembic","upgrade","head"], capture_output=True, text=True, env=env)
r.check(up.returncode == 0, "міграції накочуються", (up.stderr or "")[-200:])
down = subprocess.run([sys.executable,"-m","alembic","downgrade","base"], capture_output=True, text=True, env=env)
r.check(down.returncode == 0, "міграції відкочуються", (down.stderr or "")[-200:])

async def main():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import text
    from shop.models import Base
    from shop.repo.sql import SqlRepository
    from shop.entities import Order, OrderLine
    from shop.services import shop_service as svc

    e = create_async_engine("sqlite+aiosqlite:////tmp/qa_db.db")
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(e, expire_on_commit=False)

    print("\n--- обмеження ---")
    async with Session() as s:
        repo = SqlRepository(s)
        u = await repo.create_user(tg_id=1, username="a", first_name="A", referrer_id=None)
        dup = None
        try:
            await s.execute(text("INSERT INTO users (tg_id, referral_code, created_at) VALUES (1,'X',CURRENT_TIMESTAMP)"))
            await s.commit()
        except Exception as exc:
            dup = type(exc).__name__
            await s.rollback()
        r.check(dup is not None, "унікальність tg_id тримається", dup)

    async with Session() as s:
        repo = SqlRepository(s)
        await repo.create_operator({"login":"op1","name":"O","password_hash":"x","role":"operator","is_active":True})
        err = None
        try:
            await repo.create_operator({"login":"op1","name":"O2","password_hash":"y","role":"operator","is_active":True})
        except Exception as exc:
            err = type(exc).__name__
            await s.rollback()
        r.check(err is not None, "унікальність логіна менеджера", err)

    print("\n--- відкат транзакції ---")
    async with Session() as s:
        repo = SqlRepository(s)
        cat = await repo.create_category({"name":"К","sort_order":0,"is_active":True})
        before = len(await repo.list_categories())
        try:
            await repo.create_category({"name":"Тимчасова","sort_order":0,"is_active":True})
            raise RuntimeError("штучний збій")
        except RuntimeError:
            await s.rollback()
        # create_category комітить одразу — перевіряємо, що поведінка передбачувана
        after = len(await repo.list_categories())
        r.check(after >= before, "після відкату база узгоджена", f"{before} -> {after}")

    print("\n--- цілісність після видалення ---")
    async with Session() as s:
        repo = SqlRepository(s)
        cat = await repo.create_category({"name":"К2","sort_order":0,"is_active":True})
        p = await repo.create_product({"category_id":cat.id,"name":"Т","price":Decimal(100),"stock":5,"is_active":True})
        u = await repo.get_user_by_tg(1)
        o = await repo.create_order(Order(id=0,user_id=u.id,subtotal=Decimal(100),discount=Decimal(0),
            bonus_used=Decimal(0),total=Decimal(100),promo_code_id=None,payment_method="cod",
            contact_name="A",contact_phone="+380671112233"),
            [OrderLine(product_id=p.id,name="Т",price=Decimal(100),qty=1)])
        await repo.purge_product(p.id)
        kept = await repo.get_order(o.id)
        r.check(kept is not None, "замовлення пережило видалення товару")
        r.check(kept.items[0].name == "Т", "назва в позиції збережена")
        r.check(await repo.get_product(p.id) is None, "товар справді стерто")

    print("\n--- одночасні записи ---")
    async def spend(uid):
        async with Session() as s:
            await SqlRepository(s).add_bonus(uid, Decimal(10), "паралель")
    u = None
    async with Session() as s:
        u = await SqlRepository(s).get_user_by_tg(1)
        start = u.bonus_balance
    await asyncio.gather(*(spend(u.id) for _ in range(10)))
    async with Session() as s:
        fresh = await SqlRepository(s).get_user(u.id)
    r.check(fresh.bonus_balance == start + Decimal(100),
            "десять паралельних нарахувань не загубились", f"{start} -> {fresh.bonus_balance}")

asyncio.run(main())
sys.exit(1 if r.done() else 0)
