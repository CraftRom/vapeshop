"""Regression rules for canonical sales statistics."""
from decimal import Decimal
from types import SimpleNamespace
from pathlib import Path

from shop.entities import OrderStatus
from shop.repo.sql import stats_finance_values
from shop.services import order_business as business

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"✓ {name}")
    else:
        failed += 1
        print(f"✗ {name}: {detail}")


# CRM is the commercial source of truth.
check("CRM Продаж -> sale", business.state_from_crm_status_name("Продаж") == business.BUSINESS_SALE)
check("CRM Продаж tolerates spaces/case", business.state_from_crm_status_name("  ПРОДАЖ  ") == business.BUSINESS_SALE)
check("CRM Відмова -> refusal", business.state_from_crm_status_name("Відмова") == business.BUSINESS_REFUSAL)
check("other known CRM status stays pending", business.state_from_crm_status_name("Відправлено") == business.BUSINESS_PENDING)
check("missing CRM name is unknown", business.state_from_crm_status_name("") is None)

# Legacy fallback is intentionally narrow. Operational workflow stages are not sales.
for status in (OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.PAID, OrderStatus.SHIPPED):
    check(
        f"legacy {status.value} is not a sale",
        business.state_from_legacy_status(status) == business.BUSINESS_PENDING,
    )
check("legacy done is a sale", business.state_from_legacy_status(OrderStatus.DONE) == business.BUSINESS_SALE)
check("legacy cancelled is a refusal", business.state_from_legacy_status(OrderStatus.CANCELLED) == business.BUSINESS_REFUSAL)

crm_linked = SimpleNamespace(
    business_state=None, crm_id="42", crm_status_id="7", crm_status_name="Відправлено",
    crm_snapshot={}, status=OrderStatus.DONE,
)
check(
    "CRM authority blocks local DONE from inventing a sale",
    business.derive_business_state(crm_linked) == business.BUSINESS_PENDING,
)
legacy_done = SimpleNamespace(
    business_state=None, crm_id=None, crm_status_id=None, crm_status_name=None,
    crm_state="", crm_snapshot={}, status=OrderStatus.DONE,
)
check("true legacy DONE keeps historical sale", business.derive_business_state(legacy_done) == business.BUSINESS_SALE)
queued_done = SimpleNamespace(
    business_state=None, crm_id=None, crm_status_id=None, crm_status_name=None,
    crm_state="pending", crm_snapshot={}, status=OrderStatus.DONE,
)
check(
    "queued CRM order cannot become sale from local DONE",
    business.derive_business_state(queued_done) == business.BUSINESS_PENDING,
)

# Financial statistics only start after canonical business_state=sale.
pending_card = stats_finance_values("pending", OrderStatus.PAID, "card", 3596, {"payedAmount": 3596})
check("local PAID does not enter sales turnover", not pending_card["sold"] and pending_card["total"] == 0, pending_card)
check("local PAID does not enter received money", pending_card["received"] == 0 and pending_card["expected"] == 0, pending_card)

pending_shipped = stats_finance_values("pending", OrderStatus.SHIPPED, "cod", 880, {})
check("local SHIPPED remains a logistics flag", pending_shipped["shipped"], pending_shipped)
check("local SHIPPED does not invent a sale", not pending_shipped["sold"] and pending_shipped["total"] == 0, pending_shipped)

sale_card = stats_finance_values("sale", OrderStatus.ACCEPTED, "card", 3596, {})
check("CRM sale enters turnover regardless of local workflow", sale_card["sold"] and sale_card["total"] == Decimal("3596"), sale_card)
check("card sale is fully received by rule", sale_card["received"] == Decimal("3596"), sale_card)
check("card sale without CRM payedAmount is marked calculated", sale_card["calculated_received"] == Decimal("3596"), sale_card)
check("card sale has no expected balance", sale_card["expected"] == 0, sale_card)

sale_cod = stats_finance_values("sale", OrderStatus.SHIPPED, "cod", 880, {})
check("COD sale enters turnover", sale_cod["sold"] and sale_cod["total"] == Decimal("880"), sale_cod)
check("COD sale does not invent cash received", sale_cod["received"] == 0, sale_cod)
check("unpaid COD sale remains expected", sale_cod["expected"] == Decimal("880"), sale_cod)

sale_cod_partial = stats_finance_values(
    "sale", OrderStatus.SHIPPED, "cod", 880,
    {"paymentAmount": 880, "payedAmount": 300, "restPay": 580},
)
check("actual CRM COD payment is received", sale_cod_partial["received"] == Decimal("300"), sale_cod_partial)
check("remaining COD stays expected", sale_cod_partial["expected"] == Decimal("580"), sale_cod_partial)

crm_total = stats_finance_values(
    "sale", OrderStatus.SHIPPED, "card", 1000, {"paymentAmount": 1200, "payedAmount": None}
)
check("CRM paymentAmount wins over local total", crm_total["total"] == Decimal("1200"), crm_total)
check("card sale rule uses CRM amount", crm_total["received"] == Decimal("1200"), crm_total)

refusal = stats_finance_values("refusal", OrderStatus.CANCELLED, "card", 500, {"payedAmount": 500})
check("refusal never enters sale finance", not refusal["sold"] and refusal["total"] == 0 and refusal["received"] == 0, refusal)

# Static architecture guards: statistics must not drift back to workflow status.
root = Path(__file__).resolve().parents[1]
repo_source = (root / "shop/repo/sql.py").read_text()
users_source = (root / "shop/services/users.py").read_text()
segments_source = (root / "shop/services/segments.py").read_text()
migration_source = (root / "alembic/versions/c2f51b8d9e40_business_sale_state.py").read_text()
shop_source = (root / "shop/services/shop_service.py").read_text()

check("stats no longer has CONFIRMED_SQL", "CONFIRMED_SQL" not in repo_source)
check("stats no longer has old counted workflow set", "_COUNTED" not in shop_source)
check("sale queries use canonical business state", repo_source.count("m.Order.business_state == business.BUSINESS_SALE") >= 5)
check("customer stats use sale state", 'Order.business_state == "sale"' in users_source)
check("broadcast/customer segments use sale state", 'Order.business_state == "sale"' in segments_source)
check("migration rebuilds customer totals", "SET orders_count = COALESCE" in migration_source and "business_state = 'sale'" in migration_source)
check("queued CRM rows are not legacy sales", "COALESCE(crm_state, '') = '' AND status = 'DONE'" in migration_source)
check("repository CRM patch synchronizes business state", 'if "crm_status_name" in data:' in repo_source and "_apply_business_state_row" in repo_source)

print(f"STATS BUSINESS: {passed}/{passed + failed}")
raise SystemExit(1 if failed else 0)
