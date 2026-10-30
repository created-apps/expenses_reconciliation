"""Is an extracted invoice complete enough to match? (the `needs_check` rule)"""

import re

from app.engine.invoices.types import ExtractedInvoice

AMAZON = "amazon"
AMAZON_ORDER_ID = re.compile(r"^\d{3}-\d{7}-\d{7}$")
NO_ORDER_ID = "Amazon order ID not found. Open the file and type it (like 407-1234567-1234567)"


def order_id_problem(vendor_key: str | None, order_id: str | None) -> str | None:
    """An Amazon invoice must carry a readable Order ID: the Amazon report is matched to invoices by it, so a
    missing or misread ID would silently turn an uploaded invoice into a "missing" order."""
    if vendor_key != AMAZON:
        return None
    if not (order_id or "").strip():
        return NO_ORDER_ID
    if not AMAZON_ORDER_ID.match(order_id.strip()):
        return f"Amazon order ID “{order_id.strip()}” is not in the usual format 407-1234567-1234567. Check it"
    return None


def field_problems(
    *, vendor_key: str | None, order_id: str | None, total_minor: int | None,
    invoice_date: object | None, order_date: object | None,
) -> list[str]:
    """What is missing from an invoice's fields (the one rule behind reading and behind a person's correction)."""
    problems: list[str] = []
    if not vendor_key:
        problems.append("Vendor not recognised")
    if total_minor is None:
        problems.append("No total found")
    elif total_minor <= 0:
        problems.append("Total is not positive")
    if not invoice_date and not order_date:
        problems.append("No date found")
    order_problem = order_id_problem(vendor_key, order_id)
    if order_problem:
        problems.append(order_problem)
    return problems


def validate(item: ExtractedInvoice) -> ExtractedInvoice:
    """Marks the invoice `ok` or `needs_check`, and lists what is missing.

    Problems the reader already recorded (for example "the AI service was unreachable") are kept:
    they are never cleared by a successful field check.
    """
    problems: list[str] = list(item.problems)
    checks = field_problems(
        vendor_key=item.vendor_key, order_id=item.order_id, total_minor=item.total_minor,
        invoice_date=item.invoice_date, order_date=item.order_date,
    )
    # A reader that already explained the missing vendor (the AI reader does) is not repeated.
    if "Vendor not recognised" in checks and any(
        p.lower().startswith(("vendor", "the image does not show a vendor")) for p in problems
    ):
        checks.remove("Vendor not recognised")
    problems.extend(p for p in checks if p not in problems)
    item.problems = problems
    item.extraction_status = "needs_check" if problems else "ok"
    return item
