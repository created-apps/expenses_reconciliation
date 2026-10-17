"""Upload ingest: hash, expand ZIPs, classify, store in Storage, record in recon_files.

Orchestration only. The rules (allowed types, junk members, statement-copy markers, safe key
names) are in app/engine/ingest_rules.py. The repository, storage client and PDF text reader
are passed in, so tests can use in-memory fakes.
"""

import hashlib
import io
import logging
import uuid
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.engine.ingest_rules import (
    ALLOWED_EXTENSIONS,
    KINDS,
    STATEMENT_COPY_NOTE,
    ZIP_MEMBER_EXTENSIONS,
    extension,
    is_junk_zip_member,
    is_statement_copy,
    member_basename,
    mime_for,
    safe_storage_name,
    zip_member_name,
)
from app.engine.amazon_csv import AmazonCsvError, AmazonRow, parse_amazon_csv
from app.engine.statement_icici import statement_label
from app.pdf import PdfToolUnavailable, pdf_text
from app.services.gates import note_edit

log = logging.getLogger("app.ingest")

# The upload slot ("invoices") -> the kind stored in recon_files ("invoice").
DB_KIND = {"statement": "statement", "invoices": "invoice", "amazon_report": "amazon_report"}

UNSUPPORTED = "File type not supported"


class IngestError(Exception):
    """A problem with the whole request (not one file). Carries the HTTP status to answer with."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class Limits:
    max_file_bytes: int
    max_zip_total_bytes: int
    max_zip_entries: int


@dataclass
class Incoming:
    name: str
    data: bytes


@dataclass
class IngestResult:
    files: list[dict[str, Any]]
    rejected: list[dict[str, str]]


@dataclass
class _Item:
    id: str
    name: str
    data: bytes
    sha: str
    kind: str  # statement | invoice | amazon_report | zip | ignored
    parent_id: str | None = None
    status: str = "uploaded"
    note: str | None = None
    error: str | None = None
    storage_path: str | None = None
    amazon_rows: list[AmazonRow] | None = None  # the parsed report, for an Amazon CSV

    @property
    def store(self) -> bool:
        """Duplicates are recorded but their bytes are not stored a second time."""
        return self.status != "duplicate"


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):g} MB"


def _read_zip(data: bytes, limits: Limits) -> tuple[list[tuple[str, bytes]], list[dict[str, str]], str | None]:
    """Members of a ZIP as (file name, bytes). Returns (members, rejected members, whole-ZIP error)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return [], [], "Not a valid ZIP file"
    infos = archive.infolist()
    if len(infos) > limits.max_zip_entries:
        return [], [], f"ZIP has too many files (more than {limits.max_zip_entries})"
    if sum(i.file_size for i in infos) > limits.max_zip_total_bytes:
        return [], [], f"ZIP is too large when unpacked (more than {_mb(limits.max_zip_total_bytes)})"
    if any(i.flag_bits & 0x1 for i in infos):
        return [], [], "ZIP is password-protected"

    members: list[tuple[str, bytes]] = []
    rejected: list[dict[str, str]] = []
    for info in infos:
        path = zip_member_name(info)
        if is_junk_zip_member(path):
            continue
        name = member_basename(path)
        ext = extension(name)
        if ext == ".zip":
            rejected.append({"name": name, "message": "Nested ZIP files are not expanded"})
            continue
        if ext not in ZIP_MEMBER_EXTENSIONS:
            rejected.append({"name": name, "message": UNSUPPORTED})
            continue
        if info.file_size > limits.max_file_bytes:
            rejected.append({"name": name, "message": f"File is too large (max {_mb(limits.max_file_bytes)})"})
            continue
        with archive.open(info) as member:
            # Read one byte past the limit: the size in the ZIP header can be wrong.
            content = member.read(limits.max_file_bytes + 1)
        if len(content) > limits.max_file_bytes:
            rejected.append({"name": name, "message": f"File is too large (max {_mb(limits.max_file_bytes)})"})
        elif not content:
            rejected.append({"name": name, "message": "The file is empty"})
        else:
            members.append((name, content))
    return members, rejected, None


def ingest_upload(
    *,
    repo,
    storage,
    cycle: dict[str, Any],
    kind: str,
    uploads: list[Incoming],
    actor: str,
    limits: Limits,
    extract_text: Callable[[bytes], str] | None = None,
) -> IngestResult:
    if kind not in KINDS:
        raise IngestError(422, f"Unknown upload kind '{kind}'")
    if kind in ("statement", "amazon_report") and len(uploads) != 1:
        raise IngestError(422, "Upload exactly one file for this slot")
    if not uploads:
        raise IngestError(422, "No files were uploaded")
    cycle_id = cycle["id"]

    # 1. Read and validate what was uploaded; expand ZIPs.
    rejected: list[dict[str, str]] = []
    items: list[_Item] = []
    for up in uploads:
        ext = extension(up.name)
        if ext not in ALLOWED_EXTENSIONS[kind]:
            rejected.append({"name": up.name, "message": UNSUPPORTED})
            continue
        if not up.data:
            rejected.append({"name": up.name, "message": "The file is empty"})
            continue
        if len(up.data) > limits.max_file_bytes:
            rejected.append({"name": up.name, "message": f"File is too large (max {_mb(limits.max_file_bytes)})"})
            continue
        sha = hashlib.sha256(up.data).hexdigest()
        if ext == ".zip":
            members, member_rejects, error = _read_zip(up.data, limits)
            if error:
                rejected.append({"name": up.name, "message": error})
                continue
            rejected.extend(member_rejects)
            container = _Item(str(uuid.uuid4()), up.name, up.data, sha, "zip")
            items.append(container)
            for name, content in members:
                items.append(
                    _Item(str(uuid.uuid4()), name, content, hashlib.sha256(content).hexdigest(), DB_KIND[kind], container.id)
                )
        else:
            amazon_rows = None
            if kind == "amazon_report":
                # The report is read before anything is stored: a CSV that isn't an Amazon Business
                # report (or has values that can't be read) is refused with the reason.
                try:
                    amazon_rows = parse_amazon_csv(up.data)
                except AmazonCsvError as exc:
                    rejected.append({"name": up.name, "message": str(exc)})
                    continue
            items.append(_Item(str(uuid.uuid4()), up.name, up.data, sha, DB_KIND[kind], amazon_rows=amazon_rows))

    if not items:
        return IngestResult(files=[], rejected=rejected)

    # 2. Text check for statement copies among invoice PDFs whose bytes are new to this cycle.
    all_live = repo.live_files(cycle_id)
    # A file that failed to store holds no content, so it must not make its own re-upload a
    # "duplicate". Failed rows are dropped when the same content arrives again.
    failed_rows = [r for r in all_live if r["status"] == "failed"]
    live_rows = [r for r in all_live if r["status"] != "failed"]
    live_by_sha: dict[str, dict[str, Any]] = {r["sha256"]: r for r in live_rows if r.get("sha256")}
    copy_by_sha = _detect_statement_copies(items, live_by_sha, extract_text or pdf_text)

    # 3. Classify: duplicates, statement copies, containers.
    demote: list[dict[str, Any]] = []
    skip_parents: set[str] = set()
    kept: list[_Item] = []
    for item in items:
        if item.parent_id in skip_parents:
            continue  # members of a ZIP that was already uploaded
        existing = live_by_sha.get(item.sha)
        if item.kind == "statement":
            if existing is not None and existing["kind"] == "statement":
                _mark_duplicate(item, existing)
            elif existing is not None:
                # The same bytes were filed earlier as a statement copy or an invoice; the
                # statement slot wins, so that one becomes the duplicate.
                demote.append(existing)
        elif item.kind == "zip":
            if existing is not None:
                _mark_duplicate(item, existing)
                skip_parents.add(item.id)
        elif existing is not None:
            _mark_duplicate(item, existing)
            if item.kind == "invoice" and existing["kind"] in ("statement", "ignored"):
                item.kind, item.note = "ignored", STATEMENT_COPY_NOTE
        elif item.kind == "invoice" and copy_by_sha.get(item.sha):
            item.kind, item.note = "ignored", STATEMENT_COPY_NOTE
        if item.status != "duplicate":
            live_by_sha[item.sha] = {"id": item.id, "kind": item.kind, "sha256": item.sha, "original_name": item.name}
        kept.append(item)
    items = kept

    # 4. A new live statement replaces the old one (until it is confirmed; a statement that was read
    #    but not confirmed starts again from nothing); a new Amazon report replaces the old one.
    replaced: list[dict[str, Any]] = []
    reset_statement = False
    for slot in ("statement", "amazon_report"):
        if any(i.kind == slot and i.status != "duplicate" for i in items):
            old = [r for r in live_rows if r["kind"] == slot and r["id"] not in {d["id"] for d in demote}]
            if old and slot == "statement":
                if cycle["status"] not in ("draft", "statement_parsed"):
                    raise IngestError(409, "The statement is already confirmed; it can't be replaced")
                reset_statement = cycle["status"] == "statement_parsed"
            replaced.extend(old)

    # 5. Store the bytes (in parallel). A file that can't be stored is recorded as failed.
    def put(item: _Item) -> None:
        path = f"cycles/{cycle_id}/{item.id}/{safe_storage_name(item.name)}"
        try:
            storage.put(path, item.data, mime_for(item.name))
            item.storage_path = path
        except Exception as exc:  # noqa: BLE001 - recorded per file, never fails the whole upload
            log.exception("Storing %s failed", item.name)
            item.status, item.error = "failed", f"Could not store the file ({type(exc).__name__})"
            # A dropped connection can hide an upload that did arrive. The key is unique to this
            # file, so removing it is safe, and it leaves no object that nothing points at.
            try:
                storage.remove([path])
            except Exception:  # noqa: BLE001
                log.warning("Could not clean up %s after the failed upload", path)

    to_store = [i for i in items if i.store]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(put, to_store))

    # 6. Record. The demoted rows are updated first so the one-live-copy-per-hash index holds.
    rows = [_row(cycle_id, i) for i in items]
    rows.sort(key=lambda r: r["parent_file_id"] is not None)  # containers before their members
    new_shas = {i.sha for i in items}
    retried = [r["id"] for r in failed_rows if r.get("sha256") in new_shas]
    if retried:
        repo.delete_files(retried)  # these are replaced by the new rows below
    demoted_done: list[dict[str, Any]] = []
    try:
        for old in demote:
            repo.update_file(old["id"], {"status": "duplicate"})
            demoted_done.append(old)
        saved = repo.insert_files(rows)
    except Exception:
        for old in demoted_done:
            repo.update_file(old["id"], {"status": "uploaded"})
        storage.remove([i.storage_path for i in items if i.storage_path])
        raise

    # An Amazon report's rows are saved with its file (only a stored, non-duplicate report has any).
    report = next((i for i in items if i.amazon_rows is not None and i.status == "uploaded"), None)
    if report is not None:
        try:
            repo.insert_amazon_rows(
                [
                    {
                        "cycle_id": cycle_id, "file_id": report.id, "order_id": r.order_id,
                        "order_date": r.order_date.isoformat() if r.order_date else None,
                        "payment_ref": r.payment_ref,
                        "payment_date": r.payment_date.isoformat() if r.payment_date else None,
                        "payment_method": r.payment_method, "card_last4": r.card_last4,
                        "shipment_qty": r.shipment_qty, "net_total_paise": r.net_total_paise,
                    }
                    for r in report.amazon_rows or []
                ]
            )
        except Exception:
            repo.delete_files([i.id for i in items])  # undo this upload completely (rows cascade)
            storage.remove([i.storage_path for i in items if i.storage_path])
            for old in demoted_done:
                repo.update_file(old["id"], {"status": "uploaded"})
            raise

    if replaced:
        repo.delete_files([r["id"] for r in replaced])
        storage.remove([r["storage_path"] for r in replaced if r.get("storage_path")])
    if reset_statement and replaced:
        # The lines read from the old statement go with it, and so does a label made from its month.
        old_date = cycle.get("statement_date")
        auto_label = statement_label(date.fromisoformat(str(old_date)[:10])) if old_date else None
        repo.reset_statement(cycle_id, clear_label=bool(auto_label) and cycle.get("label") == auto_label)

    order = {i.id: n for n, i in enumerate(items)}
    saved.sort(key=lambda r: order.get(r["id"], 0))
    repo.add_event(
        cycle_id,
        actor,
        "files_uploaded",
        {
            "slot": kind,
            "stored": sum(1 for r in saved if r["status"] == "uploaded"),
            "duplicates": sum(1 for r in saved if r["status"] == "duplicate"),
            "rejected": len(rejected),
        },
    )
    repo.touch_cycle(cycle_id)
    if any(r["status"] == "uploaded" for r in saved):
        note_edit(repo, cycle, actor)  # new files on an exported reconciliation are an edit
    return IngestResult(files=saved, rejected=rejected)


def _mark_duplicate(item: _Item, existing: dict[str, Any]) -> None:
    item.status = "duplicate"
    if item.note is None:
        item.note = f"same file as {existing.get('original_name') or existing.get('name') or 'an earlier upload'}"


def _detect_statement_copies(
    items: list[_Item], live_by_sha: dict[str, dict[str, Any]], extract_text: Callable[[bytes], str]
) -> dict[str, bool]:
    """sha -> True when the PDF's text says it is a copy of the card statement."""
    candidates: dict[str, bytes] = {}
    for item in items:
        if item.kind == "invoice" and extension(item.name) == ".pdf" and item.sha not in live_by_sha:
            candidates.setdefault(item.sha, item.data)
    if not candidates:
        return {}

    def check(sha: str) -> bool:
        return is_statement_copy(extract_text(candidates[sha]))

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            return dict(zip(candidates, pool.map(check, candidates), strict=True))
    except PdfToolUnavailable:
        raise IngestError(
            503,
            "PDF text reading (poppler) is not available on this server. Run the API in Docker.",
        ) from None


def _row(cycle_id: str, item: _Item) -> dict[str, Any]:
    return {
        "id": item.id,
        "cycle_id": cycle_id,
        "kind": item.kind,
        "original_name": item.name,
        "storage_path": item.storage_path,
        "sha256": item.sha,
        "mime_type": mime_for(item.name),
        "size_bytes": len(item.data),
        "parent_file_id": item.parent_id,
        "status": "processed" if item.kind == "zip" and item.status == "uploaded" else item.status,
        "note": item.note,
        "error": item.error,
    }
