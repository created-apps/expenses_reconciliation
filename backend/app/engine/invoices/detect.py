"""Which vendor issued an invoice, from the invoice's TEXT. File names are never used."""

import re
from collections.abc import Iterable

from app.engine.invoices.types import VendorPattern

# Amazon invoices are recognised by their footer and layout, not by whichever brand a product carries
# (a Robocraze board on an Amazon invoice is still an Amazon invoice).
AMAZON_FOOTER = re.compile(r"ASSPL-Amazon|Amazon Seller Services|Amazon Retail India", re.I)


def resolve_vendor_name(name: str, vendors: Iterable[VendorPattern]) -> str | None:
    """A vendor name read from an image ("DTDC Express Limited", "Amazon") -> the vendor key.

    Tried with the same invoice patterns as PDF text; failing that, the vendor's own key or display
    name as a whole word ("Amazon" alone matches no footer pattern but is still Amazon).
    """
    vendors = list(vendors)
    found = detect_vendor(name, vendors)
    if found:
        return found
    for vendor in vendors:
        for label in (vendor.key, vendor.display_name):
            if label and re.search(rf"(?<![A-Za-z0-9]){re.escape(label)}(?![A-Za-z0-9])", name, re.I):
                return vendor.key
    return None


def detect_vendor(text: str, vendors: Iterable[VendorPattern]) -> str | None:
    """The vendor whose invoice pattern appears FIRST in the text, or None.

    The issuer's name is printed at the top of an invoice; other brand names (a Google link in a
    supplier's header, a product name) come later. The seeded pattern for each vendor is a
    case-insensitive regular expression (recon_vendor_aliases.invoice_pattern).
    """
    if "Order Number" in text and AMAZON_FOOTER.search(text):
        return "amazon"
    best: tuple[int, str] | None = None
    for vendor in vendors:
        if not vendor.invoice_pattern:
            continue
        try:
            found = re.search(vendor.invoice_pattern, text, re.I)
        except re.error:
            continue  # a bad pattern in the table must not stop the others
        if found and (best is None or found.start() < best[0]):
            best = (found.start(), vendor.key)
    return best[1] if best else None
