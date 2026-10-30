"""The Amazon Business reconciliation report (CSV): rows, card payment groups, gift-balance orders.

Pure Python, no database. Facts are project_context.md 5.4 (checked on the September sample):

* 37 columns; the ones used are Order ID, Order Date, Order payment method, Payment Reference ID,
  Payment Date, Payment Identifier (written as `="4002"`), Shipment Quantity and Net total.
* Dates are dd/mm/yyyy, money has a dot for decimals; `N/A` and an empty cell both mean "no value".
* Grouping by Payment Reference ID and summing Net total gives each card charge to the paisa.
* Rows paid by `Gift Certificate/Card` are not card charges. Rows with no payment method at all (not
  paid, quantity 0) have no reference and are in neither list.
* Rows with Shipment Quantity 0 have no Net total (not shipped): they count as zero.

Money is integer paise.
"""

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.engine.money import parse_minor

REQUIRED = (
    "Order ID",
    "Order Date",
    "Order payment method",
    "Payment Reference ID",
    "Payment Date",
    "Payment Identifier",
    "Shipment Quantity",
    "Net total",
)
GIFT_METHOD = "gift certificate/card"
MAX_ERRORS_SHOWN = 3


class AmazonCsvError(Exception):
    """The file is not a usable Amazon Business report. The message is safe to show to a person."""


@dataclass(frozen=True)
class AmazonRow:
    order_id: str | None
    order_date: date | None
    payment_ref: str | None
    payment_date: date | None
    payment_method: str | None
    card_last4: str | None
    shipment_qty: int | None
    net_total_paise: int  # 0 when the cell is empty (not shipped)

    @property
    def is_gift(self) -> bool:
        return (self.payment_method or "").strip().lower() == GIFT_METHOD

    @property
    def is_card(self) -> bool:
        """Paid by card: it has a payment method, it is not the gift balance, and it has a reference."""
        return bool(self.payment_method) and not self.is_gift and bool(self.payment_ref)


@dataclass(frozen=True)
class CardGroup:
    """All card-paid rows with one Payment Reference ID: one charge on the card statement."""

    payment_ref: str
    payment_date: date | None
    card_last4: str | None
    order_ids: tuple[str, ...]
    amount_paise: int

    @property
    def orders(self) -> int:
        return len(self.order_ids)


@dataclass(frozen=True)
class GiftOrder:
    paid_on: date | None
    order_id: str | None
    amount_paise: int


def parse_amazon_csv(data: bytes) -> list[AmazonRow]:
    """Every data row of the report. Raises `AmazonCsvError` if it is not an Amazon Business report or
    a value in it can't be read (nothing is guessed)."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")  # exports saved by Excel on Windows
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    reader.fieldnames = headers
    missing = [name for name in REQUIRED if name not in headers]
    if missing:
        raise AmazonCsvError(
            "This doesn't look like an Amazon Business reconciliation report. Missing columns: " + ", ".join(missing)
        )

    rows: list[AmazonRow] = []
    errors: list[str] = []
    for number, raw in enumerate(reader, start=2):  # row 1 is the header
        if not any((v or "").strip() for v in raw.values() if isinstance(v, str)):
            continue
        try:
            rows.append(
                AmazonRow(
                    order_id=_text(raw["Order ID"]),
                    order_date=_date(raw["Order Date"], "Order Date"),
                    payment_ref=_text(raw["Payment Reference ID"]),
                    payment_date=_date(raw["Payment Date"], "Payment Date"),
                    payment_method=_text(raw["Order payment method"]),
                    card_last4=_last4(raw["Payment Identifier"]),
                    shipment_qty=_int(raw["Shipment Quantity"], "Shipment Quantity"),
                    net_total_paise=_amount(raw["Net total"]),
                )
            )
        except ValueError as exc:
            errors.append(f"row {number}: {exc}")
    if errors:
        shown = "; ".join(errors[:MAX_ERRORS_SHOWN])
        more = f" (and {len(errors) - MAX_ERRORS_SHOWN} more)" if len(errors) > MAX_ERRORS_SHOWN else ""
        raise AmazonCsvError(f"The report has values that can't be read: {shown}{more}")
    if not rows:
        raise AmazonCsvError("The report has no rows")
    return rows


def card_groups(rows: list[AmazonRow]) -> list[CardGroup]:
    """Card-paid rows grouped by Payment Reference ID, oldest payment first. A group's amount is the sum
    of its Net totals; its orders are the distinct Order IDs."""
    by_ref: dict[str, list[AmazonRow]] = defaultdict(list)
    for row in rows:
        if row.is_card and row.payment_ref:
            by_ref[row.payment_ref].append(row)
    groups = []
    for ref, members in by_ref.items():
        dates = sorted({r.payment_date for r in members if r.payment_date})
        cards = sorted({r.card_last4 for r in members if r.card_last4})
        groups.append(
            CardGroup(
                payment_ref=ref,
                payment_date=dates[0] if dates else None,
                card_last4=cards[0] if cards else None,
                order_ids=tuple(sorted({r.order_id for r in members if r.order_id})),
                amount_paise=sum(r.net_total_paise for r in members),
            )
        )
    groups.sort(key=lambda g: (g.payment_date or date.max, g.amount_paise, g.payment_ref))
    return groups


def gift_orders(rows: list[AmazonRow]) -> list[GiftOrder]:
    """Orders paid from the Amazon gift balance (not on the card), oldest first."""
    gifts = [
        GiftOrder(paid_on=r.payment_date or r.order_date, order_id=r.order_id, amount_paise=r.net_total_paise)
        for r in rows
        if r.is_gift
    ]
    gifts.sort(key=lambda g: (g.paid_on or date.max, g.amount_paise, g.order_id or ""))
    return gifts


# -- cell readers --------------------------------------------------------------------------------------------
def _text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return None if cleaned in ("", "N/A") else cleaned


def _date(value: str | None, column: str) -> date | None:
    cleaned = _text(value)
    if cleaned is None:
        return None
    found = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", cleaned)
    try:
        if not found:
            raise ValueError
        return date(int(found[3]), int(found[2]), int(found[1]))
    except ValueError:
        raise ValueError(f"{column} '{cleaned}' is not a dd/mm/yyyy date") from None


def _last4(value: str | None) -> str | None:
    """`="4002"` -> 4002 (Excel's way of keeping a number as text)."""
    cleaned = _text(value)
    if cleaned is None:
        return None
    digits = re.sub(r"\D", "", cleaned)
    return digits[-4:] if len(digits) >= 4 else None


def _int(value: str | None, column: str) -> int | None:
    cleaned = _text(value)
    if cleaned is None:
        return None
    if not re.fullmatch(r"\d+", cleaned):
        raise ValueError(f"{column} '{cleaned}' is not a whole number")
    return int(cleaned)


def _amount(value: str | None) -> int:
    cleaned = _text(value)
    if cleaned is None:
        return 0
    if not re.fullmatch(r"-?\d[\d,]*(?:\.\d+)?", cleaned):
        raise ValueError(f"Net total '{cleaned}' is not an amount")
    return parse_minor(cleaned)
