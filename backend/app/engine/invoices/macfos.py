"""Robu / Macfos invoices: use the invoice's own `Total ₹ X` line, never the line items
(project_context.md 5.3). The invoice date is printed on the line below the "Invoice Date:" label."""

import re

from app.engine.invoices.dates import date_after_label
from app.engine.invoices.types import ExtractedInvoice
from app.engine.money import parse_minor

TOTAL = re.compile(r"(?<![A-Za-z])Total\s+₹\s*([\d,]+\.\d\d)")
INVOICE_NO = re.compile(r"Invoice#\s*(\S+)")


def extract_macfos(text: str) -> list[ExtractedInvoice]:
    totals = TOTAL.findall(text)
    total = parse_minor(totals[-1]) if totals else None
    number = INVOICE_NO.search(text)
    return [
        ExtractedInvoice(
            vendor_key="macfos",
            invoice_no=number.group(1) if number else None,
            invoice_date=date_after_label(text, r"Invoice Date\s*:", 3),
            total_minor=total,
            amounts_minor=[total] if total is not None else [],
        )
    ]
