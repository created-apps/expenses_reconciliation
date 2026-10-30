"""API tests with the database and storage replaced by in-memory fakes."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.db import get_repo
from app.main import app
from app.storage import get_storage
from fakes import FakeRepo, FakeStorage

USER = CurrentUser(email="harsh@create-ed.in", user_id="u1")
PDF = b"%PDF-1.4 something"


@pytest.fixture
def api(monkeypatch):
    repo, storage = FakeRepo(), FakeStorage()
    settings = Settings(max_file_mb=1, max_request_mb=5, max_zip_total_mb=5, max_zip_entries=20, _env_file=None)
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_settings] = lambda: settings
    # No poppler needed here: a PDF counts as a statement copy only if it says so.
    monkeypatch.setattr(
        "app.services.ingest.pdf_text",
        lambda data: "CREDIT CARD STATEMENT ... STATEMENT SUMMARY" if b"STATEMENT" in data else "Tax invoice",
    )
    client = TestClient(app)
    client.repo, client.storage = repo, storage
    yield client
    app.dependency_overrides.clear()


def new_cycle(api, label=None):
    r = api.post("/api/cycles", json={"label": label} if label is not None else None)
    assert r.status_code == 201
    return r.json()


def upload(api, cycle_id, kind, files):
    return api.post(f"/api/cycles/{cycle_id}/files", data={"kind": kind}, files=[("files", f) for f in files])


def test_every_endpoint_needs_a_token():
    client = TestClient(app)
    for method, path in [("get", "/api/cycles"), ("post", "/api/cycles"),
                         ("get", "/api/cycles/6f9619ff-8b86-d011-b42d-00c04fc964ff"),
                         ("delete", "/api/cycles/6f9619ff-8b86-d011-b42d-00c04fc964ff"),
                         ("get", "/api/cycles/6f9619ff-8b86-d011-b42d-00c04fc964ff/files"),
                         ("get", "/api/files/6f9619ff-8b86-d011-b42d-00c04fc964ff/url")]:
        assert getattr(client, method)(path).status_code == 401, (method, path)


def test_create_with_and_without_a_label(api):
    plain = new_cycle(api)
    named = new_cycle(api, "  June 2026  ")
    assert plain["label"] is None and plain["status"] == "draft" and plain["created_by"] == USER.email
    assert named["label"] == "June 2026"
    assert plain["total_lines"] is None and plain["matched_lines"] is None and plain["open_items"] is None


def test_list_is_newest_first_and_counts_lines_when_there_are_any(api):
    a, b = new_cycle(api, "A"), new_cycle(api, "B")
    api.repo.transactions += [{"cycle_id": a["id"], "status": s} for s in ("Matched", "Matched", "Review", "Missing invoice", "Payment")]
    listing = api.get("/api/cycles").json()
    assert [c["label"] for c in listing] == ["B", "A"]
    assert (listing[1]["total_lines"], listing[1]["matched_lines"], listing[1]["open_items"]) == (5, 2, 2)
    assert listing[0]["total_lines"] is None


def test_detail_has_file_counts_and_404_for_unknown_or_bad_ids(api):
    c = new_cycle(api)
    upload(api, c["id"], "statement", [("CC.pdf", PDF, "application/pdf")])
    detail = api.get(f"/api/cycles/{c['id']}").json()
    assert detail["files"]["statement"] == 1 and detail["files"]["total"] == 1
    assert api.get("/api/cycles/6f9619ff-8b86-d011-b42d-00c04fc964ff").status_code == 404
    assert api.get("/api/cycles/not-a-uuid").status_code == 422


def test_statement_upload_then_again_is_flagged_duplicate(api):
    c = new_cycle(api)
    first = upload(api, c["id"], "statement", [("CC.pdf", PDF, "application/pdf")]).json()
    assert [(f["kind"], f["status"], f["has_copy"]) for f in first["files"]] == [("statement", "uploaded", True)]
    again = upload(api, c["id"], "statement", [("CC.pdf", PDF, "application/pdf")]).json()
    assert [(f["status"], f["has_copy"]) for f in again["files"]] == [("duplicate", False)]
    assert "storage_path" not in first["files"][0] and "sha256" not in first["files"][0]


def test_unsupported_file_is_rejected_with_a_message(api):
    c = new_cycle(api)
    body = upload(api, c["id"], "invoices", [("notes.docx", b"x", "application/octet-stream")]).json()
    assert body == {"files": [], "rejected": [{"name": "notes.docx", "message": "File type not supported"}]}


def test_zip_upload_lists_container_first_then_members(api):
    c = new_cycle(api)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.pdf", b"%PDF a")
        z.writestr("b.pdf", b"%PDF STATEMENT copy")
        z.writestr("c.png", b"\x89PNG")
    body = upload(api, c["id"], "invoices", [("june.zip", buf.getvalue(), "application/zip")]).json()
    kinds = [(f["original_name"], f["kind"], f["status"]) for f in body["files"]]
    assert kinds[0] == ("june.zip", "zip", "processed")
    assert ("b.pdf", "ignored", "uploaded") in kinds
    listed = api.get(f"/api/cycles/{c['id']}/files").json()
    assert listed[0]["original_name"] == "june.zip" and len(listed) == 4
    assert api.get(f"/api/cycles/{c['id']}").json()["files"] == {
        "statement": 0, "invoices": 2, "ignored": 1, "duplicates": 0, "amazon_reports": 0, "zips": 1, "total": 4}


def test_bad_requests(api):
    c = new_cycle(api)
    assert upload(api, c["id"], "nonsense", [("a.pdf", PDF, "application/pdf")]).status_code == 422
    two = [("a.pdf", PDF, "application/pdf"), ("b.pdf", PDF + b"b", "application/pdf")]
    assert upload(api, c["id"], "statement", two).status_code == 422
    assert api.post(f"/api/cycles/{c['id']}/files", data={"kind": "invoices"}).status_code == 422
    assert upload(api, "6f9619ff-8b86-d011-b42d-00c04fc964ff", "statement", two[:1]).status_code == 404


def test_oversized_request_is_refused_up_front(api):
    c = new_cycle(api)
    r = api.post(f"/api/cycles/{c['id']}/files", data={"kind": "invoices"},
                 files=[("files", ("big.pdf", b"x" * (6 * 1024 * 1024), "application/pdf"))])
    assert r.status_code == 413


def test_signed_url_for_a_stored_file_and_404_for_a_duplicate(api):
    c = new_cycle(api)
    upload(api, c["id"], "statement", [("CC.pdf", PDF, "application/pdf")])
    dup = upload(api, c["id"], "statement", [("CC.pdf", PDF, "application/pdf")]).json()["files"][0]
    stored = next(f for f in api.get(f"/api/cycles/{c['id']}/files").json() if f["status"] == "uploaded")
    ok = api.get(f"/api/files/{stored['id']}/url").json()
    assert ok["url"].startswith("https://storage.test/cycles/") and ok["expires_in"] == 300 and ok["file_name"] == "CC.pdf"
    assert api.get(f"/api/files/{dup['id']}/url").status_code == 404
    assert api.get("/api/files/6f9619ff-8b86-d011-b42d-00c04fc964ff/url").status_code == 404


def test_signed_url_for_an_object_that_is_gone_from_storage_is_404_not_502(api):
    from storage3.exceptions import StorageApiError

    c = new_cycle(api)
    upload(api, c["id"], "statement", [("CC.pdf", PDF, "application/pdf")])
    stored = api.get(f"/api/cycles/{c['id']}/files").json()[0]

    def gone(path, expires_in):
        raise StorageApiError("Object not found", "not_found", 404)

    api.storage.signed_url = gone
    assert api.get(f"/api/files/{stored['id']}/url").status_code == 404


def test_other_storage_errors_become_a_generic_502(api):
    from storage3.exceptions import StorageApiError

    c = new_cycle(api)
    upload(api, c["id"], "statement", [("CC.pdf", PDF, "application/pdf")])
    stored = api.get(f"/api/cycles/{c['id']}/files").json()[0]

    def broken(path, expires_in):
        raise StorageApiError("secret internal detail", "internal", 500)

    api.storage.signed_url = broken
    r = TestClient(app, raise_server_exceptions=False).get(f"/api/files/{stored['id']}/url")
    assert r.status_code == 502 and "secret" not in r.text


def test_delete_removes_rows_and_stored_files(api):
    c = new_cycle(api)
    upload(api, c["id"], "statement", [("CC.pdf", PDF, "application/pdf")])
    upload(api, c["id"], "invoices", [("a.pdf", b"%PDF a", "application/pdf")])
    assert len(api.storage.objects) == 2
    assert api.delete(f"/api/cycles/{c['id']}").status_code == 204
    assert not api.storage.objects and not api.repo.files and not api.repo.cycles
    assert api.get(f"/api/cycles/{c['id']}").status_code == 404
    assert api.delete(f"/api/cycles/{c['id']}").status_code == 404


def test_delete_also_removes_objects_that_the_database_does_not_know_about(api):
    # An upload can reach storage while the client sees an error, leaving an object with no row.
    c = new_cycle(api)
    upload(api, c["id"], "statement", [("CC.pdf", PDF, "application/pdf")])
    orphan = f"cycles/{c['id']}/11111111-1111-4111-8111-111111111111/130626_Amazon_98.01.pdf"
    other_cycle = "cycles/22222222-2222-4222-8222-222222222222/x/keep.pdf"
    api.storage.objects[orphan] = b"stored but never recorded"
    api.storage.objects[other_cycle] = b"belongs to someone else"
    assert api.delete(f"/api/cycles/{c['id']}").status_code == 204
    assert orphan not in api.storage.objects
    assert list(api.storage.objects) == [other_cycle]  # nothing outside this cycle is touched


def test_exported_cycle_cannot_be_deleted(api):
    c = new_cycle(api)
    api.repo.cycles[c["id"]]["status"] = "exported"
    assert api.delete(f"/api/cycles/{c['id']}").status_code == 409
    assert c["id"] in api.repo.cycles


def test_if_storage_removal_fails_the_cycle_is_kept(api):
    c = new_cycle(api)
    upload(api, c["id"], "statement", [("CC.pdf", PDF, "application/pdf")])

    def broken(paths):
        raise RuntimeError("storage down")

    api.storage.remove = broken
    with pytest.raises(RuntimeError):
        api.delete(f"/api/cycles/{c['id']}")
    assert c["id"] in api.repo.cycles and api.repo.files
