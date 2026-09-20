"""Regression: PostgreSQL cart row lock must not include eager LEFT JOIN.

1.50.0 made cart mutations atomic with FOR UPDATE, but CartItem.product is
lazy=joined. SQLAlchemy therefore generated LEFT OUTER JOIN products ... FOR
UPDATE, which PostgreSQL rejects with FeatureNotSupportedError.
"""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import lazyload

from shop import models as m

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "backend/shop/repo/sql.py").read_text(encoding="utf-8")

compiled = str(
    select(m.CartItem)
    .where(m.CartItem.user_id == 1, m.CartItem.product_id == 2)
    .options(lazyload(m.CartItem.product))
    .with_for_update(of=m.CartItem)
    .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
)

checks = [
    ("lazyload imported", "from sqlalchemy.orm import lazyload, selectinload" in SQL),
    ("cart product eager join disabled in lock query", SQL.count(".options(lazyload(m.CartItem.product))") >= 2),
    ("lock targets cart_items only", SQL.count(".with_for_update(of=m.CartItem)") >= 2),
    ("compiled lock has no OUTER JOIN", "OUTER JOIN" not in compiled.upper()),
    ("compiled lock targets cart_items", "FOR UPDATE OF cart_items" in compiled),
]

failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(("OK" if ok else "FAIL"), name)
if failed:
    print(compiled)
    raise SystemExit("failed: " + ", ".join(failed))
print(f"{len(checks)}/{len(checks)}")
