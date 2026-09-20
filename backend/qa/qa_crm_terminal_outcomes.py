"""Regression for mutually exclusive SalesDrive terminal outcomes."""
from pathlib import Path
import ast

from shop.services import order_business as business

passed = failed = 0

def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"✓ {name}")
    else:
        failed += 1
        print(f"✗ {name}: {detail}")

for value in ("Відмова", "Повернення", "Повернено", "Видалений", "Видалено", "deleted", "returned"):
    check(f"{value} is refusal", business.state_from_crm_status_name(value) == business.BUSINESS_REFUSAL)

for value in ("Новий", "Підтверджено", "На відправку", "Відправлений"):
    check(f"{value} is not sale/refusal", business.state_from_crm_status_name(value) == business.BUSINESS_PENDING)

check("Продаж remains sole sale", business.state_from_crm_status_name("Продаж") == business.BUSINESS_SALE)

root = Path(__file__).resolve().parents[1]
versions = root / "alembic/versions"
revisions = {}
for path in versions.glob("*.py"):
    tree = ast.parse(path.read_text())
    rev = down = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                    try: value = ast.literal_eval(node.value)
                    except Exception: continue
                    if target.id == "revision": rev = value
                    else: down = value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in {"revision", "down_revision"}:
            try: value = ast.literal_eval(node.value)
            except Exception: continue
            if node.target.id == "revision": rev = value
            else: down = value
    if rev:
        revisions[rev] = down
parents = set()
for down in revisions.values():
    if isinstance(down, str): parents.add(down)
    elif isinstance(down, (tuple, list)): parents.update(down)
heads = sorted(set(revisions) - parents)
check("Alembic has exactly one head", heads == ["e3f7a91c2d64"], heads)

migration = (versions / "e3f7a91c2d64_merge_heads_and_negative_crm_outcomes.py").read_text()
check("migration rebuilds customer sale totals", "orders_count = COALESCE" in migration and "business_state = 'sale'" in migration)
check("migration classifies return/deleted", "Повернення" in migration and "Видалений" in migration and "business_state = 'refusal'" in migration)

print(f"CRM TERMINAL OUTCOMES: {passed}/{passed + failed}")
raise SystemExit(1 if failed else 0)
