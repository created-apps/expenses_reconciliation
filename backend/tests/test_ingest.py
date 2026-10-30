import io
import zipfile

import pytest

from app.pdf import PdfToolUnavailable
from app.services.ingest import IngestError, Incoming, Limits, ingest_upload
from amazon_samples import amazon_csv, row
from fakes import FakeRepo, FakeStorage

LIMITS = Limits(max_file_bytes=1_000_000, max_zip_total_bytes=5_000_000, max_zip_entries=50)
ACTOR = "harsh@create-ed.in"

STATEMENT = b"%PDF STATEMENT-COPY ICICI statement bytes"


def fake_text(data: bytes) -> str:
    if b"STATEMENT-COPY" in data:
        return "ICICI Bank CREDIT CARD STATEMENT\nSTATEMENT SUMMARY"
    return "Tax invoice"


def pdf(label: str) -> bytes:
    return f"%PDF invoice {label}".encode()


def make_zip(entries: dict[str, bytes], *, dirs: tuple[str, ...] = ()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for d in dirs:
            z.writestr(d if d.endswith("/") else d + "/", b"")
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def env():
    repo, storage = FakeRepo(), FakeStorage()
    cycle = repo.create_cycle(None, ACTOR)
    return repo, storage, cycle


def run(env, kind, uploads, *, limits=LIMITS, extract=fake_text):
    repo, storage, cycle = env
    cycle = repo.get_cycle(cycle["id"])  # fresh status
    return ingest_upload(
        repo=repo, storage=storage, cycle=cycle, kind=kind,
        uploads=[Incoming(n, d) for n, d in uploads], actor=ACTOR, limits=limits, extract_text=extract,
    )


def by_name(result):
    return {f["original_name"]: f for f in result.files}


def test_statement_is_stored_under_the_documented_path(env):
    repo, storage, cycle = env
    result = run(env, "statement", [("CC June 2026.pdf", STATEMENT)])
    (f,) = result.files
    assert (f["kind"], f["status"], f["mime_type"]) == ("statement", "uploaded", "application/pdf")
    assert f["storage_path"] == f"cycles/{cycle['id']}/{f['id']}/CC_June_2026.pdf"
    assert storage.objects[f["storage_path"]] == STATEMENT
    assert f["size_bytes"] == len(STATEMENT) and len(f["sha256"]) == 64


def test_same_statement_again_is_a_duplicate_and_there_is_still_one_statement(env):
    repo, storage, _ = env
    run(env, "statement", [("CC.pdf", STATEMENT)])
    again = run(env, "statement", [("CC again.pdf", STATEMENT)])
    (f,) = again.files
    assert f["status"] == "duplicate" and f["storage_path"] is None
    assert "same file as CC.pdf" in f["note"]
    live = [r for r in repo.files.values() if r["kind"] == "statement" and r["status"] != "duplicate"]
    assert len(live) == 1 and len(storage.objects) == 1


def test_a_different_statement_replaces_the_old_one_while_the_cycle_is_a_draft(env):
    repo, storage, _ = env
    first = run(env, "statement", [("one.pdf", b"%PDF one")]).files[0]
    run(env, "statement", [("two.pdf", b"%PDF two")])
    live = [r for r in repo.files.values() if r["kind"] == "statement"]
    assert [r["original_name"] for r in live] == ["two.pdf"]
    assert first["storage_path"] in storage.removed and len(storage.objects) == 1


def test_a_different_statement_replaces_one_that_was_read_but_not_confirmed(env):
    repo, storage, cycle = env
    run(env, "statement", [("one.pdf", b"%PDF one")])
    cid = cycle["id"]
    repo.update_cycle(cid, {"status": "statement_parsed", "period_start": "2026-05-21", "summary_purchases_paise": 5})
    repo.transactions.append({"cycle_id": cid, "status": None, "txn_date": "2026-05-21", "ser_no": "1"})
    run(env, "statement", [("two.pdf", b"%PDF two")])
    assert [r["original_name"] for r in repo.files.values()] == ["two.pdf"]
    # Back to an unread statement: no lines, no header figures.
    assert repo.cycles[cid]["status"] == "draft" and repo.cycles[cid]["period_start"] is None
    assert repo.cycles[cid]["summary_purchases_paise"] is None and repo.list_transactions(cid) == []


def test_a_different_statement_is_refused_once_the_statement_is_confirmed(env):
    repo, storage, cycle = env
    run(env, "statement", [("one.pdf", b"%PDF one")])
    repo.cycles[cycle["id"]]["status"] = "statement_confirmed"
    with pytest.raises(IngestError) as e:
        run(env, "statement", [("two.pdf", b"%PDF two")])
    assert e.value.status_code == 409
    assert [r["original_name"] for r in repo.files.values()] == ["one.pdf"]


@pytest.mark.parametrize(
    "kind, name",
    [("statement", "photo.png"), ("invoices", "notes.docx"), ("invoices", "notes.txt"),
     ("invoices", "report.csv"), ("amazon_report", "invoice.pdf")],
)
def test_unsupported_types_are_rejected_not_stored(env, kind, name):
    repo, storage, _ = env
    result = run(env, kind, [(name, b"data")])
    assert result.files == [] and result.rejected == [{"name": name, "message": "File type not supported"}]
    assert not repo.files and not storage.objects


def test_zip_is_only_accepted_as_invoices(env):
    result = run(env, "statement", [("a.zip", make_zip({"a.pdf": b"x"}))])
    assert result.rejected[0]["message"] == "File type not supported"


def test_zip_is_expanded_with_junk_skipped_and_the_container_recorded(env):
    repo, storage, cycle = env
    blob = make_zip(
        {
            "inv1.pdf": pdf("1"), "sub/inv 2.PNG": b"\x89PNG img", "__MACOSX/._inv1.pdf": b"x",
            ".DS_Store": b"x", "notes.txt": b"x", "inner.zip": make_zip({"x.pdf": b"x"}),
        },
        dirs=("sub",),
    )
    result = run(env, "invoices", [("batch.zip", blob)])
    files = by_name(result)
    assert set(files) == {"batch.zip", "inv1.pdf", "inv 2.PNG"}
    container = files["batch.zip"]
    assert (container["kind"], container["status"], container["parent_file_id"]) == ("zip", "processed", None)
    assert container["storage_path"] in storage.objects
    for name in ("inv1.pdf", "inv 2.PNG"):
        assert files[name]["parent_file_id"] == container["id"] and files[name]["status"] == "uploaded"
        assert files[name]["kind"] == "invoice"
    assert files["inv 2.PNG"]["mime_type"] == "image/png"
    messages = {(r["name"], r["message"]) for r in result.rejected}
    assert messages == {("notes.txt", "File type not supported"), ("inner.zip", "Nested ZIP files are not expanded")}
    assert [r["kind"] for r in result.files][0] == "zip"  # container listed first


def test_identical_files_inside_one_upload_are_recorded_once_as_live(env):
    repo, storage, _ = env
    blob = make_zip({"a(1).pdf": pdf("same"), "a.pdf": pdf("same"), "b.pdf": pdf("other")})
    files = by_name(run(env, "invoices", [("z.zip", blob)]))
    assert files["a(1).pdf"]["status"] == "uploaded"
    assert files["a.pdf"]["status"] == "duplicate" and files["a.pdf"]["storage_path"] is None
    assert "same file as a(1).pdf" in files["a.pdf"]["note"]
    assert len(storage.objects) == 1 + 2  # the zip, a(1).pdf and b.pdf


def test_a_file_already_in_the_cycle_is_a_duplicate(env):
    run(env, "invoices", [("a.pdf", pdf("a"))])
    again = run(env, "invoices", [("copy of a", pdf("a")), ("a2.pdf", pdf("a")), ("new.pdf", pdf("new"))])
    statuses = {f["original_name"]: f["status"] for f in again.files}
    assert statuses == {"a2.pdf": "duplicate", "new.pdf": "uploaded"}
    assert again.rejected == [{"name": "copy of a", "message": "File type not supported"}]


def test_uploading_the_same_zip_twice_does_not_add_its_members_again(env):
    repo, storage, _ = env
    blob = make_zip({"a.pdf": pdf("a"), "b.pdf": pdf("b")})
    run(env, "invoices", [("z.zip", blob)])
    stored_before = len(storage.objects)
    again = run(env, "invoices", [("z again.zip", blob)])
    assert [(f["kind"], f["status"]) for f in again.files] == [("zip", "duplicate")]
    assert len(storage.objects) == stored_before and len(repo.files) == 4


def test_a_statement_copy_among_invoices_is_ignored_with_a_note(env):
    result = run(env, "invoices", [("ACFrOg.pdf", STATEMENT), ("inv.pdf", pdf("x"))])
    files = by_name(result)
    assert (files["ACFrOg.pdf"]["kind"], files["ACFrOg.pdf"]["note"], files["ACFrOg.pdf"]["status"]) == (
        "ignored", "copy of the statement", "uploaded")
    assert files["inv.pdf"]["kind"] == "invoice"


def test_a_copy_with_the_same_bytes_as_the_statement_is_ignored_even_though_it_is_a_hash_duplicate(env):
    # The June ZIP's copy is byte-identical to the statement PDF.
    repo, storage, _ = env
    run(env, "statement", [("CC.pdf", STATEMENT)])
    result = run(env, "invoices", [("copy.pdf", STATEMENT)])
    (f,) = result.files
    assert (f["kind"], f["status"], f["note"], f["storage_path"]) == ("ignored", "duplicate", "copy of the statement", None)
    assert len(storage.objects) == 1


def test_statement_uploaded_after_its_ignored_copy_still_becomes_the_live_statement(env):
    repo, storage, _ = env
    run(env, "invoices", [("copy.pdf", STATEMENT)])  # filed as an ignored copy first
    result = run(env, "statement", [("CC.pdf", STATEMENT)])
    (f,) = result.files
    assert (f["kind"], f["status"]) == ("statement", "uploaded")
    old = next(r for r in repo.files.values() if r["original_name"] == "copy.pdf")
    assert old["status"] == "duplicate" and old["kind"] == "ignored"
    live = [r for r in repo.files.values() if r["status"] != "duplicate"]
    assert [r["kind"] for r in live] == ["statement"]


def test_statement_copy_detection_ignores_images_and_runs_once_per_distinct_pdf(env):
    calls = []

    def counting(data):
        calls.append(data)
        return "Tax invoice"

    run(env, "invoices", [("a.pdf", pdf("a")), ("a2.pdf", pdf("a")), ("b.png", b"\x89PNG"), ("c.pdf", pdf("c"))],
        extract=counting)
    assert len(calls) == 2


def test_missing_poppler_is_a_clear_error_not_a_silent_miss(env):
    def no_poppler(data):
        raise PdfToolUnavailable("nope")

    with pytest.raises(IngestError) as e:
        run(env, "invoices", [("a.pdf", pdf("a"))], extract=no_poppler)
    assert e.value.status_code == 503 and "Docker" in e.value.message
    assert not env[0].files


def test_images_only_do_not_need_poppler(env):
    def no_poppler(data):
        raise PdfToolUnavailable("nope")

    result = run(env, "invoices", [("scan.png", b"\x89PNG")], extract=no_poppler)
    assert result.files[0]["status"] == "uploaded"


def test_a_new_amazon_report_replaces_the_old_one(env):
    repo, storage, _ = env
    run(env, "amazon_report", [("a.csv", amazon_csv(row(net="1.00")))])
    run(env, "amazon_report", [("b.csv", amazon_csv(row(net="2.00")))])
    assert [r["original_name"] for r in repo.files.values()] == ["b.csv"] and len(storage.objects) == 1


def test_new_files_on_an_exported_cycle_are_an_edit_that_moves_it_back_to_matched(env):
    repo, storage, cycle = env
    run(env, "amazon_report", [("a.csv", amazon_csv(row(net="1.00")))])
    repo.cycles[cycle["id"]]["status"] = "exported"
    run(env, "amazon_report", [("b.csv", amazon_csv(row(net="2.00")))])  # replacing the report is allowed now
    assert [r["original_name"] for r in repo.files.values()] == ["b.csv"]
    assert repo.cycles[cycle["id"]]["status"] == "matched"
    assert [e["action"] for e in repo.events].count("edited_after_export") == 1


def test_one_file_that_cannot_be_stored_is_recorded_as_failed_and_the_rest_go_through(env):
    repo, storage, cycle = env
    env = (repo, FakeStorage(fail_for=("bad",)), cycle)
    result = run(env, "invoices", [("good.pdf", pdf("g")), ("bad.pdf", pdf("b"))])
    files = by_name(result)
    assert files["good.pdf"]["status"] == "uploaded"
    assert files["bad.pdf"]["status"] == "failed" and "Could not store" in files["bad.pdf"]["error"]
    assert files["bad.pdf"]["storage_path"] is None


def test_a_failed_upload_removes_any_object_that_may_have_arrived_anyway(env):
    # A dropped connection can hide an upload that did reach storage.
    repo, _, cycle = env

    class ArrivesThenErrors(FakeStorage):
        def put(self, path, data, content_type):
            self.objects[path] = data  # the bytes land...
            raise RuntimeError("Server disconnected")  # ...but the client sees an error

    storage = ArrivesThenErrors()
    result = run((repo, storage, cycle), "invoices", [("190626_Macfos_715.pdf", pdf("m"))])
    assert result.files[0]["status"] == "failed"
    assert storage.objects == {}  # nothing left behind that no row points at


def test_a_failed_file_can_be_uploaded_again_and_is_not_a_duplicate_of_itself(env):
    repo, storage, cycle = env
    flaky = FakeStorage(fail_for=("bad",))
    first = run((repo, flaky, cycle), "invoices", [("good.pdf", pdf("g")), ("bad.pdf", pdf("b"))])
    assert by_name(first)["bad.pdf"]["status"] == "failed"

    flaky.fail_for = ()  # the network is back
    again = run((repo, flaky, cycle), "invoices", [("bad.pdf", pdf("b"))])
    (f,) = again.files
    assert f["status"] == "uploaded" and f["storage_path"] in flaky.objects
    rows = [r for r in repo.files.values() if r["original_name"] == "bad.pdf"]
    assert len(rows) == 1 and rows[0]["status"] == "uploaded"  # the failed row was replaced, not kept


def test_the_same_failed_file_failing_again_leaves_a_single_failed_row(env):
    repo, storage, cycle = env
    flaky = FakeStorage(fail_for=("bad",))
    run((repo, flaky, cycle), "invoices", [("bad.pdf", pdf("b"))])
    run((repo, flaky, cycle), "invoices", [("bad.pdf", pdf("b"))])
    rows = [r for r in repo.files.values() if r["original_name"] == "bad.pdf"]
    assert [r["status"] for r in rows] == ["failed"]


def test_failed_insert_cleans_up_what_was_stored_and_restores_demoted_rows(env):
    repo, storage, _ = env
    run(env, "invoices", [("copy.pdf", STATEMENT)])  # ignored copy, will be demoted by the statement

    original = repo.insert_files

    def boom(rows):
        raise RuntimeError("database down")

    repo.insert_files = boom
    before = set(storage.objects)
    with pytest.raises(RuntimeError):
        run(env, "statement", [("CC.pdf", STATEMENT)])
    repo.insert_files = original
    assert set(storage.objects) == before  # the new object was removed again
    old = next(iter(repo.files.values()))
    assert old["status"] == "uploaded"  # demotion undone


def test_limits_for_zips_and_files(env):
    too_many = make_zip({f"{i}.pdf": pdf(str(i)) for i in range(6)})
    r = run(env, "invoices", [("many.zip", too_many)], limits=Limits(1_000_000, 5_000_000, 5))
    assert "too many files" in r.rejected[0]["message"] and not r.files

    big = make_zip({"a.pdf": b"x" * 2000, "b.pdf": b"y" * 2000})
    r = run(env, "invoices", [("big.zip", big)], limits=Limits(10_000, 3_000, 50))
    assert "too large when unpacked" in r.rejected[0]["message"] and not r.files

    r = run(env, "invoices", [("huge.pdf", b"x" * 1500)], limits=Limits(1000, 5_000, 50))
    assert "too large" in r.rejected[0]["message"]

    r = run(env, "invoices", [("broken.zip", b"not a zip at all")])
    assert r.rejected[0]["message"] == "Not a valid ZIP file"

    r = run(env, "invoices", [("empty.pdf", b"")])
    assert r.rejected[0]["message"] == "The file is empty"


def test_single_file_slots_refuse_several_files(env):
    with pytest.raises(IngestError) as e:
        run(env, "statement", [("a.pdf", b"a"), ("b.pdf", b"b")])
    assert e.value.status_code == 422
    with pytest.raises(IngestError):
        run(env, "nonsense", [("a.pdf", b"a")])


def test_an_event_is_written_and_the_cycle_is_touched(env):
    repo, _, cycle = env
    before = repo.cycles[cycle["id"]]["updated_at"]
    run(env, "invoices", [("a.pdf", pdf("a")), ("x.docx", b"x")])
    (event,) = repo.events
    assert (event["action"], event["actor"]) == ("files_uploaded", ACTOR)
    assert event["payload"] == {"slot": "invoices", "stored": 1, "duplicates": 0, "rejected": 1}
    assert repo.cycles[cycle["id"]]["updated_at"] > before
