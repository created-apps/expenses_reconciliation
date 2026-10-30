"""GET /amazon-to-fetch, and the Amazon-specific reasons on the "Invoices not used" tab (fakes for the database).

A small Amazon month is built in the fake: one report with four card payments (and one never on this
statement), a gift order, an unpaid order, charges that are Missing, Matched, credits and a reversal. The real
matcher is run on it, and the list is checked against the notes the matcher wrote into the lines.
"""

import re
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


def uid() -> str:
    return str(uuid.uuid4())


def order(n: int) -> str:
    return f"407-{n:07d}-{n:07d}"


class Month:
    """Charges: A1 20/06 10,000 (3 orders, one has no invoice), A2 22/06 1,000 (matched), A3 25/06 2,500 (2 orders, no
    invoices), A4 26/06 777 (no group). A payment group R9 (30/06, 555) belongs to no charge on this statement."""

    def __init__(self, repo: FakeRepo, *, report: bool = True):
        self.repo = repo
        self.cid = repo.create_cycle("June 2026", "t")["id"]
        repo.update_cycle(self.cid, {"status": "invoices_extracted", "statement_date": "2026-06-28"})
        self.invoice_file = uid()
        repo.insert_files([{"id": self.invoice_file, "cycle_id": self.cid, "kind": "invoice", "original_name": "inv.pdf", "status": "uploaded"}])
        self.block = 0
        self.report_file = None
        if report:
            self.report_file = uid()
            repo.insert_files([{"id": self.report_file, "cycle_id": self.cid, "kind": "amazon_report", "original_name": "report.csv", "status": "uploaded"}])
        rows = [
            self.line(1, "2026-06-10", "ASSPL Bangalore IN", 40082),
            self.line(2, "2026-06-20", "ASSPL Bangalore IN", 1000000),
            self.line(3, "2026-06-22", "ASSPL Bangalore IN", 100000),
            self.line(4, "2026-06-25", "ASSPL Bangalore IN", 250000),
            self.line(5, "2026-06-26", "ASSPL Bangalore IN", 77700),
            self.line(6, "2026-06-27", "ASSPL Bangalore IN", 15000, credit=True),
            self.line(7, "2026-06-12", "ASSPL Bangalore IN", 40082, credit=True),
        ]
        repo.replace_transactions(self.cid, rows)
        self.txn = {t["ser_no"]: t for t in repo.transactions}
        if report:
            self.report_row("R1", "2026-06-20", [(order(1), 300000), (order(2), 400000), (order(3), 300000)])
            self.report_row("R2", "2026-06-22", [(order(4), 100000)])
            self.report_row("R3", "2026-06-25", [(order(5), 150000), (order(6), 100000)])
            self.report_row("R9", "2026-06-30", [(order(9), 55500)])
            self.report_row("GIFT1", "2026-06-15", [(order(20), 15800)], method="Gift Certificate/Card", card=None)
            self.report_row("", "2026-06-24", [(order(30), 9900)], method=None, card=None)  # ordered, not paid
        # Invoices: orders 1, 2 (only part of it) and 4 are invoiced; 3, 5, 6, 9 are not.
        self.invoice(order(1), 300000, "2026-06-20")
        self.invoice(order(2), 350000, "2026-06-20")
        self.invoice(order(4), 100000, "2026-06-22")
        self.invoice(order(20), 15800, "2026-06-15")  # the gift order has an invoice too

    def line(self, n, day, desc, paise, credit=False):
        return {"cycle_id": self.cid, "ser_no": f"S{n}", "txn_date": day, "description": desc, "amount_paise": paise,
                "is_credit": credit, "card_last4": "4002", "sort_order": n}

    def report_row(self, ref, day, orders, method="Visa", card="4002"):
        self.repo.insert_amazon_rows([
            {"cycle_id": self.cid, "file_id": self.report_file, "order_id": o, "order_date": day, "payment_ref": ref or None,
             "payment_date": day if method else None, "payment_method": method, "card_last4": card,
             "shipment_qty": 1, "net_total_paise": amount}
            for o, amount in orders
        ])

    def invoice(self, order_id, total, day, *, status="ok", vendor="amazon", credit_note=False, dup=False):
        self.block += 1
        (row,) = self.repo.insert_invoices([{
            "cycle_id": self.cid, "file_id": self.invoice_file, "block_index": self.block, "vendor_key": vendor,
            "invoice_no": f"N{self.block}", "order_id": order_id, "invoice_date": day, "order_date": day, "currency": "INR",
            "total_minor": total, "amounts_minor": [total], "is_credit_note": credit_note, "source": "pdf_text",
            "extraction_status": status,
        }])
        if dup:
            self.repo.update_invoice(row["id"], {"duplicate_of": row["id"]})
        return row

    def run_matching(self):
        cycle = self.repo.get_cycle(self.cid)
        matching.start_matching(self.repo, cycle)
        assert matching.run_matching(self.repo, cycle, "t") is not None

    def status(self, n):
        return next(t for t in self.repo.transactions if t["ser_no"] == f"S{n}")


@pytest.fixture
def api():
    repo = FakeRepo()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    client = TestClient(app)
    client.month = Month(repo)
    yield client
    app.dependency_overrides.clear()


def fetch(api, month=None):
    month = month or api.month
    r = api.get(f"/api/cycles/{month.cid}/amazon-to-fetch")
    assert r.status_code == 200, r.text
    return r.json()


def ids(view):
    return [i["order_id"] for i in view["items"]]


# ---- gates ---------------------------------------------------------------------------------------------------------------------
def test_the_endpoint_needs_a_token():
    nil = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
    assert TestClient(app).get(f"/api/cycles/{nil}/amazon-to-fetch").status_code == 401


def test_an_unknown_cycle_is_404(api):
    nil = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
    assert api.get(f"/api/cycles/{nil}/amazon-to-fetch").status_code == 404


def test_without_a_report_there_is_nothing_to_list_and_it_says_so():
    repo = FakeRepo()
    month = Month(repo, report=False)
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        view = TestClient(app).get(f"/api/cycles/{month.cid}/amazon-to-fetch").json()
    finally:
        app.dependency_overrides.clear()
    assert view["has_report"] is False and view["items"] == [] and view["coverage"] is None


def test_before_matching_has_run_the_list_is_empty_but_the_coverage_is_there(api):
    view = fetch(api)
    assert view["has_report"] is True and view["matched"] is False and view["items"] == []
    assert view["coverage"]["card_orders"] == 7


# ---- the list ---------------------------------------------------------------------------------------------------------------------------
def test_it_lists_the_orders_of_each_charge_that_have_no_invoice(api):
    api.month.run_matching()
    view = fetch(api)
    assert view["matched"] is True
    assert ids(view) == [order(3), order(5), order(6)]  # ordered by charge date, then amount, then order id
    first, second, third = view["items"]
    assert (first["ser_no"], first["charge_date"], first["charge_amount_paise"], first["amount_paise"]) == ("S2", "2026-06-20", 1000000, 300000)
    assert (first["payment_date"], first["group_reference"], first["description"]) == ("2026-06-20", "R1", "ASSPL Bangalore IN")
    assert (second["ser_no"], second["amount_paise"], third["amount_paise"]) == ("S4", 150000, 100000)
    assert view["total_orders"] == 3 and view["total_paise"] == 550000


def test_an_order_whose_invoice_is_uploaded_is_not_listed_even_if_the_invoice_covers_only_part_of_it(api):
    api.month.run_matching()
    view = fetch(api)
    assert order(1) not in ids(view) and order(2) not in ids(view) and order(4) not in ids(view)
    assert view["coverage"]["partly_invoiced"] == 1  # order 2: invoice 3,500 against 4,000 in the report


def test_a_payment_that_matches_no_charge_on_this_statement_is_not_listed(api):
    api.month.run_matching()
    assert order(9) not in ids(fetch(api))  # R9 (30/06, 555) is on no line
    assert api.month.status(5)["status"] == "Missing invoice"  # the 777 charge has no group at all


def test_credits_reversals_and_orders_paid_from_the_gift_balance_or_not_paid_are_never_listed(api):
    api.month.run_matching()
    assert api.month.status(1)["status"] == "Reversed" and api.month.status(6)["status"] == "Credit – manual"
    assert order(20) not in ids(fetch(api)) and order(30) not in ids(fetch(api))


def test_a_duplicate_or_a_credit_note_does_not_count_as_the_orders_invoice(api):
    api.month.invoice(order(3), 300000, "2026-06-20", dup=True)
    api.month.invoice(order(5), 150000, "2026-06-25", credit_note=True)
    api.month.run_matching()
    assert order(3) in ids(fetch(api)) and order(5) in ids(fetch(api))


def test_uploading_the_missing_invoice_and_matching_again_takes_the_order_off_the_list(api):
    api.month.run_matching()
    assert order(3) in ids(fetch(api))
    api.month.invoice(order(3), 300000, "2026-06-20")
    api.month.repo.update_cycle(api.month.cid, {"job_status": None, "job_kind": None})
    api.month.run_matching()
    assert order(3) not in ids(fetch(api))
    # Order 2 is only partly invoiced (3,500 of 4,000), so the charge still does not add up: the order is not
    # listed as missing, but the line says what the invoices add up to.
    line = api.month.status(2)
    assert line["status"] == "Missing invoice" and "the invoices add up to ₹9,500.00" in line["notes"]


def test_a_line_a_person_changed_is_not_listed(api):
    api.month.run_matching()
    api.month.repo.update_transaction(api.month.status(4)["id"], {"status": "No invoice", "notes": "asked", "updated_by": "harsh@create-ed.in"})
    assert ids(fetch(api)) == [order(3)]


def test_the_list_agrees_with_the_order_ids_the_matcher_wrote_into_the_notes(api):
    api.month.run_matching()
    from_notes: list[str] = []
    for t in api.month.repo.transactions:
        found = re.search(r"orders without an invoice: ([0-9, \-]+)\.", t.get("notes") or "")
        if found:
            from_notes += [o.strip() for o in found.group(1).split(",")]
    assert sorted(from_notes) == sorted(ids(fetch(api))) == [order(3), order(5), order(6)]


# ---- Amazon invoices with no readable Order ID --------------------------------------------------------------------------------
def test_amazon_invoices_without_a_usable_order_id_are_counted_so_nobody_assumes_the_order_is_missing(api):
    api.month.invoice(None, 12300, "2026-06-24", status="needs_check")
    api.month.invoice("1234", 4500, "2026-06-24", status="needs_check")
    api.month.run_matching()
    assert fetch(api)["invoices_without_order_id"] == 2


# ---- reasons on the "Invoices not used" tab ----------------------------------------------------------------------------------------
def unused_reasons(api):
    r = api.get(f"/api/cycles/{api.month.cid}/unused-invoices")
    assert r.status_code == 200
    return {i["invoice_no"]: i["reason"] for i in r.json()["items"]}


def test_with_a_report_an_unused_amazon_invoice_says_how_its_order_was_paid(api):
    m = api.month
    m.report_row("RG", "2026-06-26", [(order(41), 10100)], method="Gift Certificate/Card", card=None)
    m.report_row("RP", "2026-07-02", [(order(42), 10200)])
    m.report_row("RX", "2026-06-26", [(order(43), 10300)], card="9999")
    gift, later, other, none = (
        m.invoice(order(41), 10100, "2026-06-26"), m.invoice(order(42), 10200, "2026-06-26"),
        m.invoice(order(43), 10300, "2026-06-26"), m.invoice(None, 10400, "2026-06-27", status="needs_check"),
    )
    m.run_matching()
    reasons = unused_reasons(api)
    assert reasons[gift["invoice_no"]] == "Paid by gift balance"
    assert reasons[later["invoice_no"]] == "Paid on 02/07 (after this statement)"
    assert reasons[other["invoice_no"]] == "Paid on another card"
    # No Order ID to look up: the ordinary reason, here the last Amazon charge on the statement is 26/06.
    assert reasons[none["invoice_no"]] == "Dated after the last Amazon charge on this statement (27/06)".replace("27/06", "26/06")


def test_without_a_report_the_amazon_invoices_after_the_last_charge_say_so():
    repo = FakeRepo()
    month = Month(repo, report=False)
    late = month.invoice(order(50), 5000, "2026-06-28")
    early = month.invoice(order(51), 5100, "2026-06-24")
    month.run_matching()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        items = TestClient(app).get(f"/api/cycles/{month.cid}/unused-invoices").json()["items"]
    finally:
        app.dependency_overrides.clear()
    reasons = {i["invoice_no"]: i["reason"] for i in items}
    assert reasons[late["invoice_no"]] == "Dated after the last Amazon charge on this statement (26/06)"
    assert reasons[early["invoice_no"]] == "No charge of this amount found"
