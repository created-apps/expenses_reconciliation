"""Reading invoice facts out of PDF text. Pure Python (project_context.md 5.3).

`extract_invoices(text, vendors)` returns one `ExtractedInvoice` per invoice in the document. Every
result is validated: when something that matching needs can't be found the invoice is marked
`needs_check` and the reasons are kept in `problems`.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.engine.invoices.amazon import extract_amazon
from app.engine.invoices.detect import detect_vendor
from app.engine.invoices.dtdc import extract_dtdc
from app.engine.invoices.generic import extract_generic
from app.engine.invoices.indigo import extract_indigo
from app.engine.invoices.macfos import extract_macfos
from app.engine.invoices.types import ExtractedInvoice, VendorPattern
from app.engine.invoices.validate import validate

__all__ = [
    "ExtractedInvoice",
    "VendorPattern",
    "detect_vendor",
    "duplicate_indexes",
    "extract_invoices",
    "has_text_layer",
    "validate",
]

MIN_TEXT_CHARS = 30  # fewer letters and digits than this: a scan, read as an image by the vision model


def has_text_layer(text: str) -> bool:
    return sum(1 for ch in text if ch.isalnum()) >= MIN_TEXT_CHARS


def extract_invoices(text: str, vendors: Iterable[VendorPattern]) -> list[ExtractedInvoice]:
    """Invoices found in one document's text (several for a multi-invoice Amazon PDF), validated."""
    vendor = detect_vendor(text, list(vendors))
    found: list[ExtractedInvoice] = []
    if vendor == "amazon":
        found = extract_amazon(text)
    elif vendor == "macfos":
        found = extract_macfos(text)
    elif vendor == "indigo":
        found = extract_indigo(text)
    elif vendor == "dtdc":
        found = extract_dtdc(text)
    if not found:  # no reader for this vendor
        found = extract_generic(text, vendor)
    elif len(found) == 1 and vendor != "amazon":
        _fill_gaps(found[0], extract_generic(text, vendor)[0])  # a vendor's other layout (a second DTDC format)
    for item in found:
        if item.vendor_key is None:
            item.vendor_key = vendor
        validate(item)
    return found


def _fill_gaps(item: ExtractedInvoice, generic: ExtractedInvoice) -> None:
    """Take from the generic reading whatever the vendor's own reader did not find."""
    if item.total_minor is None and generic.total_minor is not None:
        item.total_minor, item.currency = generic.total_minor, generic.currency
        item.amounts_minor = list(generic.amounts_minor)
    item.invoice_no = item.invoice_no or generic.invoice_no
    item.invoice_date = item.invoice_date or generic.invoice_date


def duplicate_indexes(rows: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """Invoice-level duplicates: the same vendor + invoice number + total (+ currency) seen again.

    `rows` are in reading order. Returns {index of the later copy: index of the first one}. Invoices
    missing a vendor, a number or a total are never called duplicates (not enough to be sure).
    Byte-identical files are caught earlier, at upload; this finds re-downloaded copies.
    """
    first: dict[tuple[str, str, int, str], int] = {}
    dupes: dict[int, int] = {}
    for i, row in enumerate(rows):
        vendor, number, total = row.get("vendor_key"), row.get("invoice_no"), row.get("total_minor")
        if not vendor or not number or total is None:
            continue
        key = (str(vendor), str(number).strip().upper(), int(total), str(row.get("currency") or "INR"))
        if key in first:
            dupes[i] = first[key]
        else:
            first[key] = i
    return dupes
