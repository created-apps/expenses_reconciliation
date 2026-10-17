"""Numbers and wording for the Results screen: attached sum vs charge, search, why an invoice is unused.

Pure Python (no database, network or clock). All money is integer paise (INR) or minor units of the
invoice's own currency; no exchange rate is ever assumed.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from app.engine.money import format_inr


@dataclass(frozen=True)
class AttachedInvoice:
    currency: str  # INR | USD
    total_minor: int | None  # None: no total could be read


@dataclass(frozen=True)
class Comparison:
    attached_sum_paise: int
    difference_paise: int  # charge minus attached sum (positive: the invoices are short)
    state: str  # none (nothing attached) | matches | differs
    needs_note: bool  # a non-zero difference must be explained by a person before it is saved


def attached_sum_paise(
    amount_paise: int,
    foreign_amount_minor: int | None,
    foreign_currency: str | None,
    invoices: Iterable[AttachedInvoice],
) -> int:
    """Sum of the attached invoices in paise, to compare with the charge.

    An INR invoice counts with its own total. A foreign-currency invoice counts as the full charge when
    its amount equals the line's foreign amount (same currency), and as zero otherwise.
    """
    total = 0
    for inv in invoices:
        if inv.total_minor is None:
            continue
        if inv.currency == "INR":
            total += inv.total_minor
        elif foreign_currency == inv.currency and foreign_amount_minor == inv.total_minor:
            total += amount_paise
    return total


def compare(
    amount_paise: int,
    foreign_amount_minor: int | None,
    foreign_currency: str | None,
    invoices: Sequence[AttachedInvoice],
) -> Comparison:
    total = attached_sum_paise(amount_paise, foreign_amount_minor, foreign_currency, invoices)
    difference = amount_paise - total
    if not invoices:
        return Comparison(0, amount_paise, "none", False)
    return Comparison(total, difference, "matches" if difference == 0 else "differs", difference != 0)


# -- search --------------------------------------------------------------------------------------------------
def _amount_text(minor: int) -> str:
    whole, rest = divmod(abs(minor), 100)
    return f"{whole}.{rest:02d}"


def _terms(query: str | None) -> list[str]:
    return (query or "").lower().split()


def _term_found(term: str, texts: Iterable[str | None], amounts: Iterable[int | None]) -> bool:
    if any(term in t.lower() for t in texts if t):
        return True
    digits = term.replace("₹", "").replace("$", "").replace(",", "")
    return bool(digits) and any(digits in _amount_text(a) for a in amounts if a is not None)


def line_matches(
    query: str | None,
    *,
    ser_no: str,
    description: str,
    amount_paise: int,
    note: str | None,
    vendor_name: str | None,
    file_names: Sequence[str],
) -> bool:
    """Every word typed must be found in the description, serial number, note, vendor, an attached file
    name, or the amount ("52539" finds 52,539.00)."""
    texts = [description, ser_no, note, vendor_name, *file_names]
    return all(_term_found(t, texts, [amount_paise]) for t in _terms(query))


def invoice_matches(
    query: str | None,
    *,
    file_name: str,
    vendor_key: str | None,
    vendor_name: str | None,
    invoice_no: str | None,
    order_id: str | None,
    total_minor: int | None,
) -> bool:
    """"amazon 175" finds Amazon invoices of 175.00: every word must be found somewhere."""
    texts = [file_name, vendor_key, vendor_name, invoice_no, order_id]
    return all(_term_found(t, texts, [total_minor]) for t in _terms(query))


# -- why an invoice is unused --------------------------------------------------------------------------------
@dataclass(frozen=True)
class VendorLine:
    """A debit of the invoice's vendor, as far as the reasons need it."""

    day: date
    amount_paise: int
    foreign_minor: int | None
    foreign_currency: str | None
    matched: bool  # it has an invoice attached


@dataclass(frozen=True)
class ReportOrder:
    """What the Amazon report says about one order (found by the invoice's Order ID)."""

    paid_on: date | None
    is_gift: bool
    card_last4: str | None


def _dm(d: date) -> str:
    return d.strftime("%d/%m")


def _dmy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _amount(currency: str, minor: int) -> str:
    if currency == "INR":
        return format_inr(minor)
    whole, cents = divmod(abs(minor), 100)
    return f"{'$' if currency == 'USD' else currency + ' '}{whole}.{cents:02d}"


def _same_amount(line: VendorLine, currency: str, total_minor: int) -> bool:
    if currency == "INR":
        return line.amount_paise == total_minor
    return line.foreign_currency == currency and line.foreign_minor == total_minor


def unused_reason(
    *,
    vendor_key: str | None,
    is_credit_note: bool,
    total_minor: int | None,
    currency: str,
    when: date | None,
    statement_date: date | None,
    vendor_lines: Sequence[VendorLine],
    window_days: int = 7,
    last_amazon_charge: date | None = None,
    report_order: ReportOrder | None = None,
    statement_cards: Sequence[str] = (),
) -> str:
    """The first reason that applies. Wording is shown on the "Invoices not used" tab and in the Excel.

    `report_order` is what the Amazon report says about this invoice's Order ID (None: no report, or the
    order is not in it). `last_amazon_charge` is the date of the last Amazon debit on the statement.
    """
    if is_credit_note:
        return "Credit note: never matched to a charge"
    if not vendor_key:
        return "No vendor set. Open the invoice and choose one"
    if total_minor is None:
        return "No total could be read"
    if report_order is not None:  # the report knows how this order was paid
        if report_order.is_gift:
            return "Paid by gift balance"
        if report_order.card_last4 and statement_cards and report_order.card_last4 not in statement_cards:
            return "Paid on another card"
        if report_order.paid_on and statement_date and report_order.paid_on > statement_date:
            return f"Paid on {_dm(report_order.paid_on)} (after this statement)"
    if when and statement_date and when > statement_date:
        return "Dated after the statement date"
    if vendor_key == "amazon" and when and last_amazon_charge and when > last_amazon_charge:
        return f"Dated after the last Amazon charge on this statement ({_dm(last_amazon_charge)})"
    if not vendor_lines:
        return "No statement line for this vendor"
    same = [line for line in vendor_lines if _same_amount(line, currency, total_minor)]
    if same:
        best = min(same, key=lambda line: abs((line.day - when).days) if when else 0)
        amount = _amount(currency, total_minor)
        gap = abs((best.day - when).days) if when else 0
        if best.matched:
            return f"A charge of {amount} on {_dmy(best.day)} is matched to another invoice"
        if gap > window_days:
            return (f"A charge of {amount} exists on {_dmy(best.day)}, {gap} days from the invoice date "
                    f"(invoices are matched within {window_days} days)")
        return f"A charge of {amount} exists on {_dmy(best.day)} but was not matched to this invoice"
    return "No charge of this amount found"