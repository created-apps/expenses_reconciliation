"""What the 12 June invoice images say (implementation_plan.md tests 7.2 to 7.8, read from the images).

Used twice: with a fake model that answers exactly this (to test the plumbing on the real files), and by
the opt-in live test that asks the real model and compares (to test the model itself).
"""

from datetime import date
from typing import Any

from app.engine.invoices.types import ExtractedInvoice

# file name -> expected fields. `date` may be the invoice date or (for the order page) the order date.
# `vendor=None` marks the images that print NO vendor name (checked by looking at them, and seen in the
# first real run): they must come back as "needs a check, choose the vendor", never a guessed vendor.
# The vendor is never taken from the file name; a person chooses it (decision of 2026-10-15).
EXPECTED: dict[str, dict[str, Any]] = {
    "010626_DTDC_769.png": dict(vendor=None, total=76900, date=date(2026, 6, 1), number="F33356894"),
    "080626_DTDC_480.png": dict(vendor="dtdc", total=48000, date=date(2026, 6, 8), number="V1005162495"),
    "DTDC_1124.png": dict(vendor=None, total=112400, date=date(2026, 6, 10)),
    "DTDC_240.png": dict(vendor=None, total=24000, date=date(2026, 6, 12)),
    "DTDC_510.png": dict(vendor="dtdc", total=51000, date=date(2026, 6, 12)),
    "DTDC_522.png": dict(vendor="dtdc", total=52200, date=date(2026, 6, 16)),
    "DTDC_623.png": dict(vendor="dtdc", total=62300, date=date(2026, 6, 11)),
    "140626_Amazon_173.63.png": dict(
        vendor="amazon", total=17363, number="WBL7-21429", order="408-4442972-1434750", order_date=date(2026, 6, 14)
    ),
    "140626_Amazon_99.png": dict(
        vendor="amazon", total=9900, number="IN-11218383", order="408-2168147-1083564",
        order_date=date(2026, 6, 14), date=date(2026, 6, 22),
    ),
    "CLOUD.png": dict(vendor="google", total=100000, date=date(2026, 6, 8)),
    "Google_5000.png": dict(vendor="google", total=500000, date=date(2026, 6, 16)),
    "080626_thinkrobotics_124.99.png": dict(vendor=None, total=12499, date=date(2026, 6, 8), order="TR60380"),
}

# For the images with no printed vendor: the vendor a person chooses (used to test that choosing one works).
CHOSEN_BY_HAND = {
    "010626_DTDC_769.png": "dtdc",
    "DTDC_1124.png": "dtdc",
    "DTDC_240.png": "dtdc",
    "080626_thinkrobotics_124.99.png": "thinkrobotics",
}

# How each vendor's name is printed on its documents (what a model would read as the seller).
VENDOR_TEXT = {"dtdc": "DTDC Express Limited", "amazon": "Amazon.in", "google": "Google Cloud", "thinkrobotics": "ThinkRobotics"}


def mismatches(item: ExtractedInvoice, expected: dict[str, Any]) -> list[str]:
    """What differs between a reading and the expected values (empty when it matches)."""
    problems: list[str] = []

    def check(name: str, got: Any, want: Any) -> None:
        if got != want:
            problems.append(f"{name}: got {got!r}, expected {want!r}")

    no_vendor_printed = expected["vendor"] is None
    check("vendor", item.vendor_key, expected["vendor"])
    check("total", item.total_minor, expected["total"])
    if "number" in expected:
        check("invoice no", item.invoice_no, expected["number"])
    if "order" in expected:
        # the order page prints one reference: it may be read as the order id or as the number
        if expected["order"] not in (item.order_id, item.invoice_no):
            problems.append(f"order: got {item.order_id!r}/{item.invoice_no!r}, expected {expected['order']!r}")
    if "order_date" in expected:
        check("order date", item.order_date, expected["order_date"])
    if "date" in expected:
        got_dates = {item.invoice_date, item.order_date} if "order_date" not in expected else {item.invoice_date}
        if expected["date"] not in got_dates:
            problems.append(f"date: got {item.invoice_date}/{item.order_date}, expected {expected['date']}")
    if no_vendor_printed:
        # Flagged for a person, with the reason; everything else on the image must still be read.
        if item.extraction_status != "needs_check" or not any("does not show a vendor" in p for p in item.problems):
            problems.append(f"expected 'needs check: no vendor on the image', got {item.extraction_status}: {item.problems}")
    elif item.extraction_status != "ok":
        problems.append(f"status {item.extraction_status}: {item.problems}")
    return problems


def model_answer(expected: dict[str, Any]) -> str:
    """The JSON a perfect model would return for these expected values."""
    import json

    return json.dumps(
        {
            "vendor": VENDOR_TEXT[expected["vendor"]] if expected["vendor"] else None,
            "invoice_no": expected.get("number"),
            "order_id": expected.get("order"),
            "invoice_date": expected["date"].isoformat() if "date" in expected else None,
            "order_date": expected["order_date"].isoformat() if "order_date" in expected else None,
            "currency": "INR",
            "total": f"{expected['total'] // 100}.{expected['total'] % 100:02d}",
        }
    )
