"""The June cycle built in memory from the real, git-ignored files (Docker only: needs poppler).

Statement parsed from the real PDF, every invoice read (PDFs from their text, the 12 images by a fake
model that answers exactly what the images say), and the vendors of the four images that print none
chosen by hand, as a person would. Nothing is uploaded anywhere and no real model is called.
"""

import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.engine.invoices.vision import VisionReply
from app.services.ingest import Incoming, Limits, ingest_upload
from app.services.invoices import correct_invoice, run_extract
from app.services.statement import confirm_statement, run_parse, statement_file
from fakes import FakeRepo, FakeStorage
from vision_expected import CHOSEN_BY_HAND, EXPECTED, model_answer

FIXTURES = Path(__file__).parent / "fixtures_private"
LIMITS = Limits(max_file_bytes=50 * 1024 * 1024, max_zip_total_bytes=300 * 1024 * 1024, max_zip_entries=1000)


def first(pattern: str) -> Path | None:
    found = sorted(FIXTURES.glob(pattern))
    return found[0] if found else None


STATEMENT = first("CC*June*2026*.pdf")
JUNE_ZIP = first("June2026*invoice*.zip")


class AnsweringVision:
    """A fake model that gives the right answer for each June image (found by its bytes)."""

    def __init__(self, zip_path: Path):
        self.answers: dict[bytes, str] = {}
        self.calls = 0
        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                name = Path(info.filename).name
                if name in EXPECTED:
                    self.answers[z.read(info)] = model_answer(EXPECTED[name])

    def read(self, image, media_type, instructions, schema):
        self.calls += 1
        return VisionReply(text=self.answers[image], model="fake", input_tokens=1000, output_tokens=60)


def build_june() -> SimpleNamespace:
    repo, storage, vision = FakeRepo(), FakeStorage(), AnsweringVision(JUNE_ZIP)
    cid = repo.create_cycle(None, "t")["id"]
    for kind, path in (("statement", STATEMENT), ("invoices", JUNE_ZIP)):
        ingest_upload(
            repo=repo, storage=storage, cycle=repo.get_cycle(cid), kind=kind,
            uploads=[Incoming(path.name, path.read_bytes())], actor="t", limits=LIMITS,
        )
    run_parse(repo=repo, storage=storage, cycle_id=cid, file=statement_file(repo, cid), actor="t")  # real pdftotext
    assert repo.get_cycle(cid)["job_status"] == "done", repo.get_cycle(cid)["job_message"]
    confirm_statement(repo, repo.get_cycle(cid), "t")
    run_extract(repo=repo, storage=storage, cycle_id=cid, actor="t", vision=vision)
    assert repo.get_cycle(cid)["job_status"] == "done", repo.get_cycle(cid)["job_message"]

    # A person chooses the vendor of the four images that print none.
    names = {f["id"]: f["original_name"] for f in repo.list_files(cid)}
    for invoice in repo.list_invoices(cid):
        vendor = CHOSEN_BY_HAND.get(names[invoice["file_id"]])
        if vendor:
            correct_invoice(repo, repo.get_cycle(cid), invoice, {"vendor_key": vendor}, "a person")
    return SimpleNamespace(repo=repo, cid=cid, storage=storage, vision=vision, names=names)
