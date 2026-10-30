"""Statement endpoints and the background read, with the database, storage and PDF reader faked.

The text below is made-up test data in the statement's layout; the real June statement is covered by
test_statement.py (Docker only).
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.db import get_repo
from app.main import app
from app.services.statement import JOB_STALE_SECONDS, StatementError, job_is_active, start_parse, statement_view
from app.storage import get_storage
from fakes import FakeRepo, FakeStorage

USER = CurrentUser(email="harsh@create-ed.in", user_id="u1")
PDF = b"%PDF-1.4 fake statement bytes"


def statement_text(*, purchases="350.00", credits="50.00") -> str:
    return "\n".join(
        [
            "CREDIT CARD STATEMENT",
            "   STATEMENT DATE          other words on the same line",
            "   June 28, 2026           more words",
            "  Statement period : May 21, 2026 to June 28, 2026",
            "   STATEMENT SUMMARY",
            f"   `400.00     `100.00     `{purchases}     `0.00     `{credits}",
            "Date        SerNo.      Transaction Details       Reward Points   Intl.# amount   Amount (in`)",
            "0000XXXXXXXX1111",
            "21/05/2026   10000000001   SHOP ONE MUMBAI IN               10                   100.00",
            "22/05/2026   10000000002   SHOP TWO MUMBAI IN               20                   200.00",
            "23/05/2026   10000000003   SHOP THREE MUMBAI IN              5       3 USD         50.00",
            "                                                                     USD",
            "24/05/2026   10000000004   CLICK TO PAY PAYMENT RECEIVED     0                    50.00 CR",
        ]
    )


@pytest.fixture
def api(monkeypatch):
    repo, storage = FakeRepo(), FakeStorage()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    box = {"text": statement_text()}
    monkeypatch.setattr("app.services.statement.pdf_text", lambda data, **kw: box["text"])
    client = TestClient(app)
    client.repo, client.storage, client.box = repo, storage, box
    yield client
    app.dependency_overrides.clear()


def cycle_with_statement(api, name="CC June 2026.pdf", data=PDF):
    cid = api.post("/api/cycles").json()["id"]
    r = api.post(f"/api/cycles/{cid}/files", data={"kind": "statement"}, files=[("files", (name, data, "application/pdf"))])
    assert r.status_code == 200 and r.json()["files"][0]["status"] == "uploaded"
    return cid


def read(api, cid):
    r = api.post(f"/api/cycles/{cid}/statement/parse")
    assert r.status_code == 202, r.text
    return r.json()


def test_every_statement_endpoint_needs_a_token():
    client = TestClient(app)
    base = "/api/cycles/6f9619ff-8b86-d011-b42d-00c04fc964ff/statement"
    for method, path in [("get", base), ("post", base + "/parse"), ("post", base + "/confirm")]:
        assert getattr(client, method)(path).status_code == 401, (method, path)


def test_before_reading_there_are_no_lines(api):
    cid = cycle_with_statement(api)
    body = api.get(f"/api/cycles/{cid}/statement").json()
    assert body["status"] == "draft" and body["lines"] == [] and body["check"] is None and body["job"] is None


def test_reading_saves_the_lines_the_header_and_a_passing_check(api):
    cid = cycle_with_statement(api)
    started = read(api, cid)
    assert started["job"] == {"status": "running", "progress": 0, "message": "Starting…"}

    body = api.get(f"/api/cycles/{cid}/statement").json()  # the background task has run by now
    assert body["status"] == "statement_parsed"
    assert body["job"]["status"] == "done" and body["job"]["progress"] == 100
    assert body["job"]["message"] == "Statement read: 4 lines"
    assert (body["statement_date"], body["period_start"], body["period_end"]) == ("2026-06-28", "2026-05-21", "2026-06-28")
    assert body["summary"] == {"previous_paise": 10000, "purchases_paise": 35000, "credits_paise": 5000, "total_due_paise": 40000}
    check = body["check"]
    assert check["ok"] and check["debits_ok"] and check["credits_ok"] and check["problems"] == []
    assert (check["lines"], check["debits_paise"], check["credits_paise"], check["cards"]) == (4, 35000, 5000, ["1111"])
    assert (check["debits_difference_paise"], check["credits_difference_paise"]) == (0, 0)

    lines = body["lines"]
    assert [x["ser_no"] for x in lines] == ["10000000001", "10000000002", "10000000003", "10000000004"]
    assert lines[2]["foreign_amount_minor"] == 300 and lines[2]["foreign_currency"] == "USD"
    assert lines[3]["is_credit"] and lines[3]["amount_paise"] == 5000
    assert api.get(f"/api/cycles/{cid}").json()["status"] == "statement_parsed"
    assert [e["action"] for e in api.repo.events if e["action"] == "statement_parsed"] == ["statement_parsed"]


def test_an_empty_label_is_filled_from_the_statement_month(api):
    cid = cycle_with_statement(api)
    assert api.get(f"/api/cycles/{cid}").json()["label"] is None
    read(api, cid)
    assert api.get(f"/api/cycles/{cid}").json()["label"] == "June 2026"


def test_a_label_a_person_gave_is_kept(api):
    cid = api.post("/api/cycles", json={"label": "Card A"}).json()["id"]
    api.post(f"/api/cycles/{cid}/files", data={"kind": "statement"}, files=[("files", ("s.pdf", PDF, "application/pdf"))])
    read(api, cid)
    assert api.get(f"/api/cycles/{cid}").json()["label"] == "Card A"


def test_replacing_the_statement_drops_a_label_made_from_the_old_month_but_not_a_typed_one(api):
    auto = cycle_with_statement(api)
    read(api, auto)
    api.post(f"/api/cycles/{auto}/files", data={"kind": "statement"}, files=[("files", ("n.pdf", b"%PDF new", "application/pdf"))])
    assert api.get(f"/api/cycles/{auto}").json()["label"] is None  # was "June 2026", from the old statement

    typed = api.post("/api/cycles", json={"label": "June 2026"}).json()["id"]  # a person typed the same words
    api.post(f"/api/cycles/{typed}/files", data={"kind": "statement"}, files=[("files", ("a.pdf", b"%PDF a", "application/pdf"))])
    read(api, typed)
    api.post(f"/api/cycles/{typed}/files", data={"kind": "statement"}, files=[("files", ("b.pdf", b"%PDF b", "application/pdf"))])
    # Indistinguishable from the automatic label, so it goes too; a typed name that differs is always kept.
    assert api.get(f"/api/cycles/{typed}").json()["label"] is None


def test_confirming_clears_the_statement_job(api):
    cid = cycle_with_statement(api)
    read(api, cid)
    assert api.repo.cycles[cid]["job_status"] == "done"
    api.post(f"/api/cycles/{cid}/statement/confirm")
    cycle = api.repo.cycles[cid]
    assert (cycle["job_status"], cycle["job_progress"], cycle["job_message"]) == (None, None, None)
    assert api.get(f"/api/cycles/{cid}/statement").json()["job"] is None


def test_confirming_locks_the_statement_and_records_who_and_when(api):
    cid = cycle_with_statement(api)
    read(api, cid)
    r = api.post(f"/api/cycles/{cid}/statement/confirm")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "statement_confirmed" and body["confirmed_by"] == USER.email and body["confirmed_at"]
    assert api.get(f"/api/cycles/{cid}").json()["status"] == "statement_confirmed"
    # Neither confirming again, nor reading again, nor replacing the file is possible.
    assert api.post(f"/api/cycles/{cid}/statement/confirm").status_code == 409
    assert api.post(f"/api/cycles/{cid}/statement/parse").status_code == 409
    other = api.post(f"/api/cycles/{cid}/files", data={"kind": "statement"}, files=[("files", ("x.pdf", b"%PDF other", "application/pdf"))])
    assert other.status_code == 409


def test_confirm_before_reading_is_refused(api):
    cid = cycle_with_statement(api)
    r = api.post(f"/api/cycles/{cid}/statement/confirm")
    assert r.status_code == 409 and "Read the statement" in r.json()["detail"]


def test_a_totals_mismatch_is_shown_and_cannot_be_confirmed(api):
    api.box["text"] = statement_text(purchases="350.05")
    cid = cycle_with_statement(api)
    read(api, cid)
    body = api.get(f"/api/cycles/{cid}/statement").json()
    assert body["status"] == "statement_parsed" and body["job"]["status"] == "done"
    check = body["check"]
    assert not check["ok"] and not check["debits_ok"] and check["credits_ok"]
    assert check["debits_difference_paise"] == -5 and len(check["problems"]) == 1
    assert "₹350.00" in check["problems"][0] and "₹350.05" in check["problems"][0]
    refused = api.post(f"/api/cycles/{cid}/statement/confirm")
    assert refused.status_code == 409 and "can't be confirmed" in refused.json()["detail"]
    assert api.get(f"/api/cycles/{cid}").json()["status"] == "statement_parsed"


def test_replacing_a_statement_that_did_not_match_starts_again(api):
    api.box["text"] = statement_text(purchases="350.05")
    cid = cycle_with_statement(api)
    read(api, cid)
    assert api.repo.list_transactions(cid)
    r = api.post(f"/api/cycles/{cid}/files", data={"kind": "statement"}, files=[("files", ("fixed.pdf", b"%PDF fixed", "application/pdf"))])
    assert r.status_code == 200
    body = api.get(f"/api/cycles/{cid}/statement").json()
    assert body["status"] == "draft" and body["lines"] == [] and body["check"] is None and body["period_start"] is None
    api.box["text"] = statement_text()
    read(api, cid)
    assert api.get(f"/api/cycles/{cid}/statement").json()["check"]["ok"]


def test_reading_again_replaces_the_lines_instead_of_adding_to_them(api):
    cid = cycle_with_statement(api)
    read(api, cid)
    read(api, cid)
    assert len(api.get(f"/api/cycles/{cid}/statement").json()["lines"]) == 4
    assert len(api.repo.transactions) == 4


def test_a_pdf_that_is_not_a_statement_fails_with_a_message_and_saves_nothing(api):
    api.box["text"] = "Tax invoice\nTotal 1,000.00"
    cid = cycle_with_statement(api, "invoice.pdf")
    read(api, cid)
    body = api.get(f"/api/cycles/{cid}/statement").json()
    assert body["status"] == "draft" and body["lines"] == [] and body["check"] is None
    assert body["job"]["status"] == "failed" and "doesn't look like an ICICI card statement" in body["job"]["message"]
    assert api.repo.transactions == []


def test_a_line_that_cannot_be_read_stops_the_whole_read(api):
    api.box["text"] = statement_text() + "\n25/05/2026   10000000009   BROKEN LINE WITH NO AMOUNT"
    cid = cycle_with_statement(api)
    read(api, cid)
    body = api.get(f"/api/cycles/{cid}/statement").json()
    assert body["job"]["status"] == "failed" and "could not be read" in body["job"]["message"]
    assert body["status"] == "draft" and api.repo.transactions == []


def test_a_pdf_with_no_text_layer_fails_clearly(api):
    api.box["text"] = "  \n"
    cid = cycle_with_statement(api)
    read(api, cid)
    job = api.get(f"/api/cycles/{cid}/statement").json()["job"]
    assert job["status"] == "failed" and "no readable text" in job["message"]


def test_a_storage_failure_is_recorded_not_raised(api, monkeypatch):
    cid = cycle_with_statement(api)

    def boom(path):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(api.storage, "get", boom)
    read(api, cid)
    job = api.get(f"/api/cycles/{cid}/statement").json()["job"]
    assert job == {"status": "failed", "progress": None, "message": "Couldn't read the statement. Please try again."}


def test_reading_without_a_statement_file_is_refused(api):
    cid = api.post("/api/cycles").json()["id"]
    r = api.post(f"/api/cycles/{cid}/statement/parse")
    assert r.status_code == 409 and "Upload the statement" in r.json()["detail"]


def test_a_second_read_while_one_is_running_is_refused(api):
    cid = cycle_with_statement(api)
    api.repo.update_cycle(cid, {"job_status": "running", "job_progress": 30, "job_message": "Reading the PDF text…"})
    r = api.post(f"/api/cycles/{cid}/statement/parse")
    assert r.status_code == 409 and "already being read" in r.json()["detail"]
    assert api.get(f"/api/cycles/{cid}/statement").json()["job"]["status"] == "running"


def test_unknown_cycle_is_404(api):
    base = "/api/cycles/6f9619ff-8b86-d011-b42d-00c04fc964ff/statement"
    assert api.get(base).status_code == 404
    assert api.post(base + "/parse").status_code == 404
    assert api.post(base + "/confirm").status_code == 404


# ---- The "already running" guard ---------------------------------------------------------------------
NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)


def running_cycle(age_seconds):
    return {
        "id": "c1", "status": "draft", "job_status": "running", "job_progress": 30, "job_message": "x",
        "updated_at": (NOW - timedelta(seconds=age_seconds)).isoformat(),
    }


def test_a_job_that_is_moving_blocks_a_second_read():
    assert job_is_active(running_cycle(5), NOW)
    with pytest.raises(StatementError) as e:
        start_parse(FakeRepo(), running_cycle(5), NOW)
    assert e.value.status_code == 409 and "already being read" in e.value.message


def test_a_job_that_has_stopped_moving_is_shown_as_failed_and_can_be_started_again():
    stale = running_cycle(JOB_STALE_SECONDS + 1)
    assert not job_is_active(stale, NOW)
    repo = FakeRepo()
    repo.cycles["c1"] = {**stale}
    assert statement_view(repo, stale, NOW)["job"] == {
        "status": "failed", "progress": None, "message": "Reading stopped unexpectedly. Please try again.",
    }
    # Starting again is allowed (the "Upload the statement first" refusal here only shows the guard was passed).
    with pytest.raises(StatementError) as e:
        start_parse(repo, stale, NOW)
    assert "Upload the statement" in e.value.message
