"""The Excel export: gather the current state, build the workbook (engine/excel.py), record the export.

Orchestration only. The layout and the totals check are in `engine/excel.py`. Exporting is allowed any number
of times; the first one (and the first one after an edit) sets the cycle to `exported`.
"""

from datetime import date, datetime, timezone
from typing import Any

from app.engine.excel import (
    SheetLine,
    Statement,
    UnusedRow,
    build_workbook,
    check_totals,
    export_file_name,
    sheet_name_for,
)
from app.services.gates import ServiceError, require_confirmed_statement
from app.services.results import Data, unused_view
from app.services.run_matching import matching_job, summary_from_rows

SHEETS_AFTER_MONTH = ("Invoices not used",)


def _day(value: Any) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def _sheet_lines(data: Data) -> list[SheetLine]:
    """Every statement line with the file names of all its invoices (attached and suggested), sorted by name."""
    out = []
    for t in data.lines:
        names = sorted({data.file_name.get(data.invoices[m["invoice_id"]]["file_id"], "?")
                        for m in data.links.get(t["id"], []) if m["invoice_id"] in data.invoices})
        out.append(SheetLine(
            txn_date=_day(t["txn_date"]), ser_no=t["ser_no"], description=t["description"],
            amount_paise=int(t["amount_paise"]), is_credit=bool(t["is_credit"]),
            foreign_amount_minor=t.get("foreign_amount_minor"), foreign_currency=t.get("foreign_currency"),
            files=tuple(names), status=t.get("status"), note=t.get("notes") or "",
        ))
    return out


def _statement(cycle: dict[str, Any]) -> Statement:
    return Statement(
        debits_paise=cycle.get("summary_purchases_paise"), credits_paise=cycle.get("summary_credits_paise"),
        period_start=_day(cycle.get("period_start")), period_end=_day(cycle.get("period_end")),
    )


def _names(cycle: dict[str, Any]) -> tuple[str, str]:
    sheet = sheet_name_for(_day(cycle.get("statement_date")), cycle.get("label"))
    return sheet, export_file_name(sheet)


def require_exportable(cycle: dict[str, Any], data: Data) -> None:
    """Matching must have run (every line has a status) and must not be running now."""
    require_confirmed_statement(cycle)
    job = matching_job(cycle)
    if job and job["status"] == "running":
        raise ServiceError(409, "Matching is running. Export when it has finished")
    if not data.lines or any(not t.get("status") for t in data.lines):
        raise ServiceError(409, "Run matching first")


def edited_since_export(repo, cycle: dict[str, Any]) -> tuple[str | None, bool]:
    """(when it was last exported, whether it has been edited since). An export always leaves the status
    `exported`; the first edit after it moves the cycle back to `matched`."""
    if cycle["status"] not in ("matched", "exported"):
        return None, False
    when = repo.last_event_at(cycle["id"], "exported")
    return when, when is not None and cycle["status"] == "matched"


def export_summary(repo, cycle: dict[str, Any]) -> dict[str, Any]:
    """What the Export step shows before the download."""
    data = Data.load(repo, cycle["id"])
    if not data.lines or any(not t.get("status") for t in data.lines):
        raise ServiceError(409, "Run matching first")
    sheet, file_name = _names(cycle)
    lines = _sheet_lines(data)
    totals = check_totals(lines, _statement(cycle))
    summary = summary_from_rows(data.lines)
    counts = {s["status"]: s["count"] for s in summary["statuses"]}
    exported_at, edited = edited_since_export(repo, cycle)
    return {
        "sheet_name": sheet, "file_name": file_name, "sheets": ["Summary", sheet, *SHEETS_AFTER_MONTH],
        "lines": len(lines), "statuses": summary["statuses"],
        "needs_review": counts["Review"] + counts["Missing invoice"],
        "unused_invoices": unused_view(repo, cycle)["total"],
        "debits_paise": totals.debits_paise, "printed_debits_paise": totals.printed_debits_paise,
        "debits_difference_paise": totals.debits_difference_paise,
        "credits_paise": totals.credits_paise, "printed_credits_paise": totals.printed_credits_paise,
        "credits_difference_paise": totals.credits_difference_paise,
        "totals_ok": totals.ok,
        "last_exported_at": exported_at, "edited_since_export": edited,
    }


def build_export(repo, cycle: dict[str, Any], actor: str) -> tuple[bytes, str]:
    """The workbook for the current state. Records the export and sets the cycle to `exported`."""
    data = Data.load(repo, cycle["id"])
    require_exportable(cycle, data)
    sheet, file_name = _names(cycle)
    lines = _sheet_lines(data)
    unused = [
        UnusedRow(
            file_name=i["file_name"], vendor=i["vendor_name"] or "", when=_day(i["invoice_date"] or i["order_date"]),
            currency=i["currency"], total_minor=i["total_minor"], reason=i["reason"],
        )
        for i in unused_view(repo, cycle)["items"]
    ]
    content = build_workbook(sheet, lines, unused, _statement(cycle))
    if cycle["status"] != "exported":
        repo.update_cycle(cycle["id"], {"status": "exported"})
    counts = {s["status"]: s["count"] for s in summary_from_rows(data.lines)["statuses"]}
    repo.add_event(cycle["id"], actor, "exported", {
        "file": file_name, "lines": len(lines), "unused_invoices": len(unused), "by_status": counts,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    return content, file_name

