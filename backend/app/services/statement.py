"""Reading the statement PDF into lines, showing the result, and confirming it.

Orchestration only: the rules (line format, totals check) are in `engine/statement_icici.py`.
Reading runs as a background job. Its progress is kept on the cycle row (`job_status`, `job_progress`,
`job_message`), so the screen can poll it and a server restart can't leave it hanging for ever.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.engine.statement_icici import StatementCheck, check_totals, parse_statement, statement_label
from app.pdf import PdfToolUnavailable, pdf_text
from app.services.jobs import CLEARED, STATEMENT, job_fields

log = logging.getLogger("app.statement")

JOB_STALE_SECONDS = 180  # a "running" job that has not moved for this long is treated as dead
READABLE_STATUSES = ("draft", "statement_parsed")


class StatementError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _age_seconds(cycle: dict[str, Any], now: datetime) -> float:
    updated = datetime.fromisoformat(str(cycle["updated_at"]).replace("Z", "+00:00"))
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (now - updated).total_seconds()


def job_is_active(cycle: dict[str, Any], now: datetime) -> bool:
    return cycle.get("job_status") == "running" and _age_seconds(cycle, now) < JOB_STALE_SECONDS


def statement_file(repo, cycle_id: str) -> dict[str, Any] | None:
    rows = [f for f in repo.live_files(cycle_id) if f["kind"] == "statement" and f.get("storage_path")]
    return rows[0] if rows else None


def start_parse(repo, cycle: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Checks that a read may start, marks the job as running and returns the statement file row."""
    now = now or datetime.now(timezone.utc)
    if cycle["status"] not in READABLE_STATUSES:
        raise StatementError(409, "The statement is already confirmed; it can't be read again")
    if job_is_active(cycle, now):
        raise StatementError(409, "The statement is already being read")
    file = statement_file(repo, cycle["id"])
    if file is None:
        raise StatementError(409, "Upload the statement first")
    repo.update_cycle(cycle["id"], job_fields(STATEMENT, "running", 0, "Starting…"))
    return file


def run_parse(
    *,
    repo,
    storage,
    cycle_id: str,
    file: dict[str, Any],
    actor: str,
    extract_text: Callable[[bytes], str] | None = None,
) -> None:
    """The background job. Never raises: any failure is recorded on the cycle as `job_status = failed`.

    Lines are saved only when every line could be read and the serial numbers are unique. A totals
    mismatch is saved too (so it can be shown), but the statement then can't be confirmed.
    """
    extract = extract_text or (lambda data: pdf_text(data, last_page=None, timeout=90))
    saving = False

    def progress(pct: int, message: str) -> None:
        repo.update_cycle(cycle_id, job_fields(STATEMENT, "running", pct, message))

    def fail(message: str) -> None:
        repo.update_cycle(cycle_id, job_fields(STATEMENT, "failed", None, message))

    try:
        progress(10, "Opening the statement…")
        data = storage.get(file["storage_path"])
        progress(30, "Reading the PDF text…")
        text = extract(data)
        if not text.strip():
            fail("The PDF has no readable text. Download the statement PDF again from net banking; photos aren't supported.")
            return
        progress(60, "Reading the transaction lines…")
        parsed = parse_statement(text)
        problems = parsed.errors()
        if problems:
            fail(" ".join(problems))
            return

        progress(80, f"Saving {len(parsed.lines)} lines…")
        saving = True
        repo.replace_transactions(
            cycle_id,
            [
                {
                    "cycle_id": cycle_id,
                    "ser_no": x.ser_no,
                    "txn_date": x.txn_date.isoformat(),
                    "card_last4": x.card_last4,
                    "description": x.description,
                    "reward_points": x.reward_points,
                    "foreign_amount_minor": x.foreign_amount_minor,
                    "foreign_currency": x.foreign_currency,
                    "amount_paise": x.amount_paise,
                    "is_credit": x.is_credit,
                    "sort_order": x.sort_order,
                }
                for x in parsed.lines
            ],
        )
        check = parsed.check()
        current = repo.get_cycle(cycle_id) or {}
        new_label = {} if current.get("label") else {"label": statement_label(parsed.statement_date)}
        repo.update_cycle(
            cycle_id,
            {
                **new_label,
                "status": "statement_parsed",
                "statement_date": parsed.statement_date.isoformat() if parsed.statement_date else None,
                "period_start": parsed.period_start.isoformat() if parsed.period_start else None,
                "period_end": parsed.period_end.isoformat() if parsed.period_end else None,
                "summary_previous_paise": parsed.previous_paise,
                # Stored as Purchases/Charges + Cash Advances (what the debit lines must add up to).
                "summary_purchases_paise": parsed.printed_debits_paise,
                "summary_credits_paise": parsed.credits_paise,
                "summary_total_due_paise": parsed.total_due_paise,
                "statement_confirmed_at": None,
                "statement_confirmed_by": None,
                **job_fields(STATEMENT, "done", 100, f"Statement read: {len(parsed.lines)} lines"),
            },
        )
        repo.add_event(cycle_id, actor, "statement_parsed", {"lines": len(parsed.lines), "totals_match": check.ok})
    except PdfToolUnavailable:
        log.error("pdftotext is not installed; run the API in Docker")
        fail("Reading PDFs needs poppler, which isn't installed on the server. Run the API in Docker.")
    except Exception:  # noqa: BLE001 - recorded on the cycle; the screen shows it
        log.exception("Reading the statement of cycle %s failed", cycle_id)
        if saving:
            try:
                repo.reset_statement(cycle_id)  # never leave half a statement behind
            except Exception:  # noqa: BLE001
                log.exception("Could not clear the partly saved statement of cycle %s", cycle_id)
        fail("Couldn't read the statement. Please try again.")


def check_from_rows(cycle: dict[str, Any], rows: list[dict[str, Any]]) -> StatementCheck:
    """The totals check, recomputed from what is saved (so it can never disagree with the data)."""
    return check_totals(
        line_count=len(rows),
        debits_paise=sum(r["amount_paise"] for r in rows if not r["is_credit"]),
        credits_paise=sum(r["amount_paise"] for r in rows if r["is_credit"]),
        printed_debits_paise=cycle.get("summary_purchases_paise"),
        printed_credits_paise=cycle.get("summary_credits_paise"),
        cards=[r["card_last4"] for r in rows if r.get("card_last4")],
    )


def statement_view(repo, cycle: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    rows = repo.list_transactions(cycle["id"])
    job = None
    # The job columns are shared with invoice reading, which only runs once the statement is confirmed.
    if cycle.get("job_status") and cycle["status"] in READABLE_STATUSES:
        job = {"status": cycle["job_status"], "progress": cycle.get("job_progress"), "message": cycle.get("job_message")}
        if job["status"] == "running" and not job_is_active(cycle, now):
            job = {"status": "failed", "progress": None, "message": "Reading stopped unexpectedly. Please try again."}
    check = check_from_rows(cycle, rows) if rows else None
    return {
        "status": cycle["status"],
        "statement_date": cycle.get("statement_date"),
        "period_start": cycle.get("period_start"),
        "period_end": cycle.get("period_end"),
        "summary": {
            "previous_paise": cycle.get("summary_previous_paise"),
            "purchases_paise": cycle.get("summary_purchases_paise"),
            "credits_paise": cycle.get("summary_credits_paise"),
            "total_due_paise": cycle.get("summary_total_due_paise"),
        },
        "job": job,
        "check": None
        if check is None
        else {
            "lines": check.lines,
            "debits_paise": check.debits_paise,
            "credits_paise": check.credits_paise,
            "printed_debits_paise": check.printed_debits_paise,
            "printed_credits_paise": check.printed_credits_paise,
            "debits_ok": check.debits_ok,
            "credits_ok": check.credits_ok,
            "debits_difference_paise": None
            if check.printed_debits_paise is None
            else check.debits_paise - check.printed_debits_paise,
            "credits_difference_paise": None
            if check.printed_credits_paise is None
            else check.credits_paise - check.printed_credits_paise,
            "cards": list(check.cards),
            "ok": check.ok,
            "problems": list(check.problems),
        },
        "confirmed_at": cycle.get("statement_confirmed_at"),
        "confirmed_by": cycle.get("statement_confirmed_by"),
        "lines": rows,
    }


def confirm_statement(repo, cycle: dict[str, Any], actor: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    if cycle["status"] == "statement_confirmed":
        raise StatementError(409, "The statement is already confirmed")
    if cycle["status"] != "statement_parsed":
        raise StatementError(409, "Read the statement before confirming it")
    check = check_from_rows(cycle, repo.list_transactions(cycle["id"]))
    if not check.ok:
        raise StatementError(409, f"The statement can't be confirmed: {check.problems[0]}")
    repo.update_cycle(
        cycle["id"],
        {
            "status": "statement_confirmed",
            "statement_confirmed_at": now.isoformat(),
            "statement_confirmed_by": actor,
            **CLEARED,  # the statement's job is over; invoice reading starts from a clean slate
        },
    )
    repo.add_event(cycle["id"], actor, "statement_confirmed", {"lines": check.lines})
