"""Running the matcher on a cycle: load, decide (engine), save.

Orchestration only: every decision is in `engine/matcher.py`. A run replaces what the system decided
before and keeps what a person decided: links with `created_by` set stay, and lines a person changed
(`updated_by` set) are left exactly as they are.

A run is a background job (the same pattern as reading invoices): its progress is kept on the cycle row
(`job_status`, `job_progress`, `job_message`) and the screen polls it. Every message of this job starts with
"Matching", which is how the screens tell it from the reading jobs that share those columns. Each call to
the database costs about half a second from a laptop, so a run reads in parallel and writes in bulk.
"""

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any

from app.engine.matcher import Inv, LineResult, Pinned, Txn, Vendor, match
from app.services.amazon_report import matching_report
from app.services.gates import ServiceError, require_confirmed_statement
from app.services.jobs import MATCHING, job_fields
from app.services.statement import job_is_active

log = logging.getLogger("app.matching")

STATUS_ORDER = (
    "Matched", "Review", "Missing invoice", "No invoice", "Reversed", "Credit – manual", "Payment", "Bank charge",
)
JOB_PREFIX = "Matching"  # the start of the messages people read; the job is told apart by `job_kind`
STALE_MESSAGE = "Matching stopped unexpectedly. Please try again."
FAILED_MESSAGE = "Matching didn't finish. Please try again."


def _day(value: Any) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def _tuple(value: Any) -> tuple[int, ...]:
    return tuple(int(v) for v in (value or []))


def _parallel(*calls):
    """Run independent database reads at the same time; results come back in the order given."""
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(c) for c in calls]
        return [f.result() for f in futures]


def load_inputs(repo, cycle_id: str):
    """Everything a run reads, fetched in parallel: lines, invoices, vendors, existing links, the Amazon report."""
    lines, invoice_rows, aliases, existing, report = _parallel(
        lambda: repo.list_transactions(cycle_id),
        lambda: repo.list_invoices(cycle_id),
        lambda: repo.list_vendor_aliases(),
        lambda: repo.list_matches(cycle_id),
        lambda: matching_report(repo, cycle_id),
    )
    return lines, invoice_rows, aliases, existing, report


def engine_values(lines, invoice_rows, aliases):
    """Database rows as the plain values the engine takes."""
    rows = sorted(lines, key=lambda t: (t.get("sort_order") or 0, t["ser_no"]))
    txns = [
        Txn(
            id=t["id"], ser_no=t["ser_no"], date=_day(t["txn_date"]), description=t["description"],
            amount_paise=int(t["amount_paise"]), is_credit=bool(t["is_credit"]), card_last4=t.get("card_last4"),
            foreign_amount_minor=t.get("foreign_amount_minor"), foreign_currency=t.get("foreign_currency"),
        )
        for t in rows
    ]
    invoices = [
        Inv(
            id=i["id"], vendor_key=i.get("vendor_key"), currency=i.get("currency") or "INR",
            total_minor=i.get("total_minor"), amounts_minor=_tuple(i.get("amounts_minor")),
            invoice_date=_day(i.get("invoice_date")), order_date=_day(i.get("order_date")), order_id=i.get("order_id"),
            is_credit_note=bool(i.get("is_credit_note")), duplicate_of=i.get("duplicate_of"),
            pnr=(i.get("extra") or {}).get("pnr"), usd_amounts_minor=_tuple((i.get("extra") or {}).get("usd_amounts_minor")),
        )
        for i in invoice_rows
    ]
    vendors = [
        Vendor(
            key=a["vendor_key"], display_name=a["display_name"], statement_pattern=a.get("statement_pattern"),
            match_mode=a["match_mode"], before_days=a["date_before_days"], after_days=a["date_after_days"],
        )
        for a in aliases
    ]
    return rows, txns, invoices, vendors


def pinned_lines(rows: list[dict[str, Any]], matches: list[dict[str, Any]]) -> list[Pinned]:
    """Lines a person decided: they changed the line (`updated_by`) or made a link (`created_by`)."""
    manual: dict[str, list[str]] = {}
    for m in matches:
        if m.get("created_by"):
            manual.setdefault(m["transaction_id"], []).append(m["invoice_id"])
    return [
        Pinned(t["ser_no"], tuple(manual.get(t["id"], ())))
        for t in rows
        if t.get("updated_by") or t["id"] in manual
    ]


# -- the job's state on the cycle row ------------------------------------------------------------------------
def is_matching_job(cycle: dict[str, Any]) -> bool:
    return bool(cycle.get("job_status")) and cycle.get("job_kind") == MATCHING


def matching_job(cycle: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    """The matching job as the screen sees it, or None. A run that has not moved for 3 minutes shows as failed."""
    if not is_matching_job(cycle):
        return None
    job = {"status": cycle["job_status"], "progress": cycle.get("job_progress"), "message": cycle.get("job_message")}
    if job["status"] == "running" and not job_is_active(cycle, now or datetime.now(timezone.utc)):
        return {"status": "failed", "progress": None, "message": STALE_MESSAGE}
    return job


def start_matching(repo, cycle: dict[str, Any], now: datetime | None = None) -> None:
    """The 409 gate (statement confirmed) and the 'already running' guard; marks the run as started."""
    now = now or datetime.now(timezone.utc)
    require_confirmed_statement(cycle)
    if job_is_active(cycle, now):
        raise ServiceError(409, "Something is already running for this reconciliation")
    repo.update_cycle(cycle["id"], job_fields(MATCHING, "running", 0, f"{JOB_PREFIX}…"))


def run_matching(repo, cycle: dict[str, Any], actor: str) -> dict[str, Any] | None:
    """The background job: match every line. Call `start_matching` first.

    Never raises: a failure is recorded on the cycle (`job_status = failed`, so the lock is released and the
    screen shows the message) and None is returned. On success the summary of the run is returned.
    """
    cycle_id = cycle["id"]

    def progress(pct: int, message: str) -> None:
        repo.update_cycle(cycle_id, job_fields(MATCHING, "running", pct, message))

    try:
        lines, invoice_rows, aliases, existing, report = load_inputs(repo, cycle_id)
        rows, txns, invoices, vendors = engine_values(lines, invoice_rows, aliases)
        progress(30, f"Matching {len(txns)} lines against {len(invoices)} invoices…")
        results = match(txns, invoices, vendors, csv=report, pinned=pinned_lines(rows, existing))
        progress(60, "Matching… saving the results")
        save_results(repo, cycle_id, rows, results)
        summary = summary_from_rows(apply_results(rows, results))
        counts = {s["status"]: s["count"] for s in summary["statuses"]}
        fields: dict[str, Any] = job_fields(
            MATCHING, "done", 100, f"{JOB_PREFIX} finished: {counts['Matched']} matched, {counts['Review']} to review"
        )
        if cycle.get("status") in ("statement_confirmed", "invoices_extracted"):
            fields["status"] = "matched"
        repo.update_cycle(cycle_id, fields)
        repo.add_event(cycle_id, actor, "matching_run", {"lines": summary["total"], "by_status": counts})
        return summary
    except Exception:
        log.exception("Matching cycle %s failed", cycle_id)
        try:
            repo.update_cycle(cycle_id, job_fields(MATCHING, "failed", None, FAILED_MESSAGE))
        except Exception:
            log.exception("Could not record the failed run of cycle %s", cycle_id)
        return None


def save_results(repo, cycle_id: str, rows: list[dict[str, Any]], results: list[LineResult]) -> None:
    """Replace the system's links and write each decided line's status, vendor and reason: two writes in
    parallel (the new links, and all the lines in one bulk call). Lines a person decided are not touched."""
    by_id = {t["id"]: t for t in rows}
    decided = [r for r in results if not r.pinned]
    links = [
        {
            "cycle_id": cycle_id, "transaction_id": r.txn_id, "invoice_id": link.invoice_id,
            "rule": link.rule, "is_suggestion": link.is_suggestion, "created_by": None,
        }
        for r in decided
        for link in r.links
    ]
    updates = [
        {
            "id": r.txn_id, "cycle_id": cycle_id, "ser_no": by_id[r.txn_id]["ser_no"],
            "txn_date": by_id[r.txn_id]["txn_date"], "description": by_id[r.txn_id]["description"],
            "amount_paise": by_id[r.txn_id]["amount_paise"],
            "status": r.status, "vendor_key": r.vendor_key, "notes": r.note,
        }
        for r in decided
    ]
    repo.delete_system_matches(cycle_id)
    _parallel(lambda: repo.insert_matches(links), lambda: repo.update_transactions(updates))


def apply_results(rows: list[dict[str, Any]], results: list[LineResult]) -> list[dict[str, Any]]:
    """The lines as they are after the run (a person's lines keep what they had)."""
    decided = {r.txn_id: r for r in results if not r.pinned}
    return [{**t, "status": decided[t["id"]].status} if t["id"] in decided else t for t in rows]


# -- the summary ------------------------------------------------------------------------------------------------
def summary_from_rows(rows: list[dict[str, Any]], job: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lines and signed amounts (credits negative) by status; `ran` is false before the first run."""
    count: Counter[str] = Counter()
    amount: Counter[str] = Counter()
    for t in rows:
        if not t.get("status"):
            continue
        count[t["status"]] += 1
        amount[t["status"]] += -int(t["amount_paise"]) if t["is_credit"] else int(t["amount_paise"])
    return {
        "ran": bool(count),
        "total": len(rows),
        "statuses": [{"status": s, "count": count[s], "amount_paise": amount[s]} for s in STATUS_ORDER],
        "job": job,
    }


def match_summary(repo, cycle_id: str, cycle: dict[str, Any] | None = None) -> dict[str, Any]:
    return summary_from_rows(repo.list_transactions(cycle_id), matching_job(cycle) if cycle else None)
