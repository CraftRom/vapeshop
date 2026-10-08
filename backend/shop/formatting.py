from decimal import Decimal


def money(value) -> str:
    """Preserve currency cents while keeping whole-price messages compact."""
    return format(Decimal(str(value)), '.2f').rstrip('0').rstrip('.')
