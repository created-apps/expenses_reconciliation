"""Restoring an invoice file that was set aside with "Not an invoice" (fakes for the database)."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.db import get_repo
from app.main import app
from app.services.invoices import readable_files
from fakes import FakeRepo

USER = CurrentUser(email="harsh@create-ed.in", user_id="u1")
NIL = "6f9619ff-8b86-d011-b42d-00c04fc964ff"


class Cycle:
    def __init__(self, repo: FakeRepo):
        self.repo = repo
        self.cid = repo.create_cycle("June 2026", "t")["id"]
        repo.update_cycle(self.cid, {"status": "invoices_extracted"})
        self.wrong = self.file("wrong.pdf")
        self.good = self.file("good.pdf")
        self.copy = self.file("statement-copy.pdf", kind="ignored", note="copy of the statement")
        self.invoice = self.read(self.wrong)
        self.read(self.good)

    def file(self, name, kind="invoice", note=None):
        repo = self.repo
        (row,) = repo.insert_files([{"id": str(uuid.uuid4()), "cycle_id": self.cid, "kind": kind, "original_name": name, "status": "uploaded", "note": note, "storage_path": f"cycles/x/{name}"}])
        return row

    def read(self, f):
        (inv,) = self.repo.insert_invoices([{
            "cycle_id": self.cid, "file_id": f["id"], "block_index": 0, "vendor_key": "macfos", "invoice_no": f["original_name"], "order_id": None,
            "invoice_date": "2026-06-08", "order_date": None, "currency": "INR", "total_minor": 42200, "amounts_minor": [42200],
            "is_credit_note": False, "source": "pdf_text", "extraction_status": "ok",
        }])
        return inv


@pytest.fixture
def api():
    repo = FakeRepo()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    client = TestClient(app)
    client.cycle = Cycle(repo)
    yield client
    app.dependency_overrides.clear()


def entry(view, name):
    return next(e for e in view["entries"] if e["file_name"] == name)


def set_aside(api):
    r = api.post(f"/api/invoices/{api.cycle.invoice['id']}/not-invoice")
    assert r.status_code == 200, r.text
    return r.json()


def restore(api, file_id, expected=200):
    r = api.post(f"/api/files/{file_id}/restore")
    assert r.status_code == expected, r.text
    return r.json()


def test_a_file_set_aside_can_be_restored_and_is_then_waiting_to_be_read(api):
    c = api.cycle
    view = set_aside(api)
    aside = entry(view, "wrong.pdf")
    assert aside["state"] == "ignored" and aside["can_restore"] is True and aside["invoice_id"] is None
    assert c.repo.get_file(api.cycle.wrong["id"])["note"] == "marked as not an invoice by harsh@create-ed.in"
    assert api.cycle.wrong["id"] not in [f["id"] for f in readable_files(c.repo, c.cid)]

    back = entry(restore(api, api.cycle.wrong["id"]), "wrong.pdf")
    assert back["state"] == "unread" and back["can_restore"] is False and back["file_kind"] == "invoice"
    row = c.repo.get_file(api.cycle.wrong["id"])
    assert row["kind"] == "invoice" and row["note"] is None
    assert api.cycle.wrong["id"] in [f["id"] for f in readable_files(c.repo, c.cid)]  # the next "Read invoices" reads it again
    actions = [e["action"] for e in c.repo.events]
    assert actions == ["invoice_ignored", "invoice_restored"]
    assert c.repo.events[-1]["actor"] == "harsh@create-ed.in" and c.repo.events[-1]["payload"]["file"] == "wrong.pdf"


def test_the_other_invoices_are_untouched_by_a_set_aside_and_a_restore(api):
    set_aside(api)
    restore(api, api.cycle.wrong["id"])
    assert entry(api.get(f"/api/cycles/{api.cycle.cid}/invoices").json(), "good.pdf")["state"] == "ok"


def test_a_copy_of_the_statement_cannot_be_restored(api):
    view = api.get(f"/api/cycles/{api.cycle.cid}/invoices").json()
    assert entry(view, "statement-copy.pdf")["state"] == "ignored" and entry(view, "statement-copy.pdf")["can_restore"] is False
    r = restore(api, api.cycle.copy["id"], 409)
    assert "Only a file you set aside" in r["detail"]
    assert api.cycle.repo.get_file(api.cycle.copy["id"])["kind"] == "ignored"


def test_an_ordinary_invoice_file_and_an_unknown_file_cannot_be_restored(api):
    assert restore(api, api.cycle.good["id"], 409)["detail"].startswith("Only a file you set aside")
    assert api.post(f"/api/files/{NIL}/restore").status_code == 404
    assert api.cycle.repo.events == []  # nothing was written


def test_restoring_needs_a_token():
    assert TestClient(app).post(f"/api/files/{NIL}/restore").status_code == 401


def test_restoring_twice_is_refused_the_second_time(api):
    set_aside(api)
    restore(api, api.cycle.wrong["id"])
    restore(api, api.cycle.wrong["id"], 409)


def test_restoring_after_an_export_is_an_edit_that_moves_the_cycle_back_to_matched(api):
    set_aside(api)
    api.cycle.repo.update_cycle(api.cycle.cid, {"status": "exported"})
    restore(api, api.cycle.wrong["id"])
    assert api.cycle.repo.get_cycle(api.cycle.cid)["status"] == "matched"
