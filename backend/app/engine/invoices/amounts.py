"""Money amounts as printed on invoices, read into integer minor units. No floats."""

import re
from dataclasses import dataclass

from app.engine.money import parse_minor

MAX_MINOR = 1_000_000_000  # 1 crore rupees / 10 million dollars: anything bigger is a phone number or an id

# One alternation, so a line is read left to right. Order matters: a dollar sign wins over a bare number.
AMOUNT = re.compile(
    r"(?P<usd>(?:US\$|\$)\s?(?P<u>[\d,]*\d(?:\.\d{1,2})?))"
    r"|(?P<usdcode>(?P<uc>[\d,]*\d\.\d{1,2})\s?USD\b)"
    r"|(?P<inr>(?:₹|`|\bRs\.?|\bINR\b)\s?(?P<i>[\d,]*\d(?:\.\d{1,2})?))"
    r"|(?P<plain>(?<![\d.,$])(?P<p>(?:\d{1,3}(?:,\d{2,3})+|\d+)\.\d{2})(?![\d]))",
    re.I,
)


@dataclass(frozen=True)
class Amount:
    minor: int
    currency: str  # INR | USD
    symbol: bool  # printed with a currency sign or code (a bare 1,234.00 is not)
    pos: int


def amounts_in(text: str) -> list[Amount]:
    """Every money amount in `text`, left to right, with its currency."""
    found: list[Amount] = []
    for m in AMOUNT.finditer(text):
        if m.group("u") is not None:
            raw, currency, symbol = m.group("u"), "USD", True
        elif m.group("uc") is not None:
            raw, currency, symbol = m.group("uc"), "USD", True
        elif m.group("i") is not None:
            raw, currency, symbol = m.group("i"), "INR", True
        else:
            raw, currency, symbol = m.group("p"), "INR", False
        try:
            minor = parse_minor(raw.strip(","))
        except Exception:  # noqa: BLE001 - not a number after all
            continue
        if 0 < minor < MAX_MINOR:
            found.append(Amount(minor, currency, symbol, m.start()))
    return found


def distinct_amounts(text: str, currency: str) -> list[int]:
    """Sorted distinct amounts of one currency. For INR, bare two-decimal numbers count too
    (many invoices print rupee amounts without a sign); USD needs a dollar sign or code."""
    return sorted({a.minor for a in amounts_in(text) if a.currency == currency})
