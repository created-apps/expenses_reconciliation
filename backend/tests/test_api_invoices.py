"""Invoice endpoints and the background read, with the database, storage and PDF reader faked.

The texts are made-up invoices; the real June invoices are covered by test_invoices.py (Docker only).
"""

import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.db import get_repo
from app.main import app
from app.pdf import PdfToolUnavailable
from app.services.vision_client import get_vision
from app.storage import get_storage
from fakes import FakeRepo, FakeStorage
from test_api_statement import statement_text
from test_invoices import AMAZON_TWO

USER = CurrentUser(email="harsh@create-ed.in", user_id="u1")

FATHOM = (
    "Fathom Video Inc.\nInvoice number B8HTVTIE-0007\nDate of issue  June 20, 2026\n"
    "Fathom Team   2   $18.00   $36.00\nTotal   $36.00\nAmount due   $36.00 USD\n"
)
UNREADABLE = "Some company\nInvoice No: A12345\nInvoice Date: 01/06/2026\n"  # no vendor, no total: needs a check

# What each uploaded "PDF" says when it is read. The bytes are the key.
PDFS = {
    b"%PDF amazon": AMAZON_TWO,
    b"%PDF fathom": FATHOM,
    b"%PDF fathom again": FATHOM,  # different bytes, same invoice: an invoice-level duplicate
    b"%PDF scan": " \n",  # a scan: no text layer
    b"%PDF unreadable": UNREADABLE,
}
STATEMENT_PDF = b"%PDF statement"


@pytest.fixture
def api(monkeypatch):
    repo, storage = FakeRepo(), FakeStorage()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_vision] = lambda: None  # AI not set up; tests that need it override this
    monkeypatch.setattr("app.services.statement.pdf_text", lambda data, **kw: statement_text())
    monkeypatch.setattr("app.services.ingest.pdf_text", lambda data, **kw: "Tax invoice")
    monkeypatch.setattr("app.services.invoices.pdf_text", lambda data, **kw: PDFS[data])
    client = TestClient(app)
    client.repo, client.storage = repo, storage
    yield client
    app.dependency_overrides.clear()


def upload(api, cid, kind, files):
    r = api.post(f"/api/cycles/{cid}/files", data={"kind": kind}, files=[("files", f) for f in files])
    assert r.status_code == 200, r.text
    return r.json()


def new_cycle(api, *, confirm=True, invoices=True):
    cid = api.post("/api/cycles").json()["id"]
    upload(api, cid, "statement", [("CC.pdf", STATEMENT_PDF, "application/pdf")])
    if invoices:
        upload(api, cid, "invoices", [
            ("a.pdf", b"%PDF amazon", "application/pdf"),
            ("b.pdf", b"%PDF fathom", "application/pdf"),
            ("c.pdf", b"%PDF fathom again", "application/pdf"),
            ("scan.pdf", b"%PDF scan", "application/pdf"),
            ("photo.png", b"\x89PNG photo", "image/png"),
            ("a again.pdf", b"%PDF amazon", "application/pdf"),  # byte-identical to a.pdf: a file-level duplicate
        ])
    if confirm:
        assert api.post(f"/api/cycles/{cid}/statement/parse").status_code == 202
        assert api.post(f"/api/cycles/{cid}/statement/confirm").status_code == 200
    return cid


def read(api, cid):
    r = api.post(f"/api/cycles/{cid}/invoices/extract")
    assert r.status_code == 202, r.text
    return r.json()


def listing(api, cid):
    return api.get(f"/api/cycles/{cid}/invoices").json()


def by_file(view):
    out: dict[str, list[dict]] = {}
    for e in view["entries"]:
        out.setdefault(e["file_name"], []).append(e)
    return out


# ---- The server-side gate (test 6.0) --------------------------------------------------------------------
def test_every_invoice_endpoint_needs_a_token():
    client = TestClient(app)
    nil = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
    for method, path in [("post", f"/api/cycles/{nil}/invoices/extract"), ("get", f"/api/cycles/{nil}/invoices"),
                         ("patch", f"/api/invoices/{nil}"), ("post", f"/api/invoices/{nil}/not-invoice")]:
        assert getattr(client, method)(path).status_code == 401, (method, path)


def test_reading_invoices_is_refused_on_a_draft(api):
    cid = new_cycle(api, confirm=False)
    r = api.post(f"/api/cycles/{cid}/invoices/extract")
    assert r.status_code == 409 and "Confirm the statement" in r.json()["detail"]
    assert api.repo.invoices == {} and api.repo.cycles[cid]["job_status"] is None  # nothing started


def test_reading_invoices_is_refused_when_the_statement_is_read_but_not_confirmed(api):
    cid = new_cycle(api, confirm=False)
    assert api.post(f"/api/cycles/{cid}/statement/parse").status_code == 202
    assert api.get(f"/api/cycles/{cid}").json()["status"] == "statement_parsed"
    assert api.post(f"/api/cycles/{cid}/invoices/extract").status_code == 409


def test_reading_again_after_an_export_is_an_edit_that_moves_the_cycle_back_to_matched(api):
    cid = new_cycle(api)
    api.repo.cycles[cid]["status"] = "exported"
    r = api.post(f"/api/cycles/{cid}/invoices/extract")
    assert r.status_code == 202 and api.repo.cycles[cid]["status"] == "matched"
    assert [e["action"] for e in api.repo.events if e["action"] == "edited_after_export"] == ["edited_after_export"]


def test_the_list_can_be_fetched_before_the_statement_is_confirmed(api):
    cid = new_cycle(api, confirm=False)
    view = listing(api, cid)
    assert view["status"] == "draft" and view["job"] is None
    assert view["counts"]["unread"] == 5 and view["counts"]["duplicate_files"] == 1


def test_reading_without_invoice_files_is_refused(api):
    cid = new_cycle(api, invoices=False)
    r = api.post(f"/api/cycles/{cid}/invoices/extract")
    assert r.status_code == 409 and "Upload the invoices" in r.json()["detail"]


def test_unknown_cycle_and_invoice_are_404(api):
    nil = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
    assert api.get(f"/api/cycles/{nil}/invoices").status_code == 404
    assert api.post(f"/api/cycles/{nil}/invoices/extract").status_code == 404
    assert api.patch(f"/api/invoices/{nil}", json={}).status_code == 404
    assert api.post(f"/api/invoices/{nil}/not-invoice").status_code == 404


# ---- Reading ---------------------------------------------------------------------------------------------
def test_before_reading_every_file_is_unread(api):
    cid = new_cycle(api)
    view = listing(api, cid)
    assert view["status"] == "statement_confirmed" and view["job"] is None
    states = collections_count(view)
    assert states == {"unread": 5, "duplicate": 1}  # a.pdf, b.pdf, c.pdf, scan.pdf, photo.png; "a again.pdf"


def collections_count(view):
    out: dict[str, int] = {}
    for e in view["entries"]:
        out[e["state"]] = out.get(e["state"], 0) + 1
    return out


def test_reading_gives_invoices_pending_rows_and_duplicates(api):
    cid = new_cycle(api)
    started = read(api, cid)
    assert started["job"] == {"status": "running", "progress": 0, "message": "Starting…"}

    view = listing(api, cid)  # the background task has run by now
    assert view["status"] == "invoices_extracted"
    assert view["job"]["status"] == "done" and view["job"]["progress"] == 100
    assert view["job"]["message"] == "Invoices read: 4 invoices from 3 files · 2 waiting for AI"
    assert view["counts"] == {
        "files": 6, "unread": 0, "invoices": 4, "pending": 2, "needs_check": 0, "failed": 0,
        "duplicate_files": 1, "duplicate_invoices": 1, "ignored": 0,
    }

    files = by_file(view)
    amazon = files["a.pdf"]
    assert [(e["block_index"], e["invoice_no"], e["total_minor"], e["state"]) for e in amazon] == [
        (0, "AB1-100", 11800, "ok"), (1, "AB1-200", 27500, "ok"),
    ]
    assert amazon[0]["vendor_key"] == "amazon" and amazon[0]["vendor_name"] == "Amazon"
    assert amazon[0]["order_id"] == "111-2222222-3333333" and amazon[0]["order_date"] == "2026-06-01"
    assert amazon[0]["invoice_date"] == "2026-06-05" and amazon[0]["source"] == "pdf_text"

    (fathom,) = files["b.pdf"]
    assert (fathom["currency"], fathom["total_minor"], fathom["state"], fathom["vendor_name"]) == ("USD", 3600, "ok", "Fathom")

    (again,) = files["c.pdf"]  # different bytes, the same invoice
    assert again["state"] == "duplicate" and again["duplicate_of_name"] == "b.pdf"
    (copy,) = files["a again.pdf"]  # the same bytes: a file-level duplicate, never read
    assert copy["state"] == "duplicate" and copy["invoice_id"] is None and not copy["has_copy"]

    for name in ("scan.pdf", "photo.png"):
        (pending,) = files[name]
        assert pending["state"] == "pending" and pending["source"] is None and pending["total_minor"] is None


def test_an_invoice_without_a_vendor_or_total_needs_a_check_and_says_why(api, monkeypatch):
    cid = new_cycle(api, invoices=False)
    upload(api, cid, "invoices", [("odd.pdf", b"%PDF unreadable", "application/pdf")])
    read(api, cid)
    view = listing(api, cid)
    (odd,) = by_file(view)["odd.pdf"]
    assert odd["state"] == "needs_check" and odd["problems"] == ["Vendor not recognised", "No total found"]
    assert view["counts"]["needs_check"] == 1 and view["counts"]["invoices"] == 1


def test_reading_again_replaces_the_rows_instead_of_adding(api):
    cid = new_cycle(api)
    read(api, cid)
    first_ids = {i["id"] for i in api.repo.invoices.values()}
    read(api, cid)
    assert len(api.repo.invoices) == len(first_ids) == 6  # 2 + 1 + 1 + 2 pending
    assert listing(api, cid)["counts"]["invoices"] == 4
    assert api.repo.cycles[cid]["status"] == "invoices_extracted"


def test_reading_only_the_new_files_leaves_the_existing_invoices_alone(api):
    cid = new_cycle(api)
    read(api, cid)
    before = {i["id"] for i in api.repo.invoices.values()}
    upload(api, cid, "invoices", [("late.pdf", b"%PDF unreadable", "application/pdf")])

    r = api.post(f"/api/cycles/{cid}/invoices/extract?new_only=true")
    assert r.status_code == 202, r.text
    now = {i["id"] for i in api.repo.invoices.values()}
    assert before <= now and len(now) == len(before) + 1  # every old row kept (same ids), one new row
    view = listing(api, cid)
    assert view["job"]["status"] == "done"
    (late,) = by_file(view)["late.pdf"]
    assert late["invoice_id"] and late["state"] == "needs_check"


def test_reading_only_the_new_files_keeps_the_matches_of_the_old_ones(api):
    cid = new_cycle(api)
    read(api, cid)
    old = next(iter(api.repo.invoices.values()))
    txn = api.repo.transactions[0]["id"]
    api.repo.matches.append({"id": "m1", "cycle_id": cid, "transaction_id": txn, "invoice_id": old["id"]})
    upload(api, cid, "invoices", [("late.pdf", b"%PDF unreadable", "application/pdf")])
    assert api.post(f"/api/cycles/{cid}/invoices/extract?new_only=true").status_code == 202
    assert [m["id"] for m in api.repo.matches] == ["m1"]


def test_reading_only_the_new_files_with_nothing_new_is_refused(api):
    cid = new_cycle(api)
    read(api, cid)
    r = api.post(f"/api/cycles/{cid}/invoices/extract?new_only=true")
    assert r.status_code == 409 and "no new invoice files" in r.json()["detail"]


def test_a_file_that_cannot_be_downloaded_fails_alone(api, monkeypatch):
    cid = new_cycle(api)
    real_get = api.storage.get

    def flaky(path):
        if path.endswith("/b.pdf"):
            raise RuntimeError("storage unavailable")
        return real_get(path)

    monkeypatch.setattr(api.storage, "get", flaky)
    read(api, cid)
    view = listing(api, cid)
    assert view["job"]["status"] == "done"
    (b,) = by_file(view)["b.pdf"]
    assert b["state"] == "failed"
    assert view["counts"]["failed"] == 1 and len(by_file(view)["a.pdf"]) == 2  # the rest was read


def test_without_poppler_the_job_fails_with_a_clear_message(api, monkeypatch):
    def no_tool(data, **kw):
        raise PdfToolUnavailable("pdftotext (poppler) is not installed")

    monkeypatch.setattr("app.services.invoices.pdf_text", no_tool)
    cid = new_cycle(api)
    read(api, cid)
    job = listing(api, cid)["job"]
    assert job["status"] == "failed" and "poppler" in job["message"]
    assert api.repo.cycles[cid]["status"] == "statement_confirmed"  # not advanced


def test_a_second_read_while_one_is_running_is_refused(api):
    cid = new_cycle(api)
    api.repo.update_cycle(cid, {"job_status": "running", "job_progress": 40, "job_message": "Reading invoices… 3 of 5"})
    r = api.post(f"/api/cycles/{cid}/invoices/extract")
    assert r.status_code == 409 and "already being read" in r.json()["detail"]
    assert listing(api, cid)["job"]["status"] == "running"


# ---- Images read by AI (Slice 7) --------------------------------------------------------------------------
DTDC = '{"vendor": "DTDC Express Limited", "invoice_no": "F33356894", "order_id": null, "invoice_date": "2026-06-01", ' \
       '"order_date": null, "currency": "INR", "total": "769.00"}'
AMAZON = '{"vendor": "Amazon", "invoice_no": "IN-11218383", "order_id": "408-2168147-1083564", "invoice_date": "2026-06-22", ' \
         '"order_date": "2026-06-14", "currency": "INR", "total": "99.00"}'
PHOTO, SCAN_PAGE = b"\x89PNG photo", b"PNG-OF-THE-SCANNED-PAGE"


class FakeVision:
    """Answers by image bytes; an exception as the answer is raised. Counts the calls it gets."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def read(self, image, media_type, instructions, schema):
        from app.engine.invoices.vision import VisionReply

        self.calls.append((image, media_type))
        answer = self.answers[image]
        if isinstance(answer, Exception):
            raise answer
        return VisionReply(text=answer, model="claude-sonnet-5-5", input_tokens=2000, output_tokens=100)


@pytest.fixture
def with_ai(api, monkeypatch):
    """Switch the AI on for a test: returns a function that sets the answers."""
    monkeypatch.setattr("app.services.invoices.render_first_page_png", lambda data: SCAN_PAGE)

    def use(answers):
        vision = FakeVision(answers)
        app.dependency_overrides[get_vision] = lambda: vision
        return vision

    return use


def test_images_and_scans_are_read_by_the_ai_when_it_is_set_up(api, with_ai):
    vision = with_ai({PHOTO: DTDC, SCAN_PAGE: AMAZON})
    cid = new_cycle(api)
    read(api, cid)
    view = listing(api, cid)
    assert view["counts"]["pending"] == 0 and view["counts"]["invoices"] == 6
    (photo,) = by_file(view)["photo.png"]
    assert (photo["state"], photo["source"], photo["vendor_name"], photo["invoice_no"], photo["total_minor"]) == (
        "ok", "vision", "DTDC", "F33356894", 76900,
    )
    (scan,) = by_file(view)["scan.pdf"]  # no text layer: its first page was turned into an image
    assert (scan["state"], scan["source"], scan["vendor_name"], scan["order_id"], scan["total_minor"]) == (
        "ok", "vision", "Amazon", "408-2168147-1083564", 9900,
    )
    assert (scan["order_date"], scan["invoice_date"]) == ("2026-06-14", "2026-06-22")
    assert {media for _, media in vision.calls} == {"image/png"} and {img for img, _ in vision.calls} == {PHOTO, SCAN_PAGE}
    assert view["job"]["message"] == "Invoices read: 6 invoices from 5 files · 2 read by AI"


def test_the_ai_usage_is_kept_on_the_invoice_and_in_the_event(api, with_ai):
    with_ai({PHOTO: DTDC, SCAN_PAGE: AMAZON})
    cid = new_cycle(api)
    read(api, cid)
    row = next(i for i in api.repo.invoices.values() if i["source"] == "vision")
    assert row["extra"]["ai"] == {"model": "claude-sonnet-5-5", "input_tokens": 2000, "output_tokens": 100, "calls": 1}
    (event,) = [e for e in api.repo.events if e["action"] == "invoices_extracted"]
    assert event["payload"]["ai_images"] == 2
    assert (event["payload"]["ai_input_tokens"], event["payload"]["ai_output_tokens"]) == (4000, 200)


def test_a_wrong_key_makes_the_image_need_a_check_with_the_reason_and_the_job_still_finishes(api, with_ai):
    from app.engine.invoices.vision import VisionError

    with_ai({PHOTO: VisionError("The AI service did not accept the API key. Check ANTHROPIC_API_KEY."), SCAN_PAGE: AMAZON})
    cid = new_cycle(api)
    read(api, cid)
    view = listing(api, cid)
    assert view["job"]["status"] == "done"  # the job did not crash
    (photo,) = by_file(view)["photo.png"]
    assert photo["state"] == "needs_check" and photo["source"] == "vision"
    assert photo["problems"] == ["The AI service did not accept the API key. Check ANTHROPIC_API_KEY."]
    assert by_file(view)["scan.pdf"][0]["state"] == "ok"  # the other image was still read
    assert len(by_file(view)["a.pdf"]) == 2  # and so were the PDFs


def test_reading_again_does_not_pay_for_images_the_ai_already_read(api, with_ai):
    vision = with_ai({PHOTO: DTDC, SCAN_PAGE: AMAZON})
    cid = new_cycle(api)
    read(api, cid)
    assert len(vision.calls) == 2
    read(api, cid)
    assert len(vision.calls) == 2  # unchanged: both were read fine
    assert listing(api, cid)["counts"]["invoices"] == 6


def test_reading_again_does_not_resend_an_image_the_ai_read_but_that_prints_no_vendor(api, with_ai):
    no_vendor = DTDC.replace('"vendor": "DTDC Express Limited"', '"vendor": null')
    vision = with_ai({PHOTO: no_vendor, SCAN_PAGE: AMAZON})
    cid = new_cycle(api)
    read(api, cid)
    (photo,) = by_file(listing(api, cid))["photo.png"]
    assert photo["state"] == "needs_check" and photo["vendor_key"] is None
    assert photo["problems"] == ["The image does not show a vendor name. Open the file and choose the vendor"]
    assert photo["total_minor"] == 76900  # everything else was read
    read(api, cid)
    assert [img for img, _ in vision.calls].count(PHOTO) == 1  # asked once: the answer would be the same
    # A person chooses the vendor: the invoice is OK and stays that way.
    done = edit(api, photo["invoice_id"], vendor_key="dtdc").json()
    assert by_file(done)["photo.png"][0]["state"] == "ok" and by_file(done)["photo.png"][0]["source"] == "manual"


def test_reading_again_tries_an_image_the_ai_could_not_read(api, with_ai):
    from app.engine.invoices.vision import VisionError

    vision = with_ai({PHOTO: VisionError("The AI service is busy (rate limit). Read the invoices again in a minute."), SCAN_PAGE: AMAZON})
    cid = new_cycle(api)
    read(api, cid)
    assert by_file(listing(api, cid))["photo.png"][0]["state"] == "needs_check"
    vision.answers[PHOTO] = DTDC  # the second try works
    read(api, cid)
    assert by_file(listing(api, cid))["photo.png"][0]["state"] == "ok"
    assert [img for img, _ in vision.calls].count(SCAN_PAGE) == 1  # the image that was fine is not read again


def test_an_answer_that_cannot_be_used_is_asked_for_once_more_then_needs_a_check(api, with_ai):
    vision = with_ai({PHOTO: "I could not read this", SCAN_PAGE: AMAZON})
    cid = new_cycle(api)
    read(api, cid)
    (photo,) = by_file(listing(api, cid))["photo.png"]
    assert photo["state"] == "needs_check" and "could not be used" in photo["problems"][0]
    assert [img for img, _ in vision.calls].count(PHOTO) == 2  # asked twice, not more


def test_a_scan_whose_page_cannot_be_rendered_stays_pending(api, with_ai, monkeypatch):
    vision = with_ai({PHOTO: DTDC})
    monkeypatch.setattr("app.services.invoices.render_first_page_png", lambda data: b"")
    cid = new_cycle(api)
    read(api, cid)
    (scan,) = by_file(listing(api, cid))["scan.pdf"]
    assert scan["state"] == "pending"
    assert "could not be turned into an image" in api.repo.invoices[scan["invoice_id"]]["extra"]["reason"]
    assert len(vision.calls) == 1  # only the photo


def test_without_the_ai_the_reason_the_images_wait_is_kept(api):
    cid = new_cycle(api)
    read(api, cid)
    (photo,) = by_file(listing(api, cid))["photo.png"]
    assert photo["state"] == "pending"
    assert "ANTHROPIC_API_KEY" in api.repo.invoices[photo["invoice_id"]]["extra"]["reason"]
    assert photo["problems"] == [api.repo.invoices[photo["invoice_id"]]["extra"]["reason"]]  # shown to the person


def test_an_image_the_ai_read_can_still_be_corrected_and_the_correction_is_kept(api, with_ai):
    vision = with_ai({PHOTO: DTDC, SCAN_PAGE: AMAZON})
    cid = new_cycle(api)
    read(api, cid)
    photo = by_file(listing(api, cid))["photo.png"][0]
    changed = edit(api, photo["invoice_id"], total_minor=77000).json()
    assert by_file(changed)["photo.png"][0]["source"] == "manual" and by_file(changed)["photo.png"][0]["total_minor"] == 77000
    read(api, cid)
    assert by_file(listing(api, cid))["photo.png"][0]["total_minor"] == 77000
    assert len(vision.calls) == 2  # no new AI calls


# ---- Corrections -----------------------------------------------------------------------------------------
def edit(api, invoice_id, **fields):
    return api.patch(f"/api/invoices/{invoice_id}", json=fields)


def entry(view, name, index=0):
    return by_file(view)[name][index]


def test_a_correction_is_saved_marked_manual_and_logged(api):
    cid = new_cycle(api)
    read(api, cid)
    target = entry(listing(api, cid), "b.pdf")
    r = edit(api, target["invoice_id"], total_minor=4000, invoice_no="B8-9")
    assert r.status_code == 200
    changed = entry(r.json(), "b.pdf")
    assert (changed["total_minor"], changed["invoice_no"], changed["source"], changed["state"]) == (4000, "B8-9", "manual", "ok")
    assert api.repo.invoices[target["invoice_id"]]["amounts_minor"] == [4000]
    events = [e for e in api.repo.events if e["action"] == "invoice_edited"]
    assert len(events) == 1 and events[0]["actor"] == USER.email
    assert events[0]["payload"]["changes"]["total_minor"] == [3600, 4000]


def test_a_corrected_invoice_survives_reading_again(api):
    cid = new_cycle(api)
    read(api, cid)
    target = entry(listing(api, cid), "b.pdf")
    edit(api, target["invoice_id"], total_minor=4000)
    read(api, cid)
    after = entry(listing(api, cid), "b.pdf")
    assert after["total_minor"] == 4000 and after["source"] == "manual" and after["invoice_id"] == target["invoice_id"]
    assert len(by_file(listing(api, cid))["a.pdf"]) == 2  # the other files were read again as usual


def test_correcting_a_pending_image_makes_it_a_real_invoice(api):
    cid = new_cycle(api)
    read(api, cid)
    photo = entry(listing(api, cid), "photo.png")
    r = edit(api, photo["invoice_id"], vendor_key="dtdc", invoice_date="2026-06-01", total_minor=76900, invoice_no="F1")
    done = entry(r.json(), "photo.png")
    assert (done["state"], done["vendor_name"], done["total_minor"], done["source"]) == ("ok", "DTDC", 76900, "manual")
    assert r.json()["counts"]["pending"] == 1  # only the scan is left


def test_a_correction_that_leaves_something_missing_needs_a_check(api):
    cid = new_cycle(api)
    read(api, cid)
    target = entry(listing(api, cid), "b.pdf")
    r = edit(api, target["invoice_id"], invoice_date=None)
    changed = entry(r.json(), "b.pdf")
    assert changed["state"] == "needs_check" and changed["problems"] == ["No date found"]


@pytest.mark.parametrize(
    "fields",
    [{"vendor_key": "no-such-vendor"}, {"currency": "EUR"}, {"total_minor": -1}],
)
def test_a_bad_correction_is_refused_and_changes_nothing(api, fields):
    cid = new_cycle(api)
    read(api, cid)
    target = entry(listing(api, cid), "b.pdf")
    assert edit(api, target["invoice_id"], **fields).status_code == 422
    assert api.repo.invoices[target["invoice_id"]]["source"] == "pdf_text"
    assert not [e for e in api.repo.events if e["action"] == "invoice_edited"]


def test_correcting_an_invoice_after_an_export_is_an_edit(api):
    cid = new_cycle(api)
    read(api, cid)
    target = entry(listing(api, cid), "b.pdf")
    api.repo.cycles[cid]["status"] = "exported"
    assert edit(api, target["invoice_id"], total_minor=1).status_code == 200
    assert api.repo.cycles[cid]["status"] == "matched"  # the first edit moves it back

    api.repo.cycles[cid]["status"] = "exported"  # exported again; setting a file aside is an edit as well
    assert api.post(f"/api/invoices/{target['invoice_id']}/not-invoice").status_code == 200
    assert api.repo.cycles[cid]["status"] == "matched"
    assert len([e for e in api.repo.events if e["action"] == "edited_after_export"]) == 2


def test_making_two_invoices_identical_marks_the_later_as_a_duplicate(api):
    cid = new_cycle(api)
    read(api, cid)
    first, second = by_file(listing(api, cid))["a.pdf"]
    r = edit(api, second["invoice_id"], invoice_no="AB1-100", total_minor=11800)
    again = by_file(r.json())["a.pdf"]
    assert again[1]["state"] == "duplicate" and again[1]["duplicate_of_name"] == "a.pdf"


def test_not_an_invoice_sets_the_file_aside(api):
    cid = new_cycle(api)
    read(api, cid)
    target = entry(listing(api, cid), "photo.png")
    r = api.post(f"/api/invoices/{target['invoice_id']}/not-invoice")
    assert r.status_code == 200
    (gone,) = by_file(r.json())["photo.png"]
    assert gone["state"] == "ignored" and gone["invoice_id"] is None and "not an invoice" in gone["file_note"]
    assert r.json()["counts"]["ignored"] == 1 and r.json()["counts"]["pending"] == 1
    assert [e["action"] for e in api.repo.events if e["action"] == "invoice_ignored"] == ["invoice_ignored"]
    read(api, cid)  # an ignored file is not read again
    assert entry(listing(api, cid), "photo.png")["state"] == "ignored"
