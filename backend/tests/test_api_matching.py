"""POST /match and GET /match-summary, and what a run does to the saved data (fakes for the database,
storage and PDF reader; the engine itself is tested in test_matcher*.py)."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.db import get_repo
from app.engine.matcher import match as real_match
from app.main import app
from app.services import run_matching as service
from app.services.gates import ServiceError
from app.services.statement import JOB_STALE_SECONDS
from app.services.vision_client import get_vision
from app.storage import get_storage
from fakes import FakeRepo, FakeStorage

USER = CurrentUser(email="harsh@create-ed.in", user_id="u1")
STATEMENT_PDF = b"%PDF statement"
MACFOS = b"%PDF macfos"
LEFTOVER = b"%PDF leftover"

MACFOS_TEXT = "MACFOS LIMITED\nTax invoice\nInvoice# INV2627/1\nInvoice Date:   Sale Order:\n08/06/2026   111\nTotal   ₹ 422.00\n"
LEFTOVER_TEXT = "MACFOS LIMITED\nTax invoice\nInvoice# INV2627/2\nInvoice Date:   Sale Order:\n09/06/2026   222\nTotal   ₹ 999.00\n"

# A statement (made-up merchants, fake serial numbers) in the layout the reader expects.
STATEMENT_TEXT = "\n".join([
    "CREDIT CARD STATEMENT",
    "   STATEMENT DATE", "   June 28, 2026",
    "  Statement period : May 21, 2026 to June 28, 2026",
    "   STATEMENT SUMMARY",
    "   `1,000.00     `100.00     `481.29     `0.00     `50.00",
    "Date        SerNo.      Transaction Details       Reward Points   Intl.# amount   Amount (in`)",
    "0000XXXXXXXX1111",
    "08/06/2026   10000000001   MACFOS LIMITED MUMBAI IN         8                   422.00",
    "10/06/2026   10000000002   DCC Fee                          0                    59.29",
    "11/06/2026   10000000003   SOME CAFE MUMBAI IN              2                     0.00",
    "12/06/2026   10000000004   CLICK TO PAY PAYMENT RECEIVED    0                    50.00 CR",
])


@pytest.fixture
def api(monkeypatch):
    repo, storage = FakeRepo(), FakeStorage()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_vision] = lambda: None
    monkeypatch.setattr("app.services.statement.pdf_text", lambda data, **kw: STATEMENT_TEXT)
    monkeypatch.setattr("app.services.ingest.pdf_text", lambda data, **kw: "Tax invoice")
    monkeypatch.setattr("app.services.invoices.pdf_text", lambda data, **kw: {MACFOS: MACFOS_TEXT, LEFTOVER: LEFTOVER_TEXT}[data])
    client = TestClient(app)
    client.repo, client.storage = repo, storage
    yield client
    app.dependency_overrides.clear()


def cycle(api, *, parse=True, confirm=True, read=True):
    cid = api.post("/api/cycles").json()["id"]
    files = [("files", ("CC.pdf", STATEMENT_PDF, "application/pdf"))]
    assert api.post(f"/api/cycles/{cid}/files", data={"kind": "statement"}, files=files).status_code == 200
    invoices = [("files", ("macfos.pdf", MACFOS, "application/pdf")), ("files", ("leftover.pdf", LEFTOVER, "application/pdf"))]
    assert api.post(f"/api/cycles/{cid}/files", data={"kind": "invoices"}, files=invoices).status_code == 200
    if parse:
        assert api.post(f"/api/cycles/{cid}/statement/parse").status_code == 202
    if confirm:
        assert api.post(f"/api/cycles/{cid}/statement/confirm").status_code == 200
    if read:
        assert api.post(f"/api/cycles/{cid}/invoices/extract").status_code == 202
    return cid


def counts(summary):
    return {s["status"]: s["count"] for s in summary["statuses"]}


def run(api, cid):
    """Start a run (202) and read the result. The background job has finished when the response returns."""
    r = api.post(f"/api/cycles/{cid}/match")
    assert r.status_code == 202, r.text
    assert r.json()["job"]["status"] == "running"  # what the screen sees at the start
    summary = api.get(f"/api/cycles/{cid}/match-summary").json()
    assert summary["job"]["status"] == "done", summary["job"]
    return summary


# ---- The 409 gate (carry-forward from Slice 5) -------------------------------------------------------------------------
def test_matching_needs_a_token():
    client = TestClient(app)
    nil = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
    assert client.post(f"/api/cycles/{nil}/match").status_code == 401
    assert client.get(f"/api/cycles/{nil}/match-summary").status_code == 401


def test_matching_is_refused_on_a_draft_cycle(api):
    cid = cycle(api, parse=False, confirm=False, read=False)
    r = api.post(f"/api/cycles/{cid}/match")
    assert r.status_code == 409 and "Confirm the statement" in r.json()["detail"]
    assert api.repo.matches == [] and api.repo.cycles[cid]["job_status"] is None  # nothing started, nothing written


def test_matching_is_refused_when_the_statement_is_read_but_not_confirmed(api):
    cid = cycle(api, confirm=False, read=False)
    assert api.get(f"/api/cycles/{cid}").json()["status"] == "statement_parsed"
    assert api.post(f"/api/cycles/{cid}/match").status_code == 409
    assert all(t["status"] is None for t in api.repo.transactions)  # no line was touched


def test_matching_again_after_an_export_is_an_edit_that_moves_the_cycle_back_to_matched(api):
    cid = cycle(api)
    api.repo.cycles[cid]["status"] = "exported"
    summary = run(api, cid)
    assert summary["ran"] and api.repo.cycles[cid]["status"] == "matched"
    assert [e["action"] for e in api.repo.events].count("edited_after_export") == 1


def test_unknown_cycle_is_404(api):
    nil = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
    assert api.post(f"/api/cycles/{nil}/match").status_code == 404
    assert api.get(f"/api/cycles/{nil}/match-summary").status_code == 404


def test_a_second_run_while_one_is_in_progress_is_refused(api):
    cid = cycle(api)
    api.repo.update_cycle(cid, {"job_status": "running", "job_progress": 0, "job_message": "Matching…"})
    r = api.post(f"/api/cycles/{cid}/match")
    assert r.status_code == 409 and "already running" in r.json()["detail"]


# ---- A run ---------------------------------------------------------------------------------------------------------------------
def test_before_matching_the_summary_is_empty_but_lists_all_eight_statuses(api):
    cid = cycle(api, read=False)
    summary = api.get(f"/api/cycles/{cid}/match-summary").json()
    assert summary["ran"] is False and summary["total"] == 4
    assert [s["status"] for s in summary["statuses"]] == [
        "Matched", "Review", "Missing invoice", "No invoice", "Reversed", "Credit – manual", "Payment", "Bank charge",
    ]
    assert all(s["count"] == 0 and s["amount_paise"] == 0 for s in summary["statuses"])


def test_a_run_saves_statuses_notes_and_links_and_moves_the_cycle_to_matched(api):
    cid = cycle(api)
    summary = run(api, cid)
    assert summary["ran"] and summary["total"] == 4
    assert counts(summary) == {"Matched": 1, "Review": 0, "Missing invoice": 0, "No invoice": 1, "Reversed": 0,
                               "Credit – manual": 0, "Payment": 1, "Bank charge": 1}
    # Amounts are signed: a credit counts negative.
    amounts = {s["status"]: s["amount_paise"] for s in summary["statuses"]}
    assert amounts["Matched"] == 42200 and amounts["Payment"] == -5000 and amounts["Bank charge"] == 5929

    lines = {t["ser_no"]: t for t in api.repo.transactions}
    assert lines["10000000001"]["status"] == "Matched" and lines["10000000001"]["vendor_key"] == "macfos"
    assert lines["10000000001"]["notes"] == "Exact INR amount"
    assert lines["10000000002"]["status"] == "Bank charge" and lines["10000000003"]["status"] == "No invoice"
    assert lines["10000000004"]["status"] == "Payment"
    (link,) = api.repo.matches
    assert link["transaction_id"] == lines["10000000001"]["id"] and link["created_by"] is None and not link["is_suggestion"]
    assert api.get(f"/api/cycles/{cid}").json()["status"] == "matched"
    assert api.get(f"/api/cycles/{cid}/match-summary").json() == summary
    cycle_row = api.repo.cycles[cid]
    assert (cycle_row["job_status"], cycle_row["job_progress"]) == ("done", 100)  # finished: not "running", so no lock
    assert cycle_row["job_message"] == "Matching finished: 1 matched, 0 to review"
    assert summary["job"] == {"status": "done", "progress": 100, "message": "Matching finished: 1 matched, 0 to review"}
    assert [e["action"] for e in api.repo.events if e["action"] == "matching_run"] == ["matching_run"]


def test_a_run_writes_all_the_lines_in_one_bulk_call_not_one_call_per_line(api):
    cid = cycle(api)
    run(api, cid)
    assert api.repo.bulk_calls == 1  # 4 lines, 1 write (June's 127 lines are also 1, up to 200 per call)


def test_a_bulk_write_changes_only_the_columns_it_sends(api):
    cid = cycle(api)
    before = {t["ser_no"]: dict(t) for t in api.repo.transactions}
    run(api, cid)
    for t in api.repo.transactions:
        for column in ("description", "amount_paise", "txn_date", "card_last4", "is_credit", "foreign_amount_minor"):
            assert t.get(column) == before[t["ser_no"]].get(column)


def test_the_progress_messages_all_start_with_matching_and_end_in_a_finished_message(api, monkeypatch):
    cid = cycle(api)
    seen: list[tuple[str | None, int | None, str | None]] = []
    original = api.repo.update_cycle

    def spy(cycle_id, fields):
        if "job_message" in fields:
            seen.append((fields.get("job_status"), fields.get("job_progress"), fields.get("job_message")))
        original(cycle_id, fields)

    monkeypatch.setattr(api.repo, "update_cycle", spy)
    run(api, cid)
    assert [s[0] for s in seen] == ["running", "running", "running", "done"]
    assert [s[1] for s in seen] == [0, 30, 60, 100]  # moves forward
    assert all(s[2].startswith("Matching") for s in seen)


def test_matching_works_before_any_invoice_is_read_everything_is_just_missing(api):
    cid = cycle(api, read=False)
    summary = run(api, cid)
    assert counts(summary)["Matched"] == 0 and counts(summary)["Missing invoice"] == 1  # the Macfos line


def test_running_twice_gives_the_same_result_and_does_not_pile_up_links(api):
    cid = cycle(api)
    first = run(api, cid)
    links_before = [(m["transaction_id"], m["invoice_id"]) for m in api.repo.matches]
    second = run(api, cid)
    assert second["statuses"] == first["statuses"]
    assert [(m["transaction_id"], m["invoice_id"]) for m in api.repo.matches] == links_before


# ---- What a person decided survives a re-run (carry-forward) ---------------------------------------------------------------------
def test_a_hand_made_link_and_a_hand_edited_line_survive_a_re_run(api):
    cid = cycle(api)
    run(api, cid)
    lines = {t["ser_no"]: t for t in api.repo.transactions}
    leftover =next(i for i in api.repo.list_invoices(cid) if i["total_minor"] == 99900)

    # A person attaches the leftover invoice to the cafe line and writes a note, and changes another line.
    cafe = lines["10000000003"]
    api.repo.matches.append({"id": "manual-1", "cycle_id": cid, "transaction_id": cafe["id"], "invoice_id": leftover["id"],
                             "rule": "manual", "is_suggestion": False, "created_by": "harsh@create-ed.in"})
    api.repo.update_transaction(cafe["id"], {"status": "Matched", "notes": "attached by hand", "updated_by": "harsh@create-ed.in"})
    fee = lines["10000000002"]
    api.repo.update_transaction(fee["id"], {"status": "Review", "notes": "checking with the bank", "updated_by": "harsh@create-ed.in"})

    run(api, cid)
    after = {t["ser_no"]: t for t in api.repo.transactions}
    assert (after["10000000003"]["status"], after["10000000003"]["notes"]) == ("Matched", "attached by hand")
    assert (after["10000000002"]["status"], after["10000000002"]["notes"]) == ("Review", "checking with the bank")
    manual = [m for m in api.repo.matches if m["created_by"]]
    assert [(m["id"], m["invoice_id"]) for m in manual] == [("manual-1", leftover["id"])]  # still there, untouched
    # The system's own link on the Macfos line was replaced, not duplicated, and the person's invoice was not reused.
    assert len([m for m in api.repo.matches if m["transaction_id"] == after["10000000001"]["id"]]) == 1
    assert after["10000000001"]["status"] == "Matched"


def test_an_invoice_a_person_attached_is_not_offered_to_another_line(api):
    cid = cycle(api)
    run(api, cid)
    lines = {t["ser_no"]: t for t in api.repo.transactions}
    macfos_invoice = next(i for i in api.repo.list_invoices(cid) if i["total_minor"] == 42200)
    cafe = lines["10000000003"]
    # The person moves the Macfos invoice to the cafe line by hand.
    api.repo.matches = [m for m in api.repo.matches if m["invoice_id"] != macfos_invoice["id"]]
    api.repo.matches.append({"id": "manual-2", "cycle_id": cid, "transaction_id": cafe["id"], "invoice_id": macfos_invoice["id"],
                             "rule": "manual", "is_suggestion": False, "created_by": "harsh@create-ed.in"})
    summary = run(api, cid)
    after = {t["ser_no"]: t for t in api.repo.transactions}
    assert after["10000000001"]["status"] == "Missing invoice"  # its invoice now belongs to the person's line
    assert counts(summary)["Matched"] == 0


# ---- Failure ------------------------------------------------------------------------------------------------------------------------
def test_a_failed_run_releases_the_lock_and_leaves_the_error_visible(api, monkeypatch):
    cid = cycle(api)

    def broken(*args, **kwargs):
        raise RuntimeError("engine blew up")

    monkeypatch.setattr(service, "match", broken)
    cycle_row = api.repo.get_cycle(cid)
    service.start_matching(api.repo, cycle_row)
    assert api.repo.cycles[cid]["job_status"] == "running"
    assert service.run_matching(api.repo, cycle_row, "t") is None  # a background job never raises
    row = api.repo.cycles[cid]
    assert (row["job_status"], row["job_message"]) == ("failed", "Matching didn't finish. Please try again.")  # not stuck "running"
    assert row["status"] == "invoices_extracted"  # not moved to matched
    summary = api.get(f"/api/cycles/{cid}/match-summary").json()
    assert summary["job"] == {"status": "failed", "progress": None, "message": "Matching didn't finish. Please try again."}
    # The Invoices step does not show a failed matching run as a failed reading.
    assert api.get(f"/api/cycles/{cid}/invoices").json()["job"] is None
    monkeypatch.setattr(service, "match", real_match)  # the engine works again
    assert api.post(f"/api/cycles/{cid}/match").status_code == 202  # so the cycle can simply be matched again
    assert api.get(f"/api/cycles/{cid}/match-summary").json()["job"]["status"] == "done"


def test_a_run_that_stopped_moving_shows_as_failed_and_can_be_started_again(api):
    cid = cycle(api)
    api.repo.update_cycle(cid, {"job_kind": "matching", "job_status": "running", "job_progress": 30, "job_message": "Matching 4 lines…"})
    api.repo.cycles[cid]["updated_at"] = "2020-01-01T00:00:00+00:00"  # not moved for years
    job = api.get(f"/api/cycles/{cid}/match-summary").json()["job"]
    assert job == {"status": "failed", "progress": None, "message": "Matching stopped unexpectedly. Please try again."}
    assert api.post(f"/api/cycles/{cid}/match").status_code == 202


def test_the_invoices_step_shows_a_running_match_but_not_a_finished_or_failed_one(api):
    cid = cycle(api)
    api.repo.update_cycle(cid, {"job_kind": "matching", "job_status": "running", "job_progress": 30, "job_message": "Matching 4 lines…"})
    assert api.get(f"/api/cycles/{cid}/invoices").json()["job"]["message"] == "Matching 4 lines…"
    api.repo.update_cycle(cid, {"job_kind": None, "job_status": None, "job_progress": None, "job_message": None})
    run_summary = run(api, cid)
    assert run_summary["job"]["status"] == "done"
    assert api.get(f"/api/cycles/{cid}/invoices").json()["job"] is None


def test_the_job_kind_not_the_wording_says_whose_job_it_is(api):
    cid = cycle(api)
    # An invoice-reading job whose message happens to start with "Matching" is not a matching run...
    api.repo.update_cycle(cid, {"job_kind": "invoices", "job_status": "failed", "job_progress": None, "job_message": "Matching files could not be read"})
    assert api.get(f"/api/cycles/{cid}/match-summary").json()["job"] is None
    assert api.get(f"/api/cycles/{cid}/invoices").json()["job"]["status"] == "failed"
    # ...and a matching run with any wording still is one (and is not shown as a failed reading).
    api.repo.update_cycle(cid, {"job_kind": "matching", "job_status": "failed", "job_progress": None, "job_message": "Something else entirely"})
    assert api.get(f"/api/cycles/{cid}/match-summary").json()["job"]["message"] == "Something else entirely"
    assert api.get(f"/api/cycles/{cid}/invoices").json()["job"] is None


def test_every_job_writes_its_kind_and_clears_it_with_the_rest(api):
    cid = cycle(api, read=False, confirm=False)  # the statement has just been read
    assert api.repo.cycles[cid]["job_kind"] == "statement" and api.repo.cycles[cid]["job_status"] == "done"
    api.post(f"/api/cycles/{cid}/statement/confirm")
    assert api.repo.cycles[cid]["job_kind"] is None and api.repo.cycles[cid]["job_status"] is None  # cleared together
    api.post(f"/api/cycles/{cid}/invoices/extract")
    assert (api.repo.cycles[cid]["job_kind"], api.repo.cycles[cid]["job_status"]) == ("invoices", "done")
    run(api, cid)
    assert (api.repo.cycles[cid]["job_kind"], api.repo.cycles[cid]["job_status"]) == ("matching", "done")


def test_a_run_left_running_by_a_dead_worker_goes_stale_after_three_minutes_like_statement_reading(api):
    assert JOB_STALE_SECONDS == 180  # the one limit that statement reading, invoice reading and matching share
    cid = cycle(api)
    service.start_matching(api.repo, api.repo.get_cycle(cid))  # the worker dies right here: nothing else happens
    row = api.repo.get_cycle(cid)
    started = datetime.fromisoformat(str(row["updated_at"]))

    # Inside 3 minutes it is still a run in progress, and a second run is refused.
    soon = started + timedelta(seconds=170)
    assert service.matching_job(row, soon)["status"] == "running"
    with pytest.raises(ServiceError) as refused:
        service.start_matching(api.repo, row, now=soon)
    assert refused.value.status_code == 409

    # After 3 minutes it shows as failed (with a plain message), and a new run may start.
    late = started + timedelta(seconds=181)
    assert service.matching_job(row, late) == {"status": "failed", "progress": None, "message": "Matching stopped unexpectedly. Please try again."}
    service.start_matching(api.repo, row, now=late)  # not refused: the cycle is not stuck
    assert api.repo.cycles[cid]["status"] == "invoices_extracted"  # the dead run changed nothing else
    assert service.run_matching(api.repo, api.repo.get_cycle(cid), "t") is not None
    assert api.get(f"/api/cycles/{cid}/match-summary").json()["job"]["status"] == "done"