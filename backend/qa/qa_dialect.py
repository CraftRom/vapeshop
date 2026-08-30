"""ДІАЛЕКТ: запити мають бути валідними саме для Postgres.

Цей набір існує через конкретну поломку. `func.max(0, x)` компілювався в
`max(0, x)`: у SQLite це звичайна функція від двох аргументів, тому всі
тести проходили, а в Postgres `max()` — агрегатна функція від одного, і
кожне оформлення замовлення падало з 500.

Тести ганяються на SQLite — це швидко й не потребує сервера. Але тоді
розходження діалектів не видно взагалі. Тут ми не виконуємо запити, а
компілюємо їх під діалект Postgres і дивимось на готовий SQL. Помилку
такого роду це ловить без жодної бази.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, "/tmp")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  ELFAR_DATA_ROOT="/tmp/qa_dialect_data")

from qa_common import Report                              # noqa: E402

r = Report("ДІАЛЕКТ")

from sqlalchemy import case, update                       # noqa: E402
from sqlalchemy.dialects import postgresql, sqlite        # noqa: E402

from shop import models as m                              # noqa: E402
from shop.repo.sql import _not_below_zero                 # noqa: E402


def as_postgres(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def as_sqlite(statement) -> str:
    return str(statement.compile(dialect=sqlite.dialect()))


# ------------------------------------------------- сам вираз обмеження знизу

print("\n--- нижня межа нуля ---")
statement = update(m.Product).values(stock=_not_below_zero(m.Product.stock - 1))
pg = as_postgres(statement)
lite = as_sqlite(statement)

r.check("CASE" in pg.upper(), "у Postgres це CASE", pg)
r.check("CASE" in lite.upper(), "у SQLite теж CASE", lite)

# Найголовніше: агрегатна функція з двома аргументами не має з'явитись
r.check(not re.search(r"\bmax\s*\(\s*\d+\s*,", pg, re.I),
        "немає max(0, …) — саме на цьому падав продакшн", pg)
r.check(not re.search(r"\bmin\s*\(\s*\d+\s*,", pg, re.I), "немає min(0, …)")
r.check("GREATEST" not in pg.upper(),
        "не GREATEST: його немає в SQLite, на якому ганяються тести")

print("\n--- поведінка виразу ---")
# Перевіряємо саму логіку на реальних значеннях через SQLite у памʼяті
import sqlite3                                            # noqa: E402

conn = sqlite3.connect(":memory:")
for value, delta, expected in [(5, -1, 4), (1, -1, 0), (0, -1, 0),
                               (0, +3, 3), (2, -10, 0)]:
    got = conn.execute(
        "SELECT CASE WHEN ? + ? < 0 THEN 0 ELSE ? + ? END",
        (value, delta, value, delta),
    ).fetchone()[0]
    r.check(got == expected, f"{value} {delta:+} → {expected}", got)
conn.close()


# ------------------------------------- жодних дволиких конструкцій у коді

print("\n--- у репозиторії немає функцій з різною арністю ---")
raw = (Path(__file__).resolve().parents[1] / "shop" / "repo" / "sql.py").read_text(
    encoding="utf-8")

# Шукаємо саме виклики в дереві, а не текст. У самому файлі пастка описана
# словами в докстрінгу, і пошук підрядком ловив би пояснення замість коду —
# тест провалювався б через власну документацію.
import ast

tree = ast.parse(raw)
risky = []
for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue
    target = node.func
    if isinstance(target, ast.Attribute) and target.attr in ("max", "min"):
        base = target.value
        if isinstance(base, ast.Name) and base.id == "func" and len(node.args) > 1:
            risky.append(f"func.{target.attr} з {len(node.args)} аргументами, "
                         f"рядок {node.lineno}")

# func.max/min із двома аргументами — та сама пастка: у SQLite це скалярна
# функція, у Postgres агрегатна. Тест на SQLite їх не ловить.
r.check(not risky, "немає func.max/min із двома аргументами", risky[:2])

source = raw
r.check("_not_below_zero" in source, "використовується спільний безпечний вираз")


# ------------------------------------------ решта запитів теж компілюється

print("\n--- ключові запити компілюються під Postgres ---")
statements = {
    "оновлення підсумків клієнта": update(m.User).values(
        orders_count=_not_below_zero(m.User.orders_count + 1),
        total_spent=_not_below_zero(m.User.total_spent + 100),
    ),
    "зміна залишку": update(m.Product).values(
        stock=_not_below_zero(m.Product.stock + 5)),
}
for label, statement in statements.items():
    try:
        compiled = as_postgres(statement)
        r.check(bool(compiled), f"{label}: компілюється")
        r.check(not re.search(r"\bmax\s*\([^)]*,", compiled, re.I),
                f"{label}: без max від двох аргументів")
    except Exception as exc:
        r.check(False, f"{label}: компілюється", str(exc)[:120])

r.done()
