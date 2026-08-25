"""ПЛАНУВАЛЬНИК: відкладені розсилки, тихі години, бекапи, ретенція."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/tmp")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  BACKUP_DIR="/tmp/qa_backups",
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_sched.db")

from qa_common import Report                         # noqa: E402

r = Report("ПЛАНУВАЛЬНИК")

from shop.entities import BroadcastStatus            # noqa: E402
from shop.models import Base                         # noqa: E402
from shop.repo.factory import open_repo              # noqa: E402
from shop.services.shop_settings import ShopSettings, save_shop_settings  # noqa: E402


async def create_schema():
    from shop.db import engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


asyncio.run(create_schema())


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# ------------------------------------------------------- тихі години (чиста логіка)

print("\n--- тихі години ---")
base = ShopSettings.from_env()
base.timezone = "Europe/Kyiv"
base.quiet_hours_enabled = True
base.quiet_hours_start = 22
base.quiet_hours_end = 9

# Київ узимку UTC+2. 21:00 UTC = 23:00 місцевого — це тиша.
r.check(base.in_quiet_hours(utc(2026, 1, 15, 21, 0)), "23:00 місцевого — тиша")
r.check(not base.in_quiet_hours(utc(2026, 1, 15, 12, 0)), "14:00 місцевого — можна")
r.check(base.in_quiet_hours(utc(2026, 1, 15, 4, 0)), "06:00 місцевого — тиша")
r.check(not base.in_quiet_hours(utc(2026, 1, 15, 7, 30)), "09:30 місцевого — можна")

wake = base.next_active_moment(utc(2026, 1, 15, 23, 0))
r.check(wake.astimezone(base.tz).hour == 9, "прокидається о 9 ранку", wake.isoformat())
r.check(wake > utc(2026, 1, 15, 23, 0), "час пробудження в майбутньому")

quiet_off = ShopSettings.from_env()
quiet_off.quiet_hours_enabled = False
r.check(not quiet_off.in_quiet_hours(utc(2026, 1, 15, 3, 0)),
        "вимкнені тихі години нічого не блокують")

same = ShopSettings.from_env()
same.quiet_hours_enabled = True
same.quiet_hours_start = same.quiet_hours_end = 10
r.check(not same.in_quiet_hours(utc(2026, 1, 15, 10, 30)),
        "однаковий початок і кінець = проміжку немає")

print("\n--- перехід на літній час ---")
summer = base.in_quiet_hours(utc(2026, 7, 15, 20, 30))   # 23:30 за Києвом
winter = base.in_quiet_hours(utc(2026, 1, 15, 20, 30))   # 22:30 за Києвом
r.check(summer and winter, "тиша тримається по обидва боки переходу", (summer, winter))
r.check(not base.in_quiet_hours(utc(2026, 7, 15, 18, 30)),
        "21:30 літнього часу — ще можна")


# ------------------------------------------------------------- відбір розсилок

async def scenario():
    from scheduler.tasks import prune_backups, run_due_broadcasts

    async with open_repo() as repo:
        past = await repo.create_broadcast({
            "title": "Дозріла", "text": "текст",
            "status": BroadcastStatus.SCHEDULED,
            "scheduled_at": datetime.now(timezone.utc) - timedelta(hours=2),
        })
        future = await repo.create_broadcast({
            "title": "Ще рано", "text": "текст",
            "status": BroadcastStatus.SCHEDULED,
            "scheduled_at": datetime.now(timezone.utc) + timedelta(days=1),
        })
        draft = await repo.create_broadcast({"title": "Чернетка", "text": "текст"})

        due = await repo.due_broadcasts(datetime.now(timezone.utc))
        ids = {b.id for b in due}
        r.check(past.id in ids, "дозріла розсилка потрапляє у вибірку")
        r.check(future.id not in ids, "майбутня не потрапляє")
        r.check(draft.id not in ids, "чернетка без дати не потрапляє")

        # Тихі години мають зупинити запуск, а не пропустити його назавжди
        await save_shop_settings(repo, {
            "quiet_hours_enabled": True,
            "quiet_hours_start": 0,
            "quiet_hours_end": 23,
            "timezone": "UTC",
        })

    started = await run_due_broadcasts()
    r.check(started == 0, "у тихі години нічого не запускається", started)

    async with open_repo() as repo:
        still = await repo.get_broadcast(past.id)
        r.check(still.status == BroadcastStatus.SCHEDULED,
                "розсилка лишається в черзі, а не губиться", still.status)

        await save_shop_settings(repo, {"quiet_hours_enabled": False})

    started = await run_due_broadcasts()
    r.check(started == 1, "поза тихими годинами розсилка стартує", started)

    async with open_repo() as repo:
        done = await repo.get_broadcast(past.id)
        r.check(done.status != BroadcastStatus.SCHEDULED,
                "статус змінився після запуску", done.status)
        untouched = await repo.get_broadcast(future.id)
        r.check(untouched.status == BroadcastStatus.SCHEDULED,
                "майбутня розсилка не зачеплена")

    # Повторний виклик не має підняти ту саму розсилку вдруге
    again = await run_due_broadcasts()
    r.check(again == 0, "повторний тік не перезапускає надіслане", again)

    print("\n--- час запуску переживає читання з бази ---")
    # Поле легко втратити в мапінгу рядок → сутність: запис проходить,
    # вибірка дозрілих теж (вона читає стовпець напряму), а от у панель
    # приїжджає None — і адміністратор бачить «Заплановано» без дати.
    async with open_repo() as repo:
        moment = datetime.now(timezone.utc) + timedelta(days=3)
        made = await repo.create_broadcast({
            "title": "Перевірка поля", "text": "текст",
            "status": BroadcastStatus.SCHEDULED, "scheduled_at": moment,
        })
        r.check(made.scheduled_at is not None, "create повертає час запуску")

        read_back = await repo.get_broadcast(made.id)
        r.check(read_back.scheduled_at is not None, "get_broadcast повертає час запуску")

        listed = {b.id: b for b in await repo.list_broadcasts()}
        r.check(listed[made.id].scheduled_at is not None,
                "list_broadcasts повертає час запуску")

        cleared = await repo.update_broadcast(made.id, {
            "status": BroadcastStatus.DRAFT, "scheduled_at": None,
        })
        r.check(cleared.scheduled_at is None, "зняття з черги очищає час")

    print("\n--- ретенція бекапів ---")
    from pathlib import Path

    backups = Path(os.environ["BACKUP_DIR"])
    backups.mkdir(parents=True, exist_ok=True)
    fresh = backups / "elfar-2026-08-25.dump"
    stale = backups / "elfar-2026-01-01.dump"
    fresh.write_bytes(b"x")
    stale.write_bytes(b"x")
    old_time = (datetime.now(timezone.utc) - timedelta(days=90)).timestamp()
    os.utime(stale, (old_time, old_time))

    removed = prune_backups(14)
    r.check(removed == 1, "старий дамп видалено", removed)
    r.check(fresh.exists(), "свіжий дамп на місці")
    r.check(not stale.exists(), "старого дампа більше немає")
    r.check(prune_backups(0) == 0, "нульова ретенція нічого не чистить")


asyncio.run(scenario())

r.done()
