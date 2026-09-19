"""Regression rules for dashboard finance statistics."""
from decimal import Decimal

from shop.entities import OrderStatus
from shop.repo.sql import stats_finance_values

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


card_sent = stats_finance_values(OrderStatus.SHIPPED, "card", 3596, {})
check("card shipped is confirmed", card_sent["confirmed"], card_sent)
check("card shipped full amount is received", card_sent["received"] == Decimal("3596"), card_sent)
check("card shipped without CRM payedAmount is calculated", card_sent["calculated_received"] == Decimal("3596"), card_sent)
check("card shipped has no expected balance", card_sent["expected"] == 0, card_sent)

card_confirmed = stats_finance_values(OrderStatus.ACCEPTED, "card", 3596, {})
check("card confirmed enters turnover", card_confirmed["confirmed"] and card_confirmed["total"] == Decimal("3596"), card_confirmed)
check("card confirmed but not paid stays expected", card_confirmed["received"] == 0 and card_confirmed["expected"] == Decimal("3596"), card_confirmed)

card_paid = stats_finance_values(OrderStatus.PAID, "card", 3596, {"payedAmount": 0})
check("explicit card paid stage counts as received", card_paid["received"] == Decimal("3596"), card_paid)

cod_sent = stats_finance_values(OrderStatus.SHIPPED, "cod", 880, {})
check("COD shipped enters shipped turnover", cod_sent["shipped"] and cod_sent["total"] == Decimal("880"), cod_sent)
check("COD shipped is not invented as cash received", cod_sent["received"] == 0, cod_sent)
check("COD shipped stays expected", cod_sent["expected"] == Decimal("880"), cod_sent)

cod_partial = stats_finance_values(
    OrderStatus.SHIPPED, "cod", 880, {"paymentAmount": 880, "payedAmount": 300, "restPay": 580}
)
check("actual CRM COD payment is received", cod_partial["received"] == Decimal("300"), cod_partial)
check("remaining COD stays expected", cod_partial["expected"] == Decimal("580"), cod_partial)

crm_total = stats_finance_values(
    OrderStatus.SHIPPED, "card", 1000, {"paymentAmount": 1200, "payedAmount": None}
)
check("CRM paymentAmount wins over local total", crm_total["total"] == Decimal("1200"), crm_total)
check("card rule uses CRM amount", crm_total["received"] == Decimal("1200"), crm_total)

new_order = stats_finance_values(OrderStatus.NEW, "card", 500, {"payedAmount": 500})
check("new order does not enter confirmed finance", not new_order["confirmed"] and new_order["received"] == 0, new_order)

print(f"STATS BUSINESS: {passed}/{passed + failed}")
raise SystemExit(1 if failed else 0)
