"""Regression checks for CRM status progression, live TTN enrichment and safe sync."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from shop.entities import Order, OrderStatus
from shop.services import order_workflow as flow
from shop.services import salesdrive


class Repo:
    def __init__(self, order: Order):
        self.order = order
        self.patches: list[dict] = []

    async def update_order(self, order_id: int, patch: dict):
        assert order_id == self.order.id
        self.patches.append(dict(patch))
        for key, value in patch.items():
            setattr(self.order, key, value)

    async def get_order(self, order_id: int):
        return self.order if order_id == self.order.id else None


async def check_tracking_enrichment():
    order = Order(
        id=1, user_id=1, status=OrderStatus.ACCEPTED,
        tracking_number="20450000123456", waybill_source=None, waybill_ref=None,
    )
    repo = Repo(order)
    result = await flow.apply_tracking(
        repo, order, "20450000123456", origin=flow.ORIGIN_SALESDRIVE,
        source=flow.SOURCE_SALESDRIVE, ref="np-ref", cost=Decimal("88.50"),
    )
    return (
        result.changed
        and repo.order.tracking_number == "20450000123456"
        and repo.order.waybill_source == flow.SOURCE_SALESDRIVE
        and repo.order.waybill_ref == "np-ref"
        and repo.order.waybill_cost == Decimal("88.50")
    )


async def check_forward_progression():
    calls = []
    marker_bot = object()
    original = flow.apply_status

    async def fake_apply_status(repo, order, status, *, origin, bot=None, on_saved=None):
        calls.append((status, origin, bot))
        fresh = replace(order, status=status)
        return flow.Outcome(order=fresh, changed=True)

    flow.apply_status = fake_apply_status
    try:
        order = Order(id=2, user_id=1, status=OrderStatus.NEW, payment_method="card")
        result = await flow.apply_crm_status_progression(
            object(), order, OrderStatus.SHIPPED, bot=marker_bot,
        )
    finally:
        flow.apply_status = original

    statuses = [item[0] for item in calls]
    bots = [item[2] for item in calls]
    return (
        result.order.status == OrderStatus.SHIPPED
        and statuses == [OrderStatus.ACCEPTED, OrderStatus.PAID, OrderStatus.SHIPPED]
        and bots == [None, None, marker_bot]
        and all(item[1] == flow.ORIGIN_SALESDRIVE for item in calls)
    )


async def check_backward_is_not_replayed():
    called = False
    original = flow.apply_status

    async def fake_apply_status(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("backward CRM movement must not call apply_status")

    flow.apply_status = fake_apply_status
    try:
        order = Order(id=3, user_id=1, status=OrderStatus.SHIPPED, payment_method="card")
        result = await flow.apply_crm_status_progression(
            object(), order, OrderStatus.ACCEPTED,
        )
    finally:
        flow.apply_status = original
    return not called and result.order.status == OrderStatus.SHIPPED and bool(result.reason)


async def check_legacy_confirmed_mapping():
    calls = []
    original = flow.apply_status

    async def fake_apply_status(repo, order, status, *, origin, bot=None, on_saved=None):
        calls.append(status)
        return flow.Outcome(order=replace(order, status=status), changed=True)

    flow.apply_status = fake_apply_status
    try:
        order = Order(id=4, user_id=1, status=OrderStatus.NEW, payment_method="card")
        result = await flow.apply_crm_status_progression(object(), order, OrderStatus.CONFIRMED)
    finally:
        flow.apply_status = original
    return calls == [OrderStatus.ACCEPTED] and result.order.status == OrderStatus.ACCEPTED


np_number, np_ref, np_cost = salesdrive._tracking_from({
    "ord_novaposhta": {"EN": "20450000123456", "ENref": "ref-np", "cost": "91.20"}
})
up_number, up_ref, up_cost = salesdrive._tracking_from({
    "ord_ukrposhta": {"barcode": "0500123456789", "barcodeUuid": "ref-up", "cost": "74.10"}
})

source = Path("shop/services/salesdrive.py").read_text()
repo_source = Path("shop/repo/sql.py").read_text()
orders_api = Path("api/routers/orders.py").read_text()
page = Path("../dashboard/src/pages/OrderPage.jsx").read_text()
styles = Path("../dashboard/src/styles.css").read_text()

checks = {
    "Nova Poshta TTN includes ENref and cost": (
        np_number == "20450000123456" and np_ref == "ref-np" and np_cost == Decimal("91.20")
    ),
    "Ukrposhta TTN includes barcodeUuid and cost": (
        up_number == "0500123456789" and up_ref == "ref-up" and up_cost == Decimal("74.10")
    ),
    "explicit empty TTN can be distinguished from partial webhook": (
        salesdrive._tracking_explicitly_present({"ord_novaposhta": {"EN": ""}})
        and salesdrive._tracking_explicitly_present({"ord_ukrposhta": {"barcode": ""}})
        and not salesdrive._tracking_explicitly_present({"statusId": 4})
    ),
    "same TTN enriches ref/source/cost": asyncio.run(check_tracking_enrichment()),
    "later CRM status confirms intermediate workflow stages": asyncio.run(check_forward_progression()),
    "CRM movement backwards does not undo side effects": asyncio.run(check_backward_is_not_replayed()),
    "legacy CRM confirmed maps to current accepted stage": asyncio.run(check_legacy_confirmed_mapping()),
    "webhook no longer ignores same-number TTN enrichment": (
        "result = await flow.apply_tracking(" in source
        and "if number and number != (order.tracking_number" not in source
    ),
    "read-only CRM calls have one bounded retry": (
        "for attempt in range(2):" in source and "response.status_code in (502, 503, 504)" in source
    ),
    "429 is not blindly retried": (
        "if response.status_code == 429:" in source and "Retry-After" in source
    ),
    "order page sends messages without broad page reload": "onSent={appendSentMessage}" in page,
    "messages and order data poll independently": (
        "useVisiblePolling(pollMessages, 5000)" in page
        and "useVisiblePolling(refreshLocalOrder, 60000)" in page
    ),
    "message polling has an after_id delta API": (
        "after_id: int | None = Query(None, ge=0)" in orders_api
        and "m.OrderMessage.id > int(after_id)" in repo_source
        and "created_at.desc()" in repo_source
    ),
    "long chats load newest messages instead of oldest 200": (
        "rows.reverse()" in repo_source and ".limit(cap)" in repo_source
    ),
    "CRM current status is visible without invented history": (
        "<SalesDriveStatusProgress" in page
        and ".crm-status-step.current" in styles
        and ".crm-status-step.passed" not in styles
    ),
    "CRM waybill origin is visible": (
        "сформована в SalesDrive" in page and "внесена вручну в SalesDrive" in page
    ),
    "missing or foreign CRM row is persisted as a visible sync error": (
        "salesdrive.pull.missing" in source
        and "salesdrive.pull.form_mismatch" in source
        and '"crm_error": message[:500]' in source
    ),
    "carrier tracking link is not guessed for unknown CRM TTN": (
        "order.waybill_source === 'novaposhta' || crmCarrier === 'Нова пошта'" in page
    ),
}

for label, ok in checks.items():
    print(("✓" if ok else "✗"), label)
assert all(checks.values())
print(f"✓ CRM live sync: {len(checks)}/{len(checks)}")
