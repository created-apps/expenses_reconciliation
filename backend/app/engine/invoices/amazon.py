"""Amazon tax invoices. One PDF can hold several invoices: a new invoice starts on every page that
contains `Order Number`, and the pages that follow belong to it (project_context.md 5.3)."""

import re

from app.engine.invoices.amounts import amounts_in
from app.engine.invoices.dates import date_after_label
from app.engine.invoices.types import ExtractedInvoice

ORDER = re.compile(r"Order Number:\s*([\d-]+)")
INVOICE_NO = re.compile(r"Invoice Number\s*:\s*(\S+)")
TOTAL_ROW = re.compile(r"TOTAL:[^\n]*")


def extract_amazon(text: str) -> list[ExtractedInvoice]:
    blocks: list[str] = []
    for page in text.split("\f"):
        if "Order Number" in page:
            blocks.append(page)
        elif blocks:
            blocks[-1] += "\n" + page  # continuation page of the invoice above
    return [_one(block, i) for i, block in enumerate(blocks)]


def _one(block: str, index: int) -> ExtractedInvoice:
    order = ORDER.search(block)
    number = INVOICE_NO.search(block)
    # The invoice total is the last TOTAL: row, and its last amount (rows read: tax, then total).
    total_rows = TOTAL_ROW.findall(block)
    amounts = [a for a in amounts_in(total_rows[-1]) if a.currency == "INR"] if total_rows else []
    total = amounts[-1].minor if amounts else None
    return ExtractedInvoice(
        block_index=index,
        vendor_key="amazon",
        invoice_no=number.group(1) if number else None,
        order_id=order.group(1) if order else None,
        invoice_date=date_after_label(block, r"Invoice Date\s*:", 0),
        order_date=date_after_label(block, r"Order Date\s*:", 0),
        total_minor=total,
        amounts_minor=[total] if total is not None else [],
        is_credit_note=bool(re.search(r"Credit\s+Note", block, re.I)),
    )
