"""Any other vendor: all amounts, the invoice's own total when a label gives it, the dates and the number.

Nothing here is specific to one vendor. When the total or the date can't be found with confidence the
invoice is flagged `needs_check` by the caller, and the candidate amounts are still kept: vendors that
match on "an amount equals the charge" use `amounts_minor` (project_context.md section 8, rule 7).
"""

import re

from app.engine.invoices.amounts import Amount, amounts_in, distinct_amounts
from app.engine.invoices.dates import date_after_label, find_dates
from app.engine.invoices.types import ExtractedInvoice

# Labels that carry the invoice's own total, best first. `side` says which amount on the line is the
# total: the last one when the label heads a row of columns, the first when a note follows it
# ("Paid Amount INR 94,146   You saved INR 8,071"). `need_sign` skips table rows that have no currency sign.
TOTAL_LABELS: list[tuple[str, str, bool]] = [
    (r"Rounded\s+Total", "last", False),
    (r"Net\s+Payable", "first", False),
    (r"Total\s+Invoice\s+Value", "last", False),
    (r"Grand\s+Total", "last", False),
    (r"Invoice\s+Amount", "first", False),
    (r"Paid\s+Amount|Amount\s+Paid", "first", False),
    # A heading with the values on the rows below it (e-invoices: "Total Invoice Amount").
    (r"Total\s+Invoice\s+Amount\s*$", "below", False),
    # Not "Total Items / Qty : 17 / 49 ... Shipping Rs 63.56", "TAX TOTAL Rs 99" or "Total in words".
    (r"(?<![A-Za-z])(?<!tax )Total(?!\s+(?:excluding|excl|tax|taxes|taxable|in\s+words|items|qty|quantity))", "last", True),
    (r"Amount\s+due", "first", False),
]
CURRENCY_IN_LABEL = re.compile(r"Total\s*\((?:`|₹|INR|Rs\.?)\)", re.I)  # "Total (`)  2,192.52"

DATE_LABELS = [
    r"Invoice\s+Date\s*:?",
    r"Date\s+of\s+issue",
    r"Date\s+Paid\s*:?",
    r"Bill\s+date",
    r"Document\s+Date\s*:?",
    r"(?<![A-Za-z])Dated\b",
    r"(?<![A-Za-z.])(?<!Due )(?<!Booking )(?<!Travel )(?<!Ack\.)(?<!Ack )Date\s*:",
    r"(?m)^\s*Date(?=\s{2,}[A-Za-z])",  # a table whose first column is "Date", the row below holds it
    r"Issue\s+Date\b",
    r"Transaction\s+Date\b",
]

NUMBER_LABELS = [
    r"Invoice\s*(?:No\.?|Number|#)\s*[:.]?\s*",
    r"Bill\s+number\s*[:.]?\s*",
    r"Document\s+No\.?\s*[:.]?\s*",
    r"Receipt\s*(?:No\.?|Number|#)?\s*[:.]?\s*",
    r"Booking\s+Id\s*[:.]?\s*",
    r"(?m)^\s*Number\s*:\s*",
]
NUMBER_HEADER = re.compile(r"Invoice\s*(?:No\.?|Number)\s*(?:Dated\b.*)?$", re.I)
HAS_DIGIT = r"(?=[\w/-]*\d)"
TOKEN = r"([A-Z0-9][\w/-]{2,})"


def extract_generic(text: str, vendor_key: str | None) -> list[ExtractedInvoice]:
    total = _labelled_total(text)
    currency = total.currency if total else _guess_currency(text)
    inr = distinct_amounts(text, "INR")
    usd = distinct_amounts(text, "USD")
    amounts = usd if currency == "USD" else inr
    total_minor = total.minor if total else None
    if total_minor is not None and total_minor not in amounts:
        amounts = sorted({*amounts, total_minor})
    extra = {"usd_amounts_minor": usd} if currency == "INR" and usd else {}
    return [
        ExtractedInvoice(
            vendor_key=vendor_key,
            invoice_no=_invoice_number(text),
            invoice_date=_invoice_date(text),
            # A booking document (a flight ticket) says when the purchase was made; matching places the
            # charge by that date, like an Amazon order date, when the invoice is dated later.
            order_date=date_after_label(text, r"Booking\s+Date\s*:?", 0),
            currency=currency,
            total_minor=total_minor,
            amounts_minor=amounts,
            extra=extra,
        )
    ]


def _labelled_total(text: str) -> Amount | None:
    rows = text.split("\n")
    for label, side, need_sign in TOTAL_LABELS:
        for i, row in enumerate(rows):
            m = re.search(label, row, re.I)
            if not m:
                continue
            if side == "below":
                for below in rows[i + 1 : i + 7]:
                    values = amounts_in(below)
                    if len(values) >= 2:  # the row of figures; its last column is the total
                        return values[-1]
                continue
            sign_needed = need_sign and not CURRENCY_IN_LABEL.search(row)
            on_row = [a for a in amounts_in(row[m.start():]) if a.symbol or not sign_needed]
            if on_row:
                return on_row[-1] if side == "last" else on_row[0]
    return None


def _guess_currency(text: str) -> str:
    amounts = amounts_in(text)
    usd = sum(1 for a in amounts if a.currency == "USD")
    inr = sum(1 for a in amounts if a.currency == "INR" and a.symbol)
    return "USD" if usd > inr else "INR"


def _invoice_date(text: str):
    for label in DATE_LABELS:
        found = date_after_label(text, label, 2)
        if found:
            return found
    dates = find_dates(text)
    return dates[0][1] if dates else None


def _invoice_number(text: str) -> str | None:
    rows = text.split("\n")
    for label in NUMBER_LABELS:
        for i, row in enumerate(rows):
            m = re.search(label + HAS_DIGIT + TOKEN, row, re.I)
            if m:
                return m.group(1)
            # A table header with the value on the line below ("Invoice No.   Dated" / "ABC/123   1-Jun-26").
            header = NUMBER_HEADER.search(row)
            if header and i + 1 < len(rows):
                column = header.start()  # read the value from the same column, not from text beside it
                below = re.search(HAS_DIGIT + TOKEN, rows[i + 1][max(column - 2, 0):])
                if below:
                    return below.group(1)
    return None
