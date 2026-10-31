"""Adding a vendor by hand (POST /api/vendors) and using it on an invoice."""

import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.db import get_repo
from app.engine.invoices.detect import detect_vendor
from app.engine.invoices.types import VendorPattern
from app.engine.matcher import Vendor, vendor_for_line
from app.main import app
from app.services.vision_client import get_vision
from app.storage import get_storage
from fakes import FakeRepo, FakeStorage
from seed import seed_rows
from test_api_invoices import listing, new_cycle, read

USER = CurrentUser(email="harsh@create-ed.in", user_id="u1")


@pytest.fixture
def api(monkeypatch):
    repo, storage = FakeRepo(), FakeStorage()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_vision] = lambda: None
    from test_api_invoices import PDFS
    from test_api_statement import statement_text

    monkeypatch.setattr("app.services.statement.pdf_text", lambda data, **kw: statement_text())
    monkeypatch.setattr("app.services.ingest.pdf_text", lambda data, **kw: "Tax invoice")
    monkeypatch.setattr("app.services.invoices.pdf_text", lambda data, **kw: PDFS[data])
    client = TestClient(app)
    client.repo = repo
    yield client
    app.dependency_overrides.clear()


def add(api, name, statement_text=None):
    return api.post("/api/vendors", json={"name": name, "statement_text": statement_text})


def test_it_needs_a_token():
    assert TestClient(app).post("/api/vendors", json={"name": "Zoom"}).status_code == 401


def test_manus_and_twilio_are_in_the_vendor_list_with_patterns_that_find_them():
    rows = {r["vendor_key"]: r for r in seed_rows()}
    assert rows["manus"]["display_name"] == "Manus" and rows["twilio"]["display_name"] == "Twilio"
    vendors = [Vendor(r["vendor_key"], r["display_name"], r["statement_pattern"], r["match_mode"]) for r in rows.values()]
    assert vendor_for_line("TWILIO SENDGRID DENVER CO", vendors).key == "twilio"
    assert vendor_for_line("MANUS AI SINGAPORE SG", vendors).key == "manus"
    patterns = [VendorPattern(r["vendor_key"], r["invoice_pattern"]) for r in rows.values()]
    assert detect_vendor("Invoice from Twilio Inc.\nTotal $10.00", patterns) == "twilio"


def test_a_new_vendor_is_added_with_a_key_and_escaped_patterns(api):
    r = add(api, "Zoom Video")
    assert r.status_code == 200 and r.json() == {"key": "zoomvideo", "name": "Zoom Video"}
    (row,) = api.repo.added_vendors
    assert row["match_mode"] == "single" and row["active"] and row["date_before_days"] == 7
    # The patterns find the typed name (any capitalisation) on a statement line and on an invoice.
    vendors = [Vendor(row["vendor_key"], row["display_name"], row["statement_pattern"], row["match_mode"])]
    assert vendor_for_line("ZOOM VIDEO COMM SAN JOSE CA", vendors).key == "zoomvideo"
    assert detect_vendor("Zoom Video Communications\nTotal 10", [VendorPattern("zoomvideo", row["invoice_pattern"])]) == "zoomvideo"


def test_the_statement_text_can_differ_from_the_name(api):
    add(api, "OpenAI Labs", "OPENAI.COM")
    (row,) = api.repo.added_vendors
    vendors = [Vendor(row["vendor_key"], row["display_name"], row["statement_pattern"], row["match_mode"])]
    assert vendor_for_line("OPENAI.COM SAN FRANCISCO US", vendors) is not None
    assert vendor_for_line("OPENAI LABS", vendors) is None  # only the statement text is used for lines


def test_special_characters_are_taken_literally_never_as_a_pattern(api):
    r = add(api, "A+B (India) Pvt. Ltd.")
    assert r.status_code == 200
    (row,) = api.repo.added_vendors
    vendors = [Vendor(row["vendor_key"], row["display_name"], row["statement_pattern"], row["match_mode"])]
    assert vendor_for_line("A+B (INDIA) PVT. LTD. MUMBAI", vendors) is not None
    assert vendor_for_line("AAB (INDIA) PVT. LTD.", vendors) is None  # "+" is not a regex quantifier here
    assert r.json()["key"] == "abindiapvtltd"


def test_the_same_name_again_returns_the_existing_vendor_without_adding_another(api):
    first = add(api, "Zoom Video").json()
    again = add(api, "  zoom   VIDEO ").json()
    assert again == first and len(api.repo.added_vendors) == 1
    assert add(api, "manus").json() == {"key": "manus", "name": "Manus"}  # a seeded vendor too
    assert api.repo.added_vendors[0]["vendor_key"] == "zoomvideo"


def test_a_name_with_the_same_letters_as_another_vendor_gets_its_own_key(api):
    assert add(api, "Zoom-Video").json()["key"] == "zoomvideo"
    assert add(api, "Zoom Video!").json()["key"] == "zoomvideo2"


@pytest.mark.parametrize("name", ["", " ", "a", "!!", "x" * 61])
def test_an_unusable_name_is_refused(api, name):
    r = add(api, name)
    assert r.status_code == 422 and api.repo.added_vendors == []


def test_an_added_vendor_is_offered_in_the_invoice_list_and_can_be_set_on_an_invoice(api):
    cid = new_cycle(api)
    read(api, cid)
    assert "zoomvideo" not in {v["key"] for v in listing(api, cid)["vendors"]}
    add(api, "Zoom Video")
    view = listing(api, cid)
    assert {"key": "zoomvideo", "name": "Zoom Video"} in view["vendors"]
    target = next(e for e in view["entries"] if e["invoice_id"] and e["state"] == "needs_check") if any(
        e["invoice_id"] and e["state"] == "needs_check" for e in view["entries"]
    ) else next(e for e in view["entries"] if e["invoice_id"])
    r = api.patch(f"/api/invoices/{target['invoice_id']}", json={"vendor_key": "zoomvideo"})
    assert r.status_code == 200
    updated = next(e for e in r.json()["entries"] if e["invoice_id"] == target["invoice_id"])
    assert updated["vendor_key"] == "zoomvideo" and updated["vendor_name"] == "Zoom Video"
