"""Small made-up Amazon Business reconciliation reports for tests (fake order numbers and amounts).
The real September report is covered by test_amazon_csv.py (Docker only)."""

import csv
import io

COLUMNS = [
    "Order Date", "Order ID", "Account Group", "Order payment method", "Payment Reference ID", "Payment Date",
    "Payment Identifier", "Shipment Quantity", "Net total",
]


def row(order="111-0000001-0000001", order_date="05/09/2026", method="Visa", ref="REF-A", paid="05/09/2026",
        card='="4002"', qty="1", net="100.00") -> dict[str, str]:
    return {
        "Order Date": order_date, "Order ID": order, "Account Group": "TEST", "Order payment method": method,
        "Payment Reference ID": ref, "Payment Date": paid, "Payment Identifier": card,
        "Shipment Quantity": qty, "Net total": net,
    }


def amazon_csv(*rows: dict[str, str], extra_columns: tuple[str, ...] = ()) -> bytes:
    """A report as bytes. With no rows given, one card-paid row (Visa 4002, ₹100.00)."""
    rows = rows or (row(),)
    columns = [*COLUMNS, *extra_columns]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: r.get(c, "") for c in columns})
    return out.getvalue().encode("utf-8")


GIFT = dict(method="Gift Certificate/Card", ref="GIFTREF", card="")
UNPAID = dict(method="", ref="", paid="N/A", card="", qty="0", net="")
