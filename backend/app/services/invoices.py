"""Reading the invoice files into invoice rows, listing them, and correcting them.

Orchestration only: what an invoice looks like is in `engine/invoices/`. Reading runs as a background
job; progress is kept on the cycle row (`job_status`, `job_progress`, `job_message`), shared with the
statement job (they never overlap: the statement is confirmed before invoices are read).
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any

from app.engine.invoices import VendorPattern, duplicate_indexes, extract_invoices, has_text_layer
from app.engine.invoices.validate import field_problems
from app.engine.invoices.vision import VisionClient, read_image_invoice
from app.pdf import PdfToolUnavailable, pdf_text, render_first_page_png
from app.services.gates import ServiceError, note_edit, require_confirmed_statement
from app.services.jobs import INVOICES, job_fields
from app.services.run_matching import is_matching_job, matching_job
from app.services.statement import job_is_active

log = logging.getLogger("app.invoices")

InvoiceError = ServiceError
WORKERS = 4
CURRENCIES = ("INR", "USD")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")


# -- which files, and the job -----------------------------------------------------------------------------
def readable_files(repo, cycle_id: str) -> list[dict[str, Any]]:
    """Invoice files that were stored and are not duplicates, in upload order."""
    rows = [
        f for f in repo.list_files(cycle_id)
        if f["kind"] == "invoice" and f["status"] == "uploaded" and f.get("storage_path")
    ]
    return sorted(rows, key=_file_order)


def _file_order(f: dict[str, Any]) -> tuple[str, str]:
    return (str(f["created_at"]), f["original_name"])


def _is_image(f: dict[str, Any]) -> bool:
    return str(f.get("mime_type") or "").startswith("image/") or f["original_name"].lower().endswith(IMAGE_EXTENSIONS)


def _unread_files(repo, cycle_id: str) -> list[dict[str, Any]]:
    """Readable files that have no invoice row yet (just uploaded)."""
    seen = {i["file_id"] for i in repo.list_invoices(cycle_id)}
    return [f for f in readable_files(repo, cycle_id) if f["id"] not in seen]


def start_extract(repo, cycle: dict[str, Any], now: datetime | None = None, new_only: bool = False) -> None:
    """Checks that reading may start and marks the job as running.

    `new_only` reads just the files that were never read, and leaves every existing invoice (and the
    matches that use it) alone: used to add one invoice to a reconciliation that has already been matched.
    """
    now = now or datetime.now(timezone.utc)
    require_confirmed_statement(cycle)
    if job_is_active(cycle, now):
        raise InvoiceError(409, "The invoices are already being read")
    if not readable_files(repo, cycle["id"]):
        raise InvoiceError(409, "Upload the invoices first")
    if new_only and not _unread_files(repo, cycle["id"]):
        raise InvoiceError(409, "There are no new invoice files to read")
    repo.update_cycle(cycle["id"], job_fields(INVOICES, "running", 0, "Starting…"))


def run_extract(
    *,
    repo,
    storage,
    cycle_id: str,
    actor: str,
    extract_text: Callable[[bytes], str] | None = None,
    vision: VisionClient | None = None,
    new_only: bool = False,
) -> None:
    """The background job. Never raises: a failure is recorded on the cycle as `job_status = failed`.
    With `new_only`, only files that have no invoice rows yet are read; nothing else is touched.

    PDFs with a text layer are read from their text. Images, and PDFs without text, are read by the
    vision model when one is configured (`vision`); otherwise they stay `pending`. A file keeps its
    rows when a person corrected them, or when the AI already read it fine (so a second click does
    not pay for the same images again); everything else is read again.
    """
    extract = extract_text or (lambda data: pdf_text(data, last_page=None, timeout=60))

    def progress(pct: int, message: str) -> None:
        repo.update_cycle(cycle_id, job_fields(INVOICES, "running", pct, message))

    def fail(message: str) -> None:
        repo.update_cycle(cycle_id, job_fields(INVOICES, "failed", None, message))

    try:
        vendors = [
            VendorPattern(a["vendor_key"], a.get("invoice_pattern"), a.get("display_name"))
            for a in repo.list_vendor_aliases()
        ]
        if new_only:
            files = _unread_files(repo, cycle_id)
        else:
            files = [f for f in readable_files(repo, cycle_id) if f["id"] not in _kept_files(repo, cycle_id)]
        total = len(files)
        progress(2, f"Reading invoices… 0 of {total}")

        def read(f: dict[str, Any]) -> tuple[str, Any]:
            try:
                data = storage.get(f["storage_path"])
                if _is_image(f):
                    if vision is None:
                        return "pending", "AI is not set up (ANTHROPIC_API_KEY and ANTHROPIC_MODEL)"
                    return "items", [read_image_invoice(data, _media_type(f), vision, vendors)]
                text = extract(data)
                if has_text_layer(text):
                    return "items", extract_invoices(text, vendors)
                # A scan: no text to read, so the first page is read as an image.
                if vision is None:
                    return "pending", "no text layer, and AI is not set up"
                page = render_first_page_png(data)
                if not page:
                    return "pending", "no text layer, and the page could not be turned into an image"
                return "items", [read_image_invoice(page, "image/png", vision, vendors)]
            except PdfToolUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the rest
                log.exception("Reading %s failed", f["original_name"])
                return "failed", f"{type(exc).__name__}"

        rows: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for n, (f, (kind, value)) in enumerate(zip(files, pool.map(read, files)), start=1):
                rows.extend(_rows_for(cycle_id, f, kind, value))
                if n % 3 == 0 or n == total:
                    progress(2 + int(88 * n / max(total, 1)), f"Reading invoices… {n} of {total}")

        progress(92, "Saving invoices…")
        repo.delete_invoices_for_files([f["id"] for f in files])
        repo.insert_invoices(rows)
        _mark_duplicates(repo, cycle_id)

        everything = repo.list_invoices(cycle_id)
        invoices = [r for r in everything if r["extraction_status"] in ("ok", "needs_check")]
        pending = sum(1 for r in everything if r["extraction_status"] == "pending")
        by_ai = sum(1 for r in everything if r.get("source") == "vision")
        message = f"Invoices read: {len(invoices)} invoices from {len({r['file_id'] for r in invoices})} files"
        if by_ai:
            message += f" · {by_ai} read by AI"
        if pending:
            message += f" · {pending} waiting for AI"
        fields: dict[str, Any] = job_fields(INVOICES, "done", 100, message)
        current = repo.get_cycle(cycle_id) or {}
        if current.get("status") == "statement_confirmed":
            fields["status"] = "invoices_extracted"
        repo.update_cycle(cycle_id, fields)
        tokens = _ai_tokens(rows)
        repo.add_event(
            cycle_id, actor, "invoices_extracted",
            {"files": total, "invoices": len(invoices), "pending": pending,
             "needs_check": sum(1 for r in everything if r["extraction_status"] == "needs_check"),
             "ai_images": sum(1 for r in rows if r.get("source") == "vision"),
             "ai_input_tokens": tokens[0], "ai_output_tokens": tokens[1]},
        )
    except PdfToolUnavailable:
        log.error("pdftotext is not installed; run the API in Docker")
        fail("Reading PDFs needs poppler, which isn't installed on the server. Run the API in Docker.")
    except Exception:  # noqa: BLE001 - recorded on the cycle; the screen shows it
        log.exception("Reading the invoices of cycle %s failed", cycle_id)
        fail("Couldn't read the invoices. Please try again.")


def _kept_files(repo, cycle_id: str) -> set[str]:
    """Files whose rows a re-read must not touch: corrected by a person, or already read by the AI.

    "Read by the AI" means it gave a usable answer, even if the image still needs a person (it prints no
    vendor name): sending it again would cost money and return the same thing. An image the AI could not
    read at all (wrong key, unreachable, unusable answer: `read_failed`) is tried again.
    """
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for invoice in repo.list_invoices(cycle_id):
        by_file[invoice["file_id"]].append(invoice)
    kept = set()
    for file_id, rows in by_file.items():
        if any(r.get("source") == "manual" for r in rows):
            kept.add(file_id)
        elif all(
            r.get("source") == "vision"
            and r["extraction_status"] in ("ok", "needs_check")
            and not (r.get("extra") or {}).get("read_failed")
            for r in rows
        ):
            kept.add(file_id)
    return kept


def _ai_tokens(rows: list[dict[str, Any]]) -> tuple[int, int]:
    """Input and output tokens the AI used for these rows (kept in each row's `extra.ai`)."""
    used = [(r.get("extra") or {}).get("ai") or {} for r in rows]
    return sum(int(u.get("input_tokens") or 0) for u in used), sum(int(u.get("output_tokens") or 0) for u in used)


def _media_type(f: dict[str, Any]) -> str:
    mime = str(f.get("mime_type") or "")
    if mime.startswith("image/"):
        return mime
    return "image/png" if f["original_name"].lower().endswith(".png") else "image/jpeg"


def _rows_for(cycle_id: str, f: dict[str, Any], kind: str, value: Any) -> list[dict[str, Any]]:
    base = {
        "cycle_id": cycle_id, "file_id": f["id"], "block_index": 0, "vendor_key": None, "invoice_no": None,
        "order_id": None, "invoice_date": None, "order_date": None, "currency": "INR", "total_minor": None,
        "amounts_minor": [], "extra": {}, "is_credit_note": False, "source": None, "extraction_status": "pending",
    }
    if kind == "pending":
        return [{**base, "extra": {"reason": value}}]
    if kind == "failed":
        return [{**base, "extraction_status": "failed", "extra": {"error": value}}]
    return [
        {
            **base,
            "block_index": item.block_index,
            "vendor_key": item.vendor_key,
            "invoice_no": item.invoice_no,
            "order_id": item.order_id,
            "invoice_date": item.invoice_date.isoformat() if item.invoice_date else None,
            "order_date": item.order_date.isoformat() if item.order_date else None,
            "currency": item.currency,
            "total_minor": item.total_minor,
            "amounts_minor": item.amounts_minor,
            "extra": {**item.extra, "problems": item.problems},
            "is_credit_note": item.is_credit_note,
            "source": item.source,
            "extraction_status": item.extraction_status,
        }
        for item in value
    ]


def _mark_duplicates(repo, cycle_id: str) -> None:
    """Invoice-level duplicates: the same vendor + number + total as an earlier invoice (file order)."""
    order = {f["id"]: n for n, f in enumerate(sorted(repo.list_files(cycle_id), key=_file_order))}
    invoices = sorted(repo.list_invoices(cycle_id), key=lambda i: (order.get(i["file_id"], 0), i["block_index"]))
    dupes = duplicate_indexes(invoices)
    for i, invoice in enumerate(invoices):
        wanted = invoices[dupes[i]]["id"] if i in dupes else None
        if invoice.get("duplicate_of") != wanted:
            repo.update_invoice(invoice["id"], {"duplicate_of": wanted})


# -- the list ---------------------------------------------------------------------------------------------
def is_set_aside(f: dict[str, Any]) -> bool:
    """A file a person marked "Not an invoice" (not a statement copy the app set aside by itself)."""
    return f.get("kind") == "ignored" and str(f.get("note") or "").startswith(SET_ASIDE_PREFIX)


def _state(f: dict[str, Any], invoice: dict[str, Any] | None) -> str:
    if f["kind"] == "ignored":
        return "ignored"
    if f["status"] == "duplicate":
        return "duplicate"
    if f["status"] == "failed":
        return "failed"
    if invoice is None:
        return "unread"
    return "duplicate" if invoice.get("duplicate_of") else invoice["extraction_status"]


def _problems(invoice: dict[str, Any]) -> list[str]:
    """What to tell a person about an invoice: why it needs a check, or why it is still waiting."""
    extra = invoice.get("extra") or {}
    if invoice["extraction_status"] == "pending":
        return [extra["reason"]] if extra.get("reason") else []
    return list(extra.get("problems") or [])


def invoices_view(repo, cycle: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    files = sorted(
        (f for f in repo.list_files(cycle["id"]) if f["kind"] in ("invoice", "ignored")), key=_file_order
    )
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for invoice in repo.list_invoices(cycle["id"]):
        by_file[invoice["file_id"]].append(invoice)
    names = {a["vendor_key"]: a["display_name"] for a in repo.list_vendor_aliases()}
    file_name = {f["id"]: f["original_name"] for f in files}
    invoice_file = {i["id"]: i["file_id"] for rows in by_file.values() for i in rows}

    entries: list[dict[str, Any]] = []
    for f in files:
        rows = sorted(by_file.get(f["id"], []), key=lambda i: i["block_index"]) or [None]
        for invoice in rows:
            state = _state(f, invoice)
            first = invoice and invoice.get("duplicate_of")
            entries.append(
                {
                    "key": f"{f['id']}:{invoice['id'] if invoice else '-'}",
                    "file_id": f["id"],
                    "file_name": f["original_name"],
                    "file_kind": f["kind"],
                    "file_status": f["status"],
                    "file_note": f.get("note") or f.get("error"),
                    "mime_type": f.get("mime_type"),
                    "has_copy": bool(f.get("storage_path")),
                    "can_restore": is_set_aside(f),
                    "state": state,
                    "invoice_id": invoice["id"] if invoice else None,
                    "block_index": invoice["block_index"] if invoice else None,
                    "vendor_key": invoice.get("vendor_key") if invoice else None,
                    "vendor_name": names.get(invoice.get("vendor_key")) if invoice else None,
                    "invoice_no": invoice.get("invoice_no") if invoice else None,
                    "order_id": invoice.get("order_id") if invoice else None,
                    "invoice_date": invoice.get("invoice_date") if invoice else None,
                    "order_date": invoice.get("order_date") if invoice else None,
                    "currency": invoice["currency"] if invoice else None,
                    "total_minor": invoice.get("total_minor") if invoice else None,
                    "is_credit_note": bool(invoice and invoice.get("is_credit_note")),
                    "source": invoice.get("source") if invoice else None,
                    "problems": _problems(invoice) if invoice else [],
                    "duplicate_of_name": file_name.get(invoice_file.get(first)) if first else None,
                }
            )

    invoice_rows = [i for rows in by_file.values() for i in rows]
    job = None
    if cycle.get("job_status") and cycle["status"] not in ("draft", "statement_parsed"):
        if is_matching_job(cycle):  # a matching run shares the job columns: only show it while it runs
            running = matching_job(cycle, now)
            job = running if running and running["status"] == "running" else None
        else:
            job = {"status": cycle["job_status"], "progress": cycle.get("job_progress"), "message": cycle.get("job_message")}
            if job["status"] == "running" and not job_is_active(cycle, now):
                job = {"status": "failed", "progress": None, "message": "Reading stopped unexpectedly. Please try again."}
    members = files
    return {
        "status": cycle["status"],
        "job": job,
        "counts": {
            "files": len(members),
            "unread": sum(1 for e in entries if e["state"] == "unread"),
            "invoices": sum(1 for i in invoice_rows if i["extraction_status"] in ("ok", "needs_check")),
            "pending": sum(1 for i in invoice_rows if i["extraction_status"] == "pending"),
            "needs_check": sum(1 for i in invoice_rows if i["extraction_status"] == "needs_check"),
            "failed": sum(1 for e in entries if e["state"] == "failed"),
            "duplicate_files": sum(1 for f in members if f["kind"] == "invoice" and f["status"] == "duplicate"),
            "duplicate_invoices": sum(1 for i in invoice_rows if i.get("duplicate_of")),
            "ignored": sum(1 for f in members if f["kind"] == "ignored"),
        },
        "vendors": [{"key": k, "name": n} for k, n in names.items()],
        "entries": entries,
    }


# -- corrections ------------------------------------------------------------------------------------------
SET_ASIDE_PREFIX = "marked as not an invoice by"  # the note of a file a person set aside (the only kind that can be restored)
EDITABLE = ("vendor_key", "invoice_no", "order_id", "invoice_date", "order_date", "currency", "total_minor")


def correct_invoice(repo, cycle: dict[str, Any], invoice: dict[str, Any], changes: dict[str, Any], actor: str) -> None:
    """A person's correction. The invoice becomes `manual`: re-reading the files keeps it.
    On an exported reconciliation it is an edit: the cycle goes back to `matched`."""
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise InvoiceError(422, f"Can't change: {', '.join(sorted(unknown))}")
    if changes.get("currency") is not None and changes["currency"] not in CURRENCIES:
        raise InvoiceError(422, "Currency must be INR or USD")
    if changes.get("total_minor") is not None and changes["total_minor"] < 0:
        raise InvoiceError(422, "The total can't be negative")
    if changes.get("vendor_key"):
        known = {a["vendor_key"] for a in repo.list_vendor_aliases()}
        if changes["vendor_key"] not in known:
            raise InvoiceError(422, "Unknown vendor")

    new = {**invoice, **changes}
    problems = field_problems(
        vendor_key=new.get("vendor_key"), order_id=new.get("order_id"), total_minor=new.get("total_minor"),
        invoice_date=new.get("invoice_date"), order_date=new.get("order_date"),
    )

    fields = {
        **{k: (v.isoformat() if isinstance(v, date) else v) for k, v in changes.items()},
        "source": "manual",
        "extraction_status": "needs_check" if problems else "ok",
        "extra": {**(invoice.get("extra") or {}), "problems": problems},
    }
    if "total_minor" in changes or "currency" in changes:
        fields["amounts_minor"] = [new["total_minor"]] if new.get("total_minor") else []
    repo.update_invoice(invoice["id"], fields)
    repo.add_event(
        cycle["id"], actor, "invoice_edited",
        {"invoice_id": invoice["id"], "file_id": invoice["file_id"],
         "changes": {k: [invoice.get(k), fields[k]] for k in changes}},
    )
    # Two invoices can now be the same one (or stop being); keep the duplicate marks right.
    _mark_duplicates(repo, cycle["id"])
    note_edit(repo, cycle, actor)


def mark_not_an_invoice(repo, cycle: dict[str, Any], invoice: dict[str, Any], actor: str) -> None:
    """The file is not an invoice (a wrong upload): it is set aside as ignored and its rows are removed."""
    file = repo.get_file(invoice["file_id"])
    repo.delete_invoices_for_files([invoice["file_id"]])
    repo.update_file(invoice["file_id"], {"kind": "ignored", "note": f"{SET_ASIDE_PREFIX} {actor}"})
    repo.add_event(
        cycle["id"], actor, "invoice_ignored",
        {"file_id": invoice["file_id"], "file": file["original_name"] if file else None},
    )
    _mark_duplicates(repo, cycle["id"])
    note_edit(repo, cycle, actor)

def restore_file(repo, cycle: dict[str, Any], file: dict[str, Any], actor: str) -> None:
    """Undo "Not an invoice": the file is an invoice file again and is read by the next "Read invoices".
    Only a file a person set aside can be restored; a copy of the statement stays set aside."""
    if not is_set_aside(file):
        raise InvoiceError(409, "Only a file you set aside with “Not an invoice” can be restored")
    repo.update_file(file["id"], {"kind": "invoice", "note": None})
    repo.add_event(cycle["id"], actor, "invoice_restored", {"file_id": file["id"], "file": file["original_name"]})
    note_edit(repo, cycle, actor)
