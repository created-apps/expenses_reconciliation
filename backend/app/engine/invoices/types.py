"""What the invoice readers return. Plain values only: no database, network or storage."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class ExtractedInvoice:
    """One invoice found in a document (a PDF can hold several).

    Money is in minor units of `currency`: paise for INR, cents for USD. `total_minor` is the
    invoice's own total (credit notes are positive, with `is_credit_note` set). `amounts_minor` is every
    amount the invoice shows in that currency; vendors matched on "an amount equals the charge" use it.
    """

    block_index: int = 0
    vendor_key: str | None = None
    invoice_no: str | None = None
    order_id: str | None = None
    invoice_date: date | None = None
    order_date: date | None = None
    currency: str = "INR"
    total_minor: int | None = None
    amounts_minor: list[int] = field(default_factory=list)
    is_credit_note: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    source: str = "pdf_text"
    extraction_status: str = "ok"  # ok | needs_check (pending and failed are set by the caller)
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VendorPattern:
    """A vendor as the invoice reader needs it (from recon_vendor_aliases)."""

    key: str
    invoice_pattern: str | None
    display_name: str | None = None  # used to resolve a vendor name read from an image
