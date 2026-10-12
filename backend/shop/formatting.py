from decimal import Decimal


def money(value) -> str:
    """Ukrainian monetary display, always preserving both currency cents."""
    return format(Decimal(str(value or 0)), '.2f').replace('.', ',')
