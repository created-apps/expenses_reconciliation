"""The "Amazon invoices to fetch" list: orders of the Amazon Business report with no invoice uploaded.

Orchestration only. Which group pays which charge, and the counts, are decided in `engine/amazon_fetch.py` by
the same functions the matcher uses, from what is saved (statement lines, invoices, the report's rows), so
nothing new is stored. Works only when a report is uploaded and matching has run.
"""

from collections import defaultdict
from datetime import date
from typing import Any

from app.engine.amazon_fetch import order_amounts, orders_to_fetch, report_coverage
from app.engine.invoices.validate import order_id_problem
from app.engine.matcher import Txn
from app.services.amazon_report import live_report_file, payment_range, report_from_rows, report_rows
from app.services.run_matching import _parallel, pinned_lines

# Lines the rules 1 to 4 decide (reversals, fees, payments, credits): the report never sees them.
DECIDED_BY_RULES = ("Reversed", "Bank charge", "Payment", "Credit – manual")


def _day(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def amazon_to_fetch(repo, cycle: dict[str, Any]) -> dict[str, Any]:
    cid = cycle["id"]
    lines, invoices, matches, files, records = _parallel(
        lambda: repo.list_transactions(cid),
        lambda: repo.list_invoices(cid),
        lambda: repo.list_matches(cid),
        lambda: repo.list_files(cid),
        lambda: repo.list_amazon_rows(cid),
    )
    empty: dict[str, Any] = {
        "has_report": False, "matched": False, "payment_date_from": None, "payment_date_to": None, "coverage": None,
        "items": [], "total_orders": 0, "total_paise": 0, "invoices_without_order_id": 0,
    }
    file = live_report_file(files)
    if file is None:
        return empty

    rows = report_rows(records, file["id"])
    span = payment_range(rows)
    amazon = [
        i for i in invoices
        if i.get("vendor_key") == "amazon" and not i.get("duplicate_of") and not i.get("is_credit_note")
    ]
    totals: dict[str, int] = defaultdict(int)
    for i in amazon:
        if i.get("order_id"):
            totals[i["order_id"]] += int(i.get("total_minor") or 0) if (i.get("currency") or "INR") == "INR" else 0
    out = {
        **empty, "has_report": True,
        "payment_date_from": span[0] if span else None, "payment_date_to": span[1] if span else None,
        "coverage": report_coverage(rows, totals).__dict__,
        "invoices_without_order_id": sum(1 for i in amazon if order_id_problem("amazon", i.get("order_id"))),
    }
    report = report_from_rows(rows)
    ran = bool(lines) and all(t.get("status") for t in lines)
    if report is None or not ran:
        return out | {"matched": ran}

    ordered = sorted(lines, key=lambda t: (t.get("sort_order") or 0, t["ser_no"]))
    pinned = {p.ser_no for p in pinned_lines(ordered, matches)}
    charges = {
        t["id"]: t for t in ordered
        if t.get("vendor_key") == "amazon" and not t["is_credit"] and t.get("status") not in DECIDED_BY_RULES
        and t["ser_no"] not in pinned
    }
    txns = [
        Txn(id=t["id"], ser_no=t["ser_no"], date=_day(t["txn_date"]), description=t["description"],
            amount_paise=int(t["amount_paise"]), is_credit=False, card_last4=t.get("card_last4"))
        for t in charges.values()
    ]
    fetch = orders_to_fetch(txns, report, order_amounts(rows), set(totals))
    fetch.sort(key=lambda o: (o.charge_date, o.charge_amount_paise, o.order_id))
    items = [
        {
            "order_id": o.order_id, "payment_date": o.payment_date, "amount_paise": o.amount_paise,
            "group_reference": o.group_reference, "transaction_id": o.txn_id, "ser_no": o.ser_no,
            "charge_date": o.charge_date, "charge_amount_paise": o.charge_amount_paise, "description": o.description,
        }
        for o in fetch
    ]
    return out | {"matched": True, "items": items, "total_orders": len(items), "total_paise": sum(o.amount_paise for o in fetch)}
