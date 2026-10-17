"""IndiGo tax invoices (InterGlobe Aviation): `Grand Total`, `Date :`, `PNR :`.
One charge is usually two invoices (one per sector) with the same PNR."""

import re

from app.engine.invoices.amounts import amounts_in
from app.engine.invoices.dates import date_after_label
from app.engine.invoices.types import ExtractedInvoice

GRAND_TOTAL_ROW = re.compile(r"Grand Total[^\n]*")
PNR = re.compile(r"PNR\s*:\s*([A-Z0-9]{6})")
NUMBER = re.compile(r"(?m)^\s*Number\s*:\s*(\S+)")


def extract_indigo(text: str) -> list[ExtractedInvoice]:
    rows = GRAND_TOTAL_ROW.findall(text)
    amounts = amounts_in(rows[-1]) if rows else []
    total = amounts[-1].minor if amounts else None  # the last figure is the total including taxes
    pnr = PNR.search(text)
    number = NUMBER.search(text)
    return [
        ExtractedInvoice(
            vendor_key="indigo",
            invoice_no=number.group(1) if number else None,
            invoice_date=date_after_label(text, r"(?m)^\s*Date\s*:", 0),
            total_minor=total,
            amounts_minor=[total] if total is not None else [],
            extra={"pnr": pnr.group(1)} if pnr else {},
        )
    ]
