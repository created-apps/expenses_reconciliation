"""Ingest of the real June and September files (git-ignored, in tests/fixtures_private/).

Needs the files and poppler's pdftotext, so these run in Docker (`docker compose run --rm tests`)
and skip anywhere else. Only fakes are used for the database and storage: nothing is uploaded.
"""

import collections
import shutil
from pathlib import Path

import pytest

from app.services.ingest import Incoming, Limits, ingest_upload
from fakes import FakeRepo, FakeStorage

FIXTURES = Path(__file__).parent / "fixtures_private"
LIMITS = Limits(max_file_bytes=50 * 1024 * 1024, max_zip_total_bytes=300 * 1024 * 1024, max_zip_entries=1000)


def first(pattern: str) -> Path | None:
    found = sorted(FIXTURES.glob(pattern))
    return found[0] if found else None


STATEMENT = first("CC*June*2026*.pdf")
JUNE_ZIP = first("June2026*invoice*.zip")
SEPT_ZIP = first("Tax invoice documents*.zip")
SEPT_CSV = first("reconciliation_from_*.csv")

needs_poppler = pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext (poppler) not installed; run in Docker")
needs_june = pytest.mark.skipif(not (STATEMENT and JUNE_ZIP), reason="June fixtures not in tests/fixtures_private/")


def upload(repo, storage, cycle_id, kind, path: Path):
    return ingest_upload(
        repo=repo, storage=storage, cycle=repo.get_cycle(cycle_id), kind=kind,
        uploads=[Incoming(path.name, path.read_bytes())], actor="test@example.com", limits=LIMITS,
    )


def tally(repo, cycle_id):
    return collections.Counter((f["kind"], f["status"]) for f in repo.list_files(cycle_id))


@needs_june
@needs_poppler
def test_june_statement_then_invoice_zip():
    repo, storage = FakeRepo(), FakeStorage()
    cid = repo.create_cycle(None, "t")["id"]
    assert upload(repo, storage, cid, "statement", STATEMENT).files[0]["status"] == "uploaded"
    result = upload(repo, storage, cid, "invoices", JUNE_ZIP)
    assert result.rejected == []

    counts = tally(repo, cid)
    # 126 files in the ZIP. Two pairs are byte-identical copies (recorded as duplicates), and the
    # statement copy is byte-identical to the statement PDF itself.
    assert counts == {
        ("statement", "uploaded"): 1,
        ("zip", "processed"): 1,
        ("invoice", "uploaded"): 123,
        ("invoice", "duplicate"): 2,
        ("ignored", "duplicate"): 1,
    }
    members = [f for f in result.files if f["kind"] != "zip"]
    assert len(members) == 126
    by_name = {f["original_name"]: f for f in members}

    ignored = [f for f in members if f["kind"] == "ignored"]
    assert len(ignored) == 1 and ignored[0]["original_name"].startswith("ACFrOg")
    assert ignored[0]["note"] == "copy of the statement"

    # The later file of each identical pair is the duplicate, as in ZIP order.
    assert by_name["140626_Amazon_525.pdf"]["status"] == "duplicate"
    assert by_name["140626_Amazon_525(1).pdf"]["status"] == "uploaded"
    assert by_name["MH2727WI016880_GC001_10-Jun-2026.pdf"]["status"] == "duplicate"
    assert by_name["DTDC_488.pdf"]["status"] == "uploaded"

    # Stored: statement + ZIP + the 123 live invoices. Duplicates are not stored again.
    assert len(storage.objects) == 1 + 1 + 123
    assert all(f["parent_file_id"] for f in members)
    assert by_name["Fathom $36.pdf"]["storage_path"].endswith("/Fathom_36.pdf")


@needs_june
@needs_poppler
def test_june_zip_first_then_the_statement_still_leaves_one_live_statement():
    repo, storage = FakeRepo(), FakeStorage()
    cid = repo.create_cycle(None, "t")["id"]
    upload(repo, storage, cid, "invoices", JUNE_ZIP)
    after_zip = tally(repo, cid)
    assert after_zip[("ignored", "uploaded")] == 1  # found by its text, not by hash

    upload(repo, storage, cid, "statement", STATEMENT)
    counts = tally(repo, cid)
    assert counts[("statement", "uploaded")] == 1
    assert counts[("ignored", "duplicate")] == 1 and counts[("ignored", "uploaded")] == 0


@needs_june
@needs_poppler
def test_the_same_june_zip_again_adds_nothing():
    repo, storage = FakeRepo(), FakeStorage()
    cid = repo.create_cycle(None, "t")["id"]
    upload(repo, storage, cid, "invoices", JUNE_ZIP)
    stored, rows = len(storage.objects), len(repo.files)
    again = upload(repo, storage, cid, "invoices", JUNE_ZIP)
    assert [(f["kind"], f["status"]) for f in again.files] == [("zip", "duplicate")]
    assert len(storage.objects) == stored and len(repo.files) == rows + 1


@pytest.mark.skipif(not (SEPT_ZIP and SEPT_CSV), reason="September fixtures not in tests/fixtures_private/")
@needs_poppler
def test_september_amazon_zip_and_csv():
    repo, storage = FakeRepo(), FakeStorage()
    cid = repo.create_cycle(None, "t")["id"]
    result = upload(repo, storage, cid, "invoices", SEPT_ZIP)
    assert result.rejected == []
    members = [f for f in result.files if f["kind"] != "zip"]
    assert len(members) == 43
    assert not any(f["kind"] == "ignored" for f in members)  # no statement copy among Amazon invoices

    csv_result = upload(repo, storage, cid, "amazon_report", SEPT_CSV)
    assert [(f["kind"], f["status"], f["mime_type"]) for f in csv_result.files] == [("amazon_report", "uploaded", "text/csv")]
