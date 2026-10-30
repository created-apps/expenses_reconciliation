"""GET /transactions, POST /transactions/{id}/resolve and GET /unused-invoices (fakes for the database).

The reconciliation is built straight in the fake: six statement lines, their invoices and links, as they
would be after a run of the matching. Names echo the June cases (a Review that is ₹149 short, a Missing
invoice, an unused Amazon invoice of ₹175, a USD charge).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.db import get_repo
from app.main import app
from app.services import run_matching as matching
from fakes import FakeRepo

USER = CurrentUser(email="harsh@create-ed.in", user_id="u1")
ME = "harsh@create-ed.in"


def uid() -> str:
    return str(uuid.uuid4())


class World:
    """A matched reconciliation: lines L1..L6, invoices and links."""

    def __init__(self, repo: FakeRepo):
        self.repo = repo
        self.cid = repo.create_cycle("June 2026", "t")["id"]
        repo.update_cycle(self.cid, {"status": "matched", "statement_date": "2026-06-28", "statement_confirmed_at": "2026-07-01"})
        self.file: dict[str, str] = {}
        self.inv: dict[str, dict] = {}

        def line(n, ser, day, desc, paise, **kw):
            return {"cycle_id": self.cid, "ser_no": ser, "txn_date": day, "description": desc, "amount_paise": paise,
                    "is_credit": False, "card_last4": "4002", "sort_order": n, **kw}

        repo.replace_transactions(self.cid, [
            line(1, "L1", "2026-06-18", "MACFOS LIMITED MUMBAI", 42200, status="Matched", vendor_key="macfos", notes="Exact INR amount"),
            line(2, "L2", "2026-06-20", "AMAZON SELLER SERVICES MUMBAI", 5253900, status="Review", vendor_key="amazon",
                 notes="Closest invoice is ₹149 less"),
            line(3, "L3", "2026-06-19", "MACFOS LIMITED MUMBAI", 71501, status="Missing invoice", vendor_key="macfos", notes="No invoice found"),
            line(4, "L4", "2026-06-21", "FATHOM VIDEO", 354437, status="Matched", vendor_key="fathom", notes="USD amount equals the foreign amount",
                 foreign_amount_minor=3600, foreign_currency="USD"),
            line(5, "L5", "2026-06-10", "CLICK TO PAY PAYMENT RECEIVED", 6047200, status="Payment", is_credit=True),
            line(6, "L6", "2026-06-22", "VISTAPRINT INDIA", 90000, status="Missing invoice", vendor_key="vistaprint", notes="No invoice found"),
        ])
        self.line = {t["ser_no"]: t for t in repo.transactions}

        self.add("A", "190626_Macfos_422.pdf", "macfos", 42200, date="2026-06-18")
        self.add("B", "200626_Amazon_52390.pdf", "amazon", 5239000, date="2026-06-20")
        self.add("F", "Fathom_36.pdf", "fathom", 3600, currency="USD", date="2026-06-21")
        self.add("U1", "240626_Amazon_175.pdf", "amazon", 17500, date="2026-06-24")
        self.add("U2", "vendorless.png", None, 9900, status="needs_check", date="2026-06-12")
        self.add("U3", "290626_Amazon_432.pdf", "amazon", 43200, date="2026-06-29")
        self.add("U4", "credit_note.pdf", "amazon", 5000, credit_note=True, date="2026-06-15")
        self.add("DUP", "copy_of_A.pdf", "macfos", 42200, date="2026-06-18", duplicate_of="A")
        self.add("PEND", "scan.png", None, None, status="pending")
        self.add("V", "Vistaprint_900.pdf", "vistaprint", 90000, date="2026-06-22")

        self.link("L1", "A", system=True)
        self.link("L2", "B", suggestion=True)
        self.link("L4", "F", system=True)

    def add(self, key, name, vendor, total, *, status="ok", currency="INR", date=None, credit_note=False, duplicate_of=None):
        fid = uid()
        self.repo.insert_files([{"id": fid, "cycle_id": self.cid, "kind": "invoice", "original_name": name, "status": "uploaded"}])
        (row,) = self.repo.insert_invoices([{
            "cycle_id": self.cid, "file_id": fid, "block_index": 0, "vendor_key": vendor, "invoice_no": f"NO-{key}",
            "order_id": None, "invoice_date": date, "order_date": None, "currency": currency, "total_minor": total,
            "is_credit_note": credit_note, "source": "pdf_text", "extraction_status": status,
        }])
        if duplicate_of:
            self.repo.update_invoice(row["id"], {"duplicate_of": self.inv[duplicate_of]["id"]})
        self.file[key] = fid
        self.inv[key] = row

    def link(self, line, key, *, system=False, suggestion=False, by=None):
        self.repo.matches.append({
            "id": uid(), "cycle_id": self.cid, "transaction_id": self.line[line]["id"], "invoice_id": self.inv[key]["id"],
            "rule": "exact_inr" if system else "manual", "is_suggestion": suggestion, "created_by": None if system or suggestion else (by or ME),
        })

    def links_of(self, line):
        return [(m["invoice_id"], m["is_suggestion"], m["created_by"], m["rule"]) for m in self.repo.matches if m["transaction_id"] == self.line[line]["id"]]

    def row(self, line):
        return next(t for t in self.repo.transactions if t["ser_no"] == line)


@pytest.fixture
def api():
    repo = FakeRepo()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    client = TestClient(app)
    client.world = World(repo)
    yield client
    app.dependency_overrides.clear()


def lines(api, **params):
    r = api.get(f"/api/cycles/{api.world.cid}/transactions", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def resolve(api, line, expected=200, **body):
    r = api.post(f"/api/transactions/{api.world.line[line]['id']}/resolve", json=body)
    assert r.status_code == expected, r.text
    return r.json()


def unused(api, **params):
    r = api.get(f"/api/cycles/{api.world.cid}/unused-invoices", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def ser(view):
    return [t["ser_no"] for t in view["items"]]


# ---- the lines --------------------------------------------------------------------------------------------------------------------
def test_the_endpoints_need_a_token():
    client = TestClient(app)
    nil = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
    assert client.get(f"/api/cycles/{nil}/transactions").status_code == 401
    assert client.post(f"/api/transactions/{nil}/resolve", json={}).status_code == 401
    assert client.get(f"/api/cycles/{nil}/unused-invoices").status_code == 401


def test_all_lines_come_back_in_statement_order_with_their_invoices(api):
    view = lines(api)
    assert (view["total"], view["shown"]) == (6, 6)
    assert ser(view) == ["L5", "L1", "L3", "L2", "L4", "L6"]  # by date
    by = {t["ser_no"]: t for t in view["items"]}
    assert [i["file_name"] for i in by["L1"]["invoices"]] == ["190626_Macfos_422.pdf"] and by["L1"]["suggestions"] == []
    assert [i["file_name"] for i in by["L2"]["suggestions"]] == ["200626_Amazon_52390.pdf"] and by["L2"]["invoices"] == []
    assert by["L1"]["vendor_name"] == "Macfos" or by["L1"]["vendor_name"]  # name comes from the vendor table
    assert view["cards"] == ["4002"]
    assert {v["key"] for v in view["vendors"]} == {"macfos", "amazon", "fathom", "vistaprint"}


def test_the_comparison_comes_from_the_api(api):
    by = {t["ser_no"]: t for t in lines(api)["items"]}
    assert by["L1"]["comparison"] == {"attached_sum_paise": 42200, "difference_paise": 0, "state": "matches",
                                      "needs_note": False, "note_missing": False}
    assert by["L2"]["comparison"]["state"] == "none" and by["L2"]["comparison"]["difference_paise"] == 5253900
    # The USD invoice equals the line's foreign amount, so it counts as the whole charge.
    assert by["L4"]["comparison"]["attached_sum_paise"] == 354437 and by["L4"]["comparison"]["state"] == "matches"
    assert by["L4"]["foreign"] == {"amount_minor": 3600, "currency": "USD"}
    assert by["L5"]["is_credit"] is True


def test_the_filters_status_vendor_card_and_search(api):
    assert ser(lines(api, status="Review")) == ["L2"]
    assert ser(lines(api, status="Missing invoice")) == ["L3", "L6"]
    assert ser(lines(api, vendor="macfos")) == ["L1", "L3"]
    assert ser(lines(api, card="4002"))[0] == "L5" and lines(api, card="9999")["shown"] == 0
    assert lines(api, status="Review")["total"] == 6  # the total is every line, whatever the filter
    assert ser(lines(api, q="52539")) == ["L2"]  # by amount (10.6)
    assert ser(lines(api, q="vistaprint")) == ["L6"]  # by description (10.6)
    assert ser(lines(api, q="Macfos_422")) == ["L1"]  # by attached file name
    assert ser(lines(api, q="amazon 52539")) == ["L2"]
    assert ser(lines(api, status="Missing invoice", q="macfos")) == ["L3"]


def test_unknown_cycle_is_404(api):
    nil = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
    assert api.get(f"/api/cycles/{nil}/transactions").status_code == 404
    assert api.get(f"/api/cycles/{nil}/unused-invoices").status_code == 404
    assert api.post(f"/api/transactions/{nil}/resolve", json={}).status_code == 404


# ---- accept a suggestion (10.2) --------------------------------------------------------------------------------------------
def test_a_preview_shows_the_new_sum_and_difference_and_writes_nothing(api):
    w = api.world
    before = (list(w.repo.matches), dict(w.row("L2")), list(w.repo.events))
    line = resolve(api, "L2", attach_invoice_ids=[w.inv["B"]["id"]], status="Matched", preview=True)
    assert line["status"] == "Matched"
    assert [i["file_name"] for i in line["invoices"]] == ["200626_Amazon_52390.pdf"] and line["suggestions"] == []
    assert line["comparison"] == {"attached_sum_paise": 5239000, "difference_paise": 14900, "state": "differs",
                                  "needs_note": True, "note_missing": True}  # ₹149.00 short, and the note is still the system's
    assert (w.repo.matches, w.row("L2"), w.repo.events) == before  # nothing written


def test_accepting_a_suggestion_needs_a_note_for_the_difference(api):
    w = api.world
    resolve(api, "L2", expected=422, attach_invoice_ids=[w.inv["B"]["id"]], status="Matched")  # system note untouched
    resolve(api, "L2", expected=422, attach_invoice_ids=[w.inv["B"]["id"]], status="Matched", note="   ")
    assert w.row("L2")["status"] == "Review" and w.row("L2").get("updated_by") is None  # still nothing saved

    line = resolve(api, "L2", attach_invoice_ids=[w.inv["B"]["id"]], status="Matched", note="Vendor confirmed ₹149 discount")
    assert line["status"] == "Matched" and line["note"] == "Vendor confirmed ₹149 discount" and line["updated_by"] == ME
    assert line["comparison"]["difference_paise"] == 14900 and line["comparison"]["note_missing"] is False
    # The suggestion became the person's own link (rule manual), not a second link.
    assert w.links_of("L2") == [(w.inv["B"]["id"], False, ME, "manual")]
    assert (w.row("L2")["status"], w.row("L2")["updated_by"]) == ("Matched", ME)
    actions = [e["action"] for e in w.repo.events]
    assert actions == ["suggestion_accepted", "status_changed", "note_saved"]
    assert w.repo.events[0]["payload"]["invoices"] == ["200626_Amazon_52390.pdf"] and w.repo.events[0]["actor"] == ME
    assert w.repo.events[1]["payload"]["from"] == "Review" and w.repo.events[1]["payload"]["to"] == "Matched"


def test_an_exact_attach_needs_no_note(api):
    w = api.world
    resolve(api, "L3", attach_invoice_ids=[w.inv["A"]["id"]], expected=409)  # A is used by L1
    w.repo.matches = [m for m in w.repo.matches if m["invoice_id"] != w.inv["A"]["id"]]  # free it
    w.repo.update_invoice(w.inv["A"]["id"], {"total_minor": 71501})
    line = resolve(api, "L3", attach_invoice_ids=[w.inv["A"]["id"]], status="Matched")
    assert line["comparison"]["state"] == "matches" and line["status"] == "Matched"


def test_a_note_that_was_saved_by_a_person_before_still_counts(api):
    w = api.world
    resolve(api, "L2", attach_invoice_ids=[w.inv["B"]["id"]], status="Matched", note="Discount agreed")
    # Later the person only changes the status: the note is theirs already, so no new note is demanded.
    line = resolve(api, "L2", status="Review")
    assert line["status"] == "Review" and line["comparison"]["note_missing"] is False


# ---- mark No invoice (10.3) -------------------------------------------------------------------------------------------------------
def test_mark_no_invoice_with_a_note(api):
    w = api.world
    line = resolve(api, "L3", status="No invoice", note="asked vendor")
    assert (line["status"], line["note"], line["updated_by"]) == ("No invoice", "asked vendor", ME)
    assert (w.row("L3")["status"], w.row("L3")["notes"], w.row("L3")["updated_by"]) == ("No invoice", "asked vendor", ME)
    assert [e["action"] for e in w.repo.events] == ["status_changed", "note_saved"]
    assert lines(api, status="No invoice")["items"][0]["note"] == "asked vendor"  # shows in the table


def test_a_note_alone_keeps_the_status(api):
    line = resolve(api, "L3", note="chasing the vendor")
    assert line["status"] == "Missing invoice" and line["note"] == "chasing the vendor"
    assert [e["action"] for e in api.world.repo.events] == ["note_saved"]


def test_nothing_changed_writes_nothing_and_does_not_mark_the_line(api):
    w = api.world
    line = resolve(api, "L3", status="Missing invoice", note="No invoice found")
    assert line["updated_by"] is None and w.row("L3").get("updated_by") is None and w.repo.events == []


# ---- find an invoice and attach it (10.4) ---------------------------------------------------------------------------------------
def test_unused_invoices_are_searchable_by_vendor_and_amount(api):
    view = unused(api, q="amazon 175")
    assert [i["file_name"] for i in view["items"]] == ["240626_Amazon_175.pdf"]
    assert view["total"] == len(unused(api)["items"])  # total ignores the search


def test_attaching_an_unused_invoice_updates_the_sum(api):
    w = api.world
    line = resolve(api, "L6", attach_invoice_ids=[w.inv["U1"]["id"]], note="Closest invoice, checking")
    assert line["comparison"]["attached_sum_paise"] == 17500 and line["comparison"]["difference_paise"] == 72500
    assert w.links_of("L6") == [(w.inv["U1"]["id"], False, ME, "manual")]
    assert "240626_Amazon_175.pdf" not in [i["file_name"] for i in unused(api)["items"]]  # no longer unused
    assert [e["action"] for e in w.repo.events] == ["invoices_attached", "note_saved"]
    # A second invoice adds up.
    line = resolve(api, "L6", attach_invoice_ids=[w.inv["V"]["id"]])
    assert line["comparison"]["attached_sum_paise"] == 107500 and len(line["invoices"]) == 2


def test_an_attach_that_is_refused(api):
    w = api.world
    resolve(api, "L6", expected=409, attach_invoice_ids=[w.inv["A"]["id"]])  # attached to L1
    resolve(api, "L6", expected=409, attach_invoice_ids=[w.inv["B"]["id"]])  # reserved by L2's suggestion
    resolve(api, "L6", expected=422, attach_invoice_ids=[w.inv["DUP"]["id"]])  # a duplicate
    resolve(api, "L6", expected=422, attach_invoice_ids=[w.inv["PEND"]["id"]])  # not read yet
    resolve(api, "L6", expected=404, attach_invoice_ids=[uid()])  # not in this reconciliation
    resolve(api, "L6", expected=422, attach_invoice_ids=[w.inv["U1"]["id"]], detach_invoice_ids=[w.inv["U1"]["id"]])
    assert w.repo.events == [] and w.links_of("L6") == []


def test_an_invoice_with_no_vendor_can_be_found_and_attached(api):
    w = api.world
    items = unused(api)["items"]
    vendorless = next(i for i in items if i["file_name"] == "vendorless.png")
    assert vendorless["vendor_key"] is None and vendorless["needs_check"] is True
    assert vendorless["reason"] == "No vendor set. Open the invoice and choose one"
    line = resolve(api, "L6", attach_invoice_ids=[vendorless["id"]], note="Image of the Vistaprint receipt")
    assert line["invoices"][0]["file_name"] == "vendorless.png"


def test_a_credit_note_cannot_be_attached_to_a_charge_but_can_to_a_credit_line(api):
    w = api.world
    credit_note = w.inv["U4"]["id"]
    for preview in (True, False):  # refused in the preview as well as on save
        r = api.post(f"/api/transactions/{w.line['L6']['id']}/resolve", json={"attach_invoice_ids": [credit_note], "preview": preview})
        assert r.status_code == 422 and "credit note can't be attached to a charge" in r.json()["detail"]
    assert w.links_of("L6") == [] and w.repo.events == []
    line = resolve(api, "L5", attach_invoice_ids=[credit_note], note="credit note for the refund")  # L5 is a credit line; the difference needs a note
    assert [i["file_name"] for i in line["invoices"]] == ["credit_note.pdf"] and line["invoices"][0]["is_credit_note"] is True
    assert "credit_note.pdf" not in [i["file_name"] for i in unused(api)["items"]]


# ---- detach, status rules -------------------------------------------------------------------------------------------------------
def test_detach_returns_the_invoice_to_the_unused_list(api):
    w = api.world
    resolve(api, "L1", expected=422, detach_invoice_ids=[w.inv["A"]["id"]])  # still Matched, with nothing attached
    line = resolve(api, "L1", detach_invoice_ids=[w.inv["A"]["id"]], status="Missing invoice", note="wrong invoice")
    assert line["invoices"] == [] and line["status"] == "Missing invoice"
    assert w.links_of("L1") == []
    assert "190626_Macfos_422.pdf" in [i["file_name"] for i in unused(api)["items"]]
    assert [e["action"] for e in w.repo.events] == ["invoices_detached", "status_changed", "note_saved"]


def test_a_status_the_rules_own_cannot_be_set_by_hand(api):
    resolve(api, "L3", expected=422, status="Payment")
    resolve(api, "L3", expected=422, status="Reversed")
    resolve(api, "L3", expected=422, status="Nonsense")
    resolve(api, "L3", expected=422, status="Matched")  # nothing attached


def test_leaving_review_drops_the_suggestions_so_they_stop_reserving_invoices(api):
    w = api.world
    assert "200626_Amazon_52390.pdf" not in [i["file_name"] for i in unused(api)["items"]]  # reserved
    resolve(api, "L2", status="No invoice", note="not ours")
    assert w.links_of("L2") == []
    assert "200626_Amazon_52390.pdf" in [i["file_name"] for i in unused(api)["items"]]  # free again


def test_a_note_on_a_review_line_keeps_its_suggestion(api):
    w = api.world
    resolve(api, "L2", note="checking with the vendor")
    assert [x[1] for x in w.links_of("L2")] == [True]


# ---- the unused list -------------------------------------------------------------------------------------------------------------------
def test_the_unused_list_and_its_reasons(api):
    view = unused(api)
    by = {i["file_name"]: i for i in view["items"]}
    # Used (A, F), reserved by a suggestion (B), a duplicate and a pending image are not in the list.
    assert sorted(by) == ["240626_Amazon_175.pdf", "290626_Amazon_432.pdf", "Vistaprint_900.pdf", "credit_note.pdf", "vendorless.png"]
    assert view["total"] == 5
    # The world's last Amazon charge is 20/06, and this invoice is dated 24/06.
    assert by["240626_Amazon_175.pdf"]["reason"] == "Dated after the last Amazon charge on this statement (20/06)"
    assert by["290626_Amazon_432.pdf"]["reason"] == "Dated after the statement date"
    assert by["credit_note.pdf"]["reason"] == "Credit note: never matched to a charge"
    assert by["Vistaprint_900.pdf"]["reason"] == "A charge of ₹900.00 exists on 22/06/2026 but was not matched to this invoice"  # the line is Missing
    assert by["240626_Amazon_175.pdf"]["total_minor"] == 17500 and by["240626_Amazon_175.pdf"]["currency"] == "INR"
    assert [i["file_name"] for i in unused(api, vendor="amazon")["items"]] == ["240626_Amazon_175.pdf", "290626_Amazon_432.pdf", "credit_note.pdf"]


# ---- gates -----------------------------------------------------------------------------------------------------------------------------
def test_a_line_that_has_not_been_matched_yet_cannot_be_resolved(api):
    w = api.world
    w.row("L3")["status"] = None
    resolve(api, "L3", expected=409, status="No invoice")


def test_resolving_while_matching_runs_is_refused(api):
    w = api.world
    w.repo.update_cycle(w.cid, {"job_status": "running", "job_progress": 30, "job_message": "Matching 6 lines…"})
    resolve(api, "L3", expected=409, status="No invoice")


def test_changing_a_line_after_an_export_moves_the_cycle_back_to_matched(api):
    w = api.world
    w.repo.update_cycle(w.cid, {"status": "exported"})
    resolve(api, "L3", status="No invoice", note="asked vendor", preview=True)
    assert w.repo.get_cycle(w.cid)["status"] == "exported"  # a preview is not an edit
    resolve(api, "L3", status="No invoice", note="asked vendor")
    assert w.repo.get_cycle(w.cid)["status"] == "matched"
    assert "edited_after_export" in [e["action"] for e in w.repo.events]


def test_a_line_of_another_cycle_is_not_found_through_this_one(api):
    other = api.world.repo.create_cycle("other", "t")["id"]
    api.world.repo.update_cycle(other, {"status": "matched"})
    api.world.repo.transactions.append({"id": uid(), "cycle_id": other, "ser_no": "X", "txn_date": "2026-06-01", "description": "X",
                                        "amount_paise": 100, "is_credit": False, "status": "Missing invoice"})
    foreign = api.world.repo.transactions[-1]["id"]
    # The line's own cycle is used, so the call works against that cycle; the invoices of this one are not found there.
    r = api.post(f"/api/transactions/{foreign}/resolve", json={"attach_invoice_ids": [api.world.inv["U1"]["id"]]})
    assert r.status_code == 404


# ---- what a person did survives a new run (10.5) -----------------------------------------------------------------------------------------
def test_a_re_run_keeps_what_was_resolved_by_hand(api):
    w = api.world
    resolve(api, "L2", attach_invoice_ids=[w.inv["B"]["id"]], status="Matched", note="Discount agreed")  # 10.2
    resolve(api, "L3", status="No invoice", note="asked vendor")  # 10.3
    resolve(api, "L6", attach_invoice_ids=[w.inv["U1"]["id"]], note="attached by hand")  # 10.4

    cycle = w.repo.get_cycle(w.cid)
    matching.start_matching(w.repo, cycle)
    assert matching.run_matching(w.repo, cycle, ME) is not None
    assert (w.row("L2")["status"], w.row("L2")["notes"]) == ("Matched", "Discount agreed")
    assert (w.row("L3")["status"], w.row("L3")["notes"]) == ("No invoice", "asked vendor")
    assert w.row("L6")["notes"] == "attached by hand"
    assert w.links_of("L2") == [(w.inv["B"]["id"], False, ME, "manual")]
    assert w.links_of("L6") == [(w.inv["U1"]["id"], False, ME, "manual")]
    # A line nobody touched is decided again by the rules.
    assert w.row("L1").get("updated_by") is None
    view = lines(api, q="52539")
    assert view["items"][0]["status"] == "Matched"
