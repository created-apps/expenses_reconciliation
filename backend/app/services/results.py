"""The Results step: the lines with their invoices, the unused invoices, and what a person does to a line.

Orchestration only. The sum, the difference, the search and the reasons are in `engine/results.py`; which
invoice belongs to which line was decided by `engine/matcher.py` and is only changed here by a person.
Every change is written to `recon_events`.
"""

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from app.engine.results import (
    AttachedInvoice,
    ReportOrder,
    VendorLine,
    compare,
    invoice_matches,
    line_matches,
    unused_reason,
)
from app.services.amazon_report import live_report_file, report_rows
from app.services.gates import ServiceError, note_edit, require_confirmed_statement
from app.services.run_matching import _parallel
from app.services.statement import job_is_active

# What a person may set by hand. Reversed, Payment, Bank charge and Credit – manual come from the rules.
MANUAL_STATUSES = ("Matched", "Review", "Missing invoice", "No invoice")
READY = ("ok", "needs_check")  # invoices that have been read (pending and failed ones have nothing to match)


def _day(value: Any) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


class Data:
    """Everything the Results step reads for one reconciliation (fetched in parallel)."""

    def __init__(self, lines, invoices, matches, files, aliases, amazon_records=()):
        self.lines = lines
        self.files = files
        self.aliases = {a["vendor_key"]: a for a in aliases}
        self.amazon_records = list(amazon_records)
        self.invoices = {i["id"]: i for i in invoices}
        self.matches = matches
        self.file_name = {f["id"]: f["original_name"] for f in files}
        self.vendor_name = {a["vendor_key"]: a["display_name"] for a in aliases}
        self.links: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for m in matches:
            self.links[m["transaction_id"]].append(m)

    @classmethod
    def load(cls, repo, cycle_id: str, with_report: bool = False) -> "Data":
        calls = [
            lambda: repo.list_transactions(cycle_id),
            lambda: repo.list_invoices(cycle_id),
            lambda: repo.list_matches(cycle_id),
            lambda: repo.list_files(cycle_id),
            lambda: repo.list_vendor_aliases(),
        ]
        if with_report:  # the Amazon report's rows, for the reasons on the "Invoices not used" tab
            calls.append(lambda: repo.list_amazon_rows(cycle_id))
        return cls(*_parallel(*calls))

    def ref(self, invoice: dict[str, Any], linked_by: str | None = None) -> dict[str, Any]:
        return {
            "id": invoice["id"], "file_id": invoice["file_id"], "file_name": self.file_name.get(invoice["file_id"], "?"),
            "vendor_key": invoice.get("vendor_key"), "vendor_name": self.vendor_name.get(invoice.get("vendor_key") or ""),
            "invoice_no": invoice.get("invoice_no"), "order_id": invoice.get("order_id"),
            "invoice_date": invoice.get("invoice_date"), "order_date": invoice.get("order_date"),
            "currency": invoice.get("currency") or "INR", "total_minor": invoice.get("total_minor"),
            "is_credit_note": bool(invoice.get("is_credit_note")),
            "needs_check": invoice.get("extraction_status") == "needs_check", "linked_by": linked_by,
        }

    def refs(self, links: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = [self.ref(self.invoices[m["invoice_id"]], m.get("created_by")) for m in links if m["invoice_id"] in self.invoices]
        return sorted(out, key=lambda r: r["file_name"].lower())


def note_is_theirs(new_note: str, old_note: str, updated_by: str | None) -> bool:
    """A note counts as a person's when they wrote something new, or they had already saved this line
    (the note box starts with the system's own reason; leaving that untouched does not count)."""
    return new_note.strip() != "" and (new_note.strip() != old_note.strip() or bool(updated_by))


def _line(
    data: Data, t: dict[str, Any], attached: list[dict[str, Any]], suggestions: list[dict[str, Any]], theirs: bool,
) -> dict[str, Any]:
    foreign = {"amount_minor": t["foreign_amount_minor"], "currency": t["foreign_currency"]} if t.get("foreign_amount_minor") else None
    comparison = compare(
        int(t["amount_paise"]), t.get("foreign_amount_minor"), t.get("foreign_currency"),
        [AttachedInvoice(a["currency"], a["total_minor"]) for a in attached],
    )
    return {
        "id": t["id"], "ser_no": t["ser_no"], "txn_date": t["txn_date"], "description": t["description"],
        "card_last4": t.get("card_last4"), "vendor_key": t.get("vendor_key"),
        "vendor_name": data.vendor_name.get(t.get("vendor_key") or ""), "foreign": foreign,
        "amount_paise": int(t["amount_paise"]), "is_credit": bool(t["is_credit"]), "status": t.get("status"),
        "note": t.get("notes") or "", "updated_by": t.get("updated_by"), "updated_at": t.get("updated_at"),
        "invoices": attached, "suggestions": suggestions,
        "comparison": {
            "attached_sum_paise": comparison.attached_sum_paise, "difference_paise": comparison.difference_paise,
            "state": comparison.state, "needs_note": comparison.needs_note,
            "note_missing": comparison.needs_note and not theirs,
        },
    }


def _saved_line(data: Data, t: dict[str, Any]) -> dict[str, Any]:
    links = data.links.get(t["id"], [])
    note = t.get("notes") or ""
    return _line(
        data, t, data.refs([m for m in links if not m.get("is_suggestion")]), data.refs([m for m in links if m.get("is_suggestion")]),
        note_is_theirs(note, note, t.get("updated_by")),
    )


# -- the lines -------------------------------------------------------------------------------------------------
def transactions_view(
    repo, cycle: dict[str, Any], *, status: str | None = None, vendor: str | None = None,
    card: str | None = None, q: str | None = None,
) -> dict[str, Any]:
    data = Data.load(repo, cycle["id"])
    items = []
    for t in data.lines:
        if status and t.get("status") != status:
            continue
        if vendor and t.get("vendor_key") != vendor:
            continue
        if card and t.get("card_last4") != card:
            continue
        line = _saved_line(data, t)
        if q and not line_matches(
            q, ser_no=line["ser_no"], description=line["description"], amount_paise=line["amount_paise"],
            note=line["note"], vendor_name=line["vendor_name"], file_names=[i["file_name"] for i in line["invoices"]],
        ):
            continue
        items.append(line)
    vendors = sorted({t["vendor_key"] for t in data.lines if t.get("vendor_key")}, key=lambda k: data.vendor_name.get(k, k).lower())
    return {
        "total": len(data.lines), "shown": len(items),
        "vendors": [{"key": k, "name": data.vendor_name.get(k, k)} for k in vendors],
        "cards": sorted({t["card_last4"] for t in data.lines if t.get("card_last4")}),
        "items": items,
    }


# -- invoices not used -----------------------------------------------------------------------------------------
def report_orders(data: Data) -> dict[str, ReportOrder]:
    """What the Amazon report says about each order that was paid (Order ID -> how and when). Empty without a report."""
    file = live_report_file(data.files)
    if file is None:
        return {}
    by_order: dict[str, list] = defaultdict(list)
    for row in report_rows(data.amazon_records, file["id"]):
        if row.order_id and row.payment_method:  # a row with no payment method says nothing about how it was paid
            by_order[row.order_id].append(row)
    out = {}
    for order, rows in by_order.items():
        dates = [r.payment_date for r in rows if r.payment_date]
        if all(r.is_gift for r in rows):
            out[order] = ReportOrder(paid_on=min(dates) if dates else None, is_gift=True, card_last4=None)
        else:
            cards = [r.card_last4 for r in rows if not r.is_gift and r.card_last4]
            out[order] = ReportOrder(paid_on=min(dates) if dates else None, is_gift=False, card_last4=cards[0] if cards else None)
    return out


def unused_view(repo, cycle: dict[str, Any], *, q: str | None = None, vendor: str | None = None) -> dict[str, Any]:
    """Read invoices that no line uses and no Review suggestion reserves (rule 8), each with a reason."""
    data = Data.load(repo, cycle["id"], with_report=True)
    used = {m["invoice_id"] for m in data.matches}
    attached = {m["transaction_id"] for m in data.matches if not m.get("is_suggestion")}
    statement_date = _day(cycle.get("statement_date"))
    vendor_lines: dict[str, list[VendorLine]] = defaultdict(list)
    for t in data.lines:
        if t.get("vendor_key") and not t["is_credit"]:
            vendor_lines[t["vendor_key"]].append(VendorLine(
                day=_day(t["txn_date"]), amount_paise=int(t["amount_paise"]),
                foreign_minor=t.get("foreign_amount_minor"), foreign_currency=t.get("foreign_currency"),
                matched=t["id"] in attached,
            ))
    amazon_days = [line.day for line in vendor_lines.get("amazon", [])]
    last_amazon_charge = max(amazon_days) if amazon_days else None
    statement_cards = sorted({t["card_last4"] for t in data.lines if t.get("card_last4")})
    orders = report_orders(data)
    rows = []
    unused = [
        i for i in data.invoices.values()
        if i["id"] not in used and not i.get("duplicate_of") and i.get("extraction_status") in READY
    ]
    for i in sorted(unused, key=lambda i: (data.file_name.get(i["file_id"], "").lower(), i.get("block_index") or 0)):
        ref = data.ref(i)
        if vendor and ref["vendor_key"] != vendor:
            continue
        if q and not invoice_matches(
            q, file_name=ref["file_name"], vendor_key=ref["vendor_key"], vendor_name=ref["vendor_name"],
            invoice_no=ref["invoice_no"], order_id=ref["order_id"], total_minor=ref["total_minor"],
        ):
            continue
        key = i.get("vendor_key")
        alias = data.aliases.get(key or "", {})
        is_amazon = key == "amazon"
        rows.append({
            **ref,
            "reason": unused_reason(
                vendor_key=key, is_credit_note=ref["is_credit_note"], total_minor=ref["total_minor"],
                currency=ref["currency"], when=_day(i.get("invoice_date")) or _day(i.get("order_date")),
                statement_date=statement_date, vendor_lines=vendor_lines.get(key or "", []),
                window_days=max(alias.get("date_before_days") or 0, alias.get("date_after_days") or 0) or 7,
                last_amazon_charge=last_amazon_charge if is_amazon else None,
                report_order=orders.get(i.get("order_id") or "") if is_amazon else None,
                statement_cards=statement_cards,
            ),
        })
    return {"total": len(unused), "items": rows}

# -- what a person does to a line ------------------------------------------------------------------------------
def _fail(status: int, message: str) -> ServiceError:
    return ServiceError(status, message)


def resolve(repo, cycle: dict[str, Any], transaction_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
    """Attach and detach invoices, set a status, write a note: one action on one line.

    With `preview` nothing is written; the line comes back as it would be, with its new sum and difference.
    A change by a person marks the line (`updated_by`), so a later run of the matching leaves it as it is.
    """
    require_confirmed_statement(cycle)
    if job_is_active(cycle, datetime.now(timezone.utc)):
        raise _fail(409, "Matching is running. Try again when it has finished")
    t = repo.get_transaction(transaction_id)
    if t is None or t["cycle_id"] != cycle["id"]:
        raise _fail(404, "Statement line not found")
    if not t.get("status"):
        raise _fail(409, "Run matching first")

    data = Data.load(repo, cycle["id"])
    mine = data.links.get(t["id"], [])
    attach = list(dict.fromkeys(body.get("attach_invoice_ids") or []))
    detach = list(dict.fromkeys(body.get("detach_invoice_ids") or []))
    if set(attach) & set(detach):
        raise _fail(422, "An invoice can't be attached and detached in the same step")

    on_this_line = {m["invoice_id"] for m in mine if not m.get("is_suggestion")}
    suggested = {m["invoice_id"] for m in mine if m.get("is_suggestion")}
    used_elsewhere = {m["invoice_id"] for m in data.matches if m["transaction_id"] != t["id"]}
    for invoice_id in attach:
        invoice = data.invoices.get(invoice_id)
        if invoice is None:
            raise _fail(404, "Invoice not found in this reconciliation")
        if invoice.get("duplicate_of"):
            raise _fail(422, "That invoice is a duplicate of another one")
        if invoice.get("extraction_status") not in READY:
            raise _fail(422, "That invoice has not been read yet")
        if invoice_id in used_elsewhere:
            raise _fail(409, "That invoice is already used by another line")
        if invoice.get("is_credit_note") and not t["is_credit"]:
            raise _fail(422, "A credit note can't be attached to a charge. Attach it to a credit line instead")

    new_status = body.get("status") or t["status"]
    if new_status != t["status"] and new_status not in MANUAL_STATUSES:
        raise _fail(422, f"A status can only be set to {', '.join(MANUAL_STATUSES)}")
    old_note = t.get("notes") or ""
    new_note = old_note if body.get("note") is None else str(body["note"]).strip()

    final = (on_this_line - set(detach)) | set(attach)
    if new_status == "Matched" and not final:
        raise _fail(422, "A line can only be Matched with an invoice attached")
    kept_suggestions = (suggested - set(attach) - set(detach)) if new_status == "Review" else set()

    changed = bool(
        set(attach) - on_this_line or (set(detach) & (on_this_line | suggested))
        or new_status != t["status"] or new_note != old_note
        or kept_suggestions != suggested
    )

    # What the line looks like afterwards.
    by_invoice = {m["invoice_id"]: m for m in mine}
    attached_refs = sorted(
        (data.ref(data.invoices[i], by_invoice[i].get("created_by") if i in on_this_line else actor) for i in final),
        key=lambda r: r["file_name"].lower(),
    )
    suggestion_refs = sorted((data.ref(data.invoices[i]) for i in kept_suggestions if i in data.invoices), key=lambda r: r["file_name"].lower())
    after = {**t, "status": new_status, "notes": new_note}
    if changed:
        after.update({"updated_by": actor, "updated_at": datetime.now(timezone.utc).isoformat()})
    theirs = note_is_theirs(new_note, old_note, t.get("updated_by"))
    line = _line(data, after, attached_refs, suggestion_refs, theirs)

    if not changed or body.get("preview"):
        return line
    if line["comparison"]["note_missing"]:
        raise _fail(422, "Add a note to explain the difference before saving")

    # Writes: first the links that go (a suggestion that is accepted is replaced by a person's link), then the
    # new links, the line and the audit rows together.
    drop = [m["id"] for m in mine if m["invoice_id"] in detach or (m.get("is_suggestion") and (m["invoice_id"] in attach or new_status != "Review"))]
    new_links = [
        {"cycle_id": cycle["id"], "transaction_id": t["id"], "invoice_id": i, "rule": "manual", "is_suggestion": False, "created_by": actor}
        for i in attach if i not in on_this_line
    ]
    label = {"transaction": t["ser_no"], "description": t["description"]}
    names = lambda ids: [data.ref(data.invoices[i])["file_name"] for i in ids if i in data.invoices]  # noqa: E731
    events: list[tuple[str, dict[str, Any]]] = []
    added = [i for i in attach if i not in on_this_line]
    if added:
        events.append(("suggestion_accepted" if set(added) <= suggested else "invoices_attached", {**label, "invoices": names(added)}))
    removed = [i for i in detach if i in on_this_line or i in suggested]
    if removed:
        events.append(("invoices_detached", {**label, "invoices": names(removed)}))
    if new_status != t["status"]:
        events.append(("status_changed", {**label, "from": t["status"], "to": new_status}))
    if new_note != (t.get("notes") or ""):
        events.append(("note_saved", {**label, "note": new_note}))

    if drop:
        repo.delete_matches(drop)
    _parallel(
        lambda: repo.insert_matches(new_links) if new_links else None,
        lambda: repo.update_transaction(t["id"], {"status": new_status, "notes": new_note, "updated_by": actor}),
        lambda: repo.add_events(cycle["id"], actor, events),
    )
    note_edit(repo, cycle, actor)  # on an exported reconciliation the first edit moves it back to matched
    return line
