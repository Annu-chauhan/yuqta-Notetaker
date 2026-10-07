from datetime import date
from decimal import Decimal


def pct_change(previous: float | Decimal, current: float | Decimal) -> float | None:
    if not previous:
        return None
    return round(float((Decimal(current) - Decimal(previous)) / Decimal(previous) * 100), 1)


def usd(value: float | Decimal, signed: bool = False) -> str:
    """$2.39M, $440K, -$190K style amounts."""
    amount = float(value)
    sign = "−" if amount < 0 else ("+" if signed and amount > 0 else "")
    amount = abs(amount)
    if amount >= 1_000_000:
        text = f"{amount / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    elif amount >= 1_000:
        text = f"{amount / 1_000:.0f}K"
    else:
        text = f"{amount:.0f}"
    return f"{sign}${text}"


def pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return "n/a"
    sign = "−" if value < 0 else ("+" if signed and value > 0 else "")
    return f"{sign}{abs(value):.1f}%"


def day(value: date) -> str:
    return f"{value.day} {value:%b %Y}"
