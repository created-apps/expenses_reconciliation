"""DTDC PDF invoices: `Invoice Date`, `Total invoice Value` (it can carry paise: ₹215.01 for a ₹215 charge).
Booking screenshots are images, read by vision in Slice 7."""

import re

from app.engine.invoices.dates import date_after_label
from app.engine.invoices.types import ExtractedInvoice
from app.engine.money import parse_minor

TOTAL = re.compile(r"Total invoice Value\s+([\d,]+\.\d\d)", re.I)
INVOICE_NO = re.compile(r"Invoice No\.?\s+([A-Z0-9]+)")


def extract_dtdc(text: str) -> list[ExtractedInvoice]:
    found = TOTAL.search(text)
    total = parse_minor(found.group(1)) if found else None
    number = INVOICE_NO.search(text)
    return [
        ExtractedInvoice(
            vendor_key="dtdc",
            invoice_no=number.group(1) if number else None,
            invoice_date=date_after_label(text, r"Invoice Date\s", 0),
            total_minor=total,
            amounts_minor=[total] if total is not None else [],
        )
    ]
