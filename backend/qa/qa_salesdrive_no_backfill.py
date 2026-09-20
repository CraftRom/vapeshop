"""Regression guard: SalesDrive must never backfill historical ELFAR orders."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
shop = (root/'backend/shop/services/shop_service.py').read_text()
flow = (root/'backend/shop/services/order_workflow.py').read_text()
sd = (root/'backend/shop/services/salesdrive.py').read_text()
router = (root/'backend/api/routers/orders.py').read_text()

checks = {
    'new orders queue only when SalesDrive ready': 'crm_state="pending" if shop.salesdrive_ready else ""' in shop,
    'status changes only queue linked orders': 'crm_linked = business_state_service.has_crm_authority(order)' in shop,
    'tracking changes do not queue historical orders': '_crm_pending_patch(order)' in flow and 'if (order.crm_id or order.crm_state) else {}' in flow,
    'webhook cannot attach historical order by externalId': 'candidate and (candidate.crm_id or candidate.crm_state)' in sd,
    'manual retry cannot create historical CRM order': 'Історичне замовлення не експортується в SalesDrive' in router,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items(): print(('✓' if ok else '✗'), name)
if failed: raise SystemExit(1)
print(f'{len(checks)}/{len(checks)} checks passed')
