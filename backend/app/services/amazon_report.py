"""The Amazon Business report of a cycle, as the Invoices step shows it (built from the saved rows)."""

from datetime import date
from typing import Any

from app.engine.amazon_csv import AmazonRow, card_groups, gift_orders


def _day(value: Any) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def _row(r: dict[str, Any]) -> AmazonRow:
    return AmazonRow(
        order_id=r.get("order_id"),
        order_date=_day(r.get("order_date")),
        payment_ref=r.get("payment_ref"),
        payment_date=_day(r.get("payment_date")),
        payment_method=r.get("payment_method"),
        card_last4=r.get("card_last4"),
        shipment_qty=r.get("shipment_qty"),
        net_total_paise=int(r.get("net_total_paise") or 0),
    )


def payment_range(rows: list[AmazonRow]) -> tuple[date, date] | None:
    """The first and last payment date in the report (every row with one, gift balance included)."""
    dates = [r.payment_date for r in rows if r.payment_date]
    return (min(dates), max(dates)) if dates else None


def live_report_file(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The stored Amazon report of a cycle (a new report replaces the old one), or None."""
    return next((f for f in files if f["kind"] == "amazon_report" and f["status"] == "uploaded"), None)


def report_rows(records: list[dict[str, Any]], file_id: str) -> list[AmazonRow]:
    """The saved rows of one report file as the engine reads them."""
    return [_row(r) for r in records if r["file_id"] == file_id]


def report_from_rows(rows: list[AmazonRow]):
    """The report as the matcher needs it (card groups and the payment-date range), or None."""
    from app.engine.matcher import CsvGroup, CsvReport

    span = payment_range(rows)
    if span is None:
        return None  # no payment dates: it can't say which debits it covers
    groups = tuple(
        CsvGroup(g.payment_ref, g.payment_date, g.card_last4, g.order_ids, g.amount_paise) for g in card_groups(rows)
    )
    return CsvReport(payment_from=span[0], payment_to=span[1], groups=groups)


def matching_report(repo, cycle_id: str):
    """The report as the matcher needs it (card groups and the payment-date range), or None."""
    file = live_report_file(repo.list_files(cycle_id))
    if file is None:
        return None
    return report_from_rows(report_rows(repo.list_amazon_rows(cycle_id), file["id"]))


def report_view(repo, cycle_id: str) -> dict[str, Any]:
    """Groups, gift orders and counts from the saved rows; `file` is None when no report is uploaded."""
    files = [f for f in repo.list_files(cycle_id) if f["kind"] == "amazon_report" and f["status"] == "uploaded"]
    if not files:
        return {
            "file": None, "rows": 0, "unpaid_rows": 0, "card_last4s": [], "payment_date_from": None,
            "payment_date_to": None, "groups": [], "gift": [],
        }
    file = files[0]
    rows = [_row(r) for r in repo.list_amazon_rows(cycle_id) if r["file_id"] == file["id"]]
    groups = card_groups(rows)
    span = payment_range(rows)
    return {
        "file": {"id": file["id"], "name": file["original_name"], "has_copy": bool(file.get("storage_path"))},
        "rows": len(rows),
        # rows with no payment method and no reference: ordered but not paid or not shipped
        "unpaid_rows": sum(1 for r in rows if not r.payment_method),
        "card_last4s": sorted({g.card_last4 for g in groups if g.card_last4}),
        "payment_date_from": span[0] if span else None,
        "payment_date_to": span[1] if span else None,
        "groups": [
            {
                "payment_date": g.payment_date, "reference": g.payment_ref, "card_last4": g.card_last4,
                "orders": g.orders, "amount_paise": g.amount_paise,
            }
            for g in groups
        ],
        "gift": [{"paid_on": g.paid_on, "order_id": g.order_id, "amount_paise": g.amount_paise} for g in gift_orders(rows)],
    }
