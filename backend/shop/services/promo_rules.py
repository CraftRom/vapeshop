"""Shared category and monetary rules for quotes, bot and locked checkout."""
from decimal import Decimal


def eligible_subtotal(lines, category_ids, subcategory_parents=None):
    selected = set(category_ids or [])
    parents = subcategory_parents or {}
    return sum((
        line.product.price * line.qty for line in lines
        if line.product and line.product.is_active and line.qty > 0 and (
            not selected or line.product.category_id in selected
            or parents.get(line.product.subcategory_id) in selected
        )
    ), Decimal(0))


def promo_discount(promo, subtotal):
    value = Decimal(str(promo.value))
    if promo.type == "percent":
        value = (subtotal * value / Decimal(100)).quantize(Decimal("0.01"))
    return max(Decimal(0), min(value, subtotal))
