"""The June invoice ZIP end to end through upload and reading (fakes for the database and storage).

Needs the git-ignored files and poppler's pdftotext: runs in Docker, skips elsewhere. Nothing is
uploaded anywhere.
"""

import collections
import shutil
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.engine.invoices.types import ExtractedInvoice
from app.services.ingest import Incoming, Limits, ingest_upload
from app.services.invoices import correct_invoice, invoices_view, run_extract
from fakes import FakeRepo, FakeStorage
from vision_expected import CHOSEN_BY_HAND, EXPECTED, mismatches, model_answer

FIXTURES = Path(__file__).parent / "fixtures_private"
LIMITS = Limits(max_file_bytes=50 * 1024 * 1024, max_zip_total_bytes=300 * 1024 * 1024, max_zip_entries=1000)
ZIPS = sorted(FIXTURES.glob("June2026*invoice*.zip"))
STATEMENTS = sorted(FIXTURES.glob("CC*June*2026*.pdf"))

pytestmark = [
    pytest.mark.skipif(not (ZIPS and STATEMENTS), reason="June fixtures not in tests/fixtures_private/"),
    pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext (poppler) not installed; run in Docker"),
]


@pytest.fixture(scope="module")
def june():
    repo, storage = FakeRepo(), FakeStorage()
    cid = repo.create_cycle(None, "t")["id"]
    for kind, path in (("statement", STATEMENTS[0]), ("invoices", ZIPS[0])):
        ingest_upload(
            repo=repo, storage=storage, cycle=repo.get_cycle(cid), kind=kind,
            uploads=[Incoming(path.name, path.read_bytes())], actor="t", limits=LIMITS,
        )
    repo.update_cycle(cid, {"status": "statement_confirmed"})
    run_extract(repo=repo, storage=storage, cycle_id=cid, actor="t")  # the real pdftotext
    return SimpleNamespace(repo=repo, cid=cid, storage=storage)


def test_test_6_1_and_6_2_the_counters(june):
    repo, cid = june.repo, june.cid
    cycle = repo.get_cycle(cid)
    assert cycle["job_status"] == "done", cycle["job_message"]
    assert cycle["status"] == "invoices_extracted"
    view = invoices_view(repo, cycle)
    counts = view["counts"]
    assert counts["invoices"] == 112  # from 111 PDF files
    assert counts["pending"] == 12  # the images, left for the vision slice
    assert counts["duplicate_files"] == 2 and counts["ignored"] == 1  # from upload
    assert counts["duplicate_invoices"] == 0
    assert counts["failed"] == 0 and counts["unread"] == 0
    assert counts["files"] == 126
    assert "Invoices read: 112 invoices from 111 files" in cycle["job_message"]  # 123 files read: 111 PDFs + 12 images
    assert "12 waiting for AI" in cycle["job_message"]  # no AI client in this test: the images stay pending


def test_test_6_3_62_amazon_invoices_from_61_files(june):
    repo, cid = june.repo, june.cid
    amazon = [i for i in repo.list_invoices(cid) if i["vendor_key"] == "amazon" and i["source"] == "pdf_text"]
    assert len(amazon) == 62 and len({i["file_id"] for i in amazon}) == 61


def test_test_6_4_to_6_9_known_files(june):
    repo, cid = june.repo, june.cid
    entries = {}
    for e in invoices_view(repo, repo.get_cycle(cid))["entries"]:
        entries.setdefault(e["file_name"], []).append(e)
    two = entries["280626_Amazon_1263.pdf"]
    assert [(e["invoice_no"], e["total_minor"], e["order_id"]) for e in two] == [
        ("MAA4-1138", 34900, "408-8124784-9796354"), ("MAA4-982422", 91400, "408-8124784-9796354"),
    ]
    (single,) = entries["130626_Amazon_928.27.pdf"]
    assert (single["order_id"], single["invoice_no"], single["invoice_date"], single["total_minor"]) == (
        "408-4454576-4641947", "IN-9370", "2026-06-13", 92827,
    )
    (macfos,) = entries["190626_Macfos_715.pdf"]
    assert (macfos["total_minor"], macfos["invoice_date"]) == (61100, "2026-06-19")
    (indigo,) = entries["TaxInvoiceMH1262706AY53125.pdf"]
    assert (indigo["vendor_name"], indigo["total_minor"], indigo["invoice_date"]) == ("IndiGo", 833300, "2026-06-04")
    assert repo.invoices[indigo["invoice_id"]]["extra"]["pnr"] == "YGDDKH"
    (dtdc,) = entries["DTDC_215.pdf"]
    assert (dtdc["vendor_name"], dtdc["total_minor"]) == ("DTDC", 21501)
    (fathom,) = entries["Fathom $36.pdf"]
    assert (fathom["vendor_name"], fathom["currency"], fathom["total_minor"], fathom["invoice_date"]) == (
        "Fathom", "USD", 3600, "2026-06-20",
    )


def test_test_6_10_the_file_level_duplicates_and_the_ignored_copy(june):
    repo, cid = june.repo, june.cid
    view = invoices_view(repo, repo.get_cycle(cid))
    states = collections.Counter(e["state"] for e in view["entries"])
    assert states["duplicate"] == 2 and states["ignored"] == 1 and states["pending"] == 12 and states["needs_check"] == 1
    dupes = {e["file_name"] for e in view["entries"] if e["state"] == "duplicate"}
    assert len(dupes) == 2 and all(e["invoice_id"] is None for e in view["entries"] if e["state"] == "duplicate")


class AnsweringVision:
    """A fake model that gives the right answer for each June image (found by its bytes)."""

    def __init__(self):
        from app.engine.invoices.vision import VisionReply

        self.reply_type = VisionReply
        self.answers: dict[bytes, str] = {}
        self.calls = 0
        with zipfile.ZipFile(ZIPS[0]) as z:
            for info in z.infolist():
                name = Path(info.filename).name
                if name in EXPECTED:
                    self.answers[z.read(info)] = model_answer(EXPECTED[name])

    def read(self, image, media_type, instructions, schema):
        self.calls += 1
        assert media_type == "image/png"
        return self.reply_type(text=self.answers[image], model="fake", input_tokens=1000, output_tokens=60)


@pytest.fixture(scope="module")
def june_ai():
    repo, storage, vision = FakeRepo(), FakeStorage(), AnsweringVision()
    cid = repo.create_cycle(None, "t")["id"]
    for kind, path in (("statement", STATEMENTS[0]), ("invoices", ZIPS[0])):
        ingest_upload(
            repo=repo, storage=storage, cycle=repo.get_cycle(cid), kind=kind,
            uploads=[Incoming(path.name, path.read_bytes())], actor="t", limits=LIMITS,
        )
    repo.update_cycle(cid, {"status": "statement_confirmed"})
    run_extract(repo=repo, storage=storage, cycle_id=cid, actor="t", vision=vision)
    return SimpleNamespace(repo=repo, cid=cid, storage=storage, vision=vision)


def test_test_7_1_the_twelve_images_are_read_and_nothing_is_pending(june_ai):
    repo, cid = june_ai.repo, june_ai.cid
    cycle = repo.get_cycle(cid)
    assert cycle["job_status"] == "done", cycle["job_message"]
    counts = invoices_view(repo, cycle)["counts"]
    assert counts["pending"] == 0 and counts["failed"] == 0
    assert counts["invoices"] == 124  # 112 from PDF text + 12 from images
    # Four images print no vendor name (left for a person) plus the Mailchimp receipt (no total line).
    assert counts["needs_check"] == 5
    assert june_ai.vision.calls == 12
    assert "12 read by AI" in cycle["job_message"] and "waiting for AI" not in cycle["job_message"]


def test_test_7_2_to_7_8_each_image_gives_its_expected_invoice(june_ai):
    view = invoices_view(june_ai.repo, june_ai.repo.get_cycle(june_ai.cid))
    rows = {e["file_name"]: e for e in view["entries"] if e["source"] == "vision"}
    assert set(rows) == set(EXPECTED)
    for name, entry in rows.items():
        item = ExtractedInvoice(
            vendor_key=entry["vendor_key"], invoice_no=entry["invoice_no"], order_id=entry["order_id"],
            invoice_date=date.fromisoformat(entry["invoice_date"]) if entry["invoice_date"] else None,
            order_date=date.fromisoformat(entry["order_date"]) if entry["order_date"] else None,
            total_minor=entry["total_minor"], extraction_status="ok" if entry["state"] == "ok" else entry["state"],
            problems=entry["problems"],
        )
        assert mismatches(item, EXPECTED[name]) == [], name
        assert entry["currency"] == "INR"
        assert entry["state"] == ("ok" if EXPECTED[name]["vendor"] else "needs_check"), name


def test_reading_again_makes_no_new_ai_calls_and_changes_nothing(june_ai):
    repo, cid = june_ai.repo, june_ai.cid
    before = sorted((i["file_id"], i["block_index"], i["total_minor"], i["source"]) for i in repo.list_invoices(cid))
    run_extract(repo=repo, storage=june_ai.storage, cycle_id=cid, actor="t", vision=june_ai.vision)
    assert june_ai.vision.calls == 12
    assert sorted((i["file_id"], i["block_index"], i["total_minor"], i["source"]) for i in repo.list_invoices(cid)) == before


def test_a_person_chooses_the_vendor_of_the_images_that_print_none(june_ai):
    repo, cid = june_ai.repo, june_ai.cid
    cycle = repo.get_cycle(cid)
    entries = {e["file_name"]: e for e in invoices_view(repo, cycle)["entries"]}
    for name, vendor in CHOSEN_BY_HAND.items():
        entry = entries[name]
        assert entry["state"] == "needs_check" and entry["vendor_key"] is None
        assert entry["problems"] == ["The image does not show a vendor name. Open the file and choose the vendor"]
        correct_invoice(repo, cycle, repo.get_invoice(entry["invoice_id"]), {"vendor_key": vendor}, "t")
    after = {e["file_name"]: e for e in invoices_view(repo, cycle)["entries"]}
    for name, vendor in CHOSEN_BY_HAND.items():
        assert (after[name]["state"], after[name]["vendor_key"], after[name]["source"]) == ("ok", vendor, "manual"), name
        assert after[name]["total_minor"] == EXPECTED[name]["total"]  # what the AI read is kept
    # Only the Mailchimp receipt is left to check, and a re-read keeps the chosen vendors without new AI calls.
    calls = june_ai.vision.calls
    run_extract(repo=repo, storage=june_ai.storage, cycle_id=cid, actor="t", vision=june_ai.vision)
    assert june_ai.vision.calls == calls
    again = invoices_view(repo, cycle)
    assert again["counts"]["needs_check"] == 1
    assert {e["file_name"] for e in again["entries"] if e["state"] == "needs_check"} == {"mailchimp-receipt-MC26118597.pdf"}


def test_reading_the_whole_set_again_gives_the_same_result(june):
    repo, cid, storage = june.repo, june.cid, june.storage
    key = lambda: sorted((i["file_id"], i["block_index"], i["total_minor"], i["vendor_key"]) for i in repo.list_invoices(cid))  # noqa: E731
    before = key()
    assert len(before) == 124  # 112 invoices + 12 pending image rows
    run_extract(repo=repo, storage=storage, cycle_id=cid, actor="t")
    assert repo.get_cycle(cid)["job_status"] == "done"
    assert key() == before
