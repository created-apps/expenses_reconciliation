"""Money as integers. Rupee amounts are paise, foreign amounts are minor units (cents). No floats."""

from decimal import ROUND_HALF_UP, Decimal


def parse_minor(text: str) -> int:
    """'1,05,980.00' -> 10598000; '133.5' -> 13350; '36' -> 3600. Text only, never a float.

    A third decimal or more (rare, 'unit price' columns) is rounded half up.
    """
    cleaned = text.strip().replace(",", "").replace(" ", "")
    return int((Decimal(cleaned) * 100).to_integral_value(ROUND_HALF_UP))


def parse_paise(text: str) -> int:
    """Same as `parse_minor`; the name used where the amount is in rupees."""
    return parse_minor(text)


def short_decimal(minor: int) -> str:
    """Minor units as the shortest decimal text, as the client's earlier workbooks write foreign amounts:
    3600 -> '36', 13350 -> '133.5', 899 -> '8.99', 5 -> '0.05'."""
    whole, cents = divmod(abs(minor), 100)
    if cents == 0:
        return str(whole)
    return f"{whole}.{cents // 10}" if cents % 10 == 0 else f"{whole}.{cents:02d}"


def format_inr(paise: int) -> str:
    """₹ with Indian digit grouping, for messages only (e.g. 131610704 -> ₹13,16,107.04)."""
    rupees, rest = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join([*groups, tail])
    return f"{'-' if paise < 0 else ''}₹{digits}.{rest:02d}"
