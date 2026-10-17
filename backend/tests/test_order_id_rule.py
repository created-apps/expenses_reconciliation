"""An Amazon invoice without a readable Order ID is `needs_check` with a clear reason: the Amazon report is
matched to invoices by Order ID, so a missing or misread one must never silently turn an uploaded invoice into a
"missing" order. Also the same rule when a person corrects an invoice."""

from datetime import date

from app.engine.invoices.types import ExtractedInvoice
from app.engine.invoices.validate import AMAZON_ORDER_ID, NO_ORDER_ID, order_id_problem, validate
from app.services.invoices import correct_invoice
from fakes import FakeRepo
from test_vision import VENDORS, Script, read, reply

GOOD_ID = "407-1234567-1234567"


def amazon(order_id, **kw) -> ExtractedInvoice:
    base = dict(vendor_key="amazon", order_id=order_id, total_minor=17500, invoice_date=date(2026, 6, 24), currency="INR")
    return ExtractedInvoice(**{**base, **kw})


# ---- when an invoice is read -------------------------------------------------------------------------------------------------
def test_an_amazon_invoice_with_no_order_id_needs_a_check_and_says_why():
    item = validate(amazon(None))
    assert item.extraction_status == "needs_check" and item.problems == [NO_ORDER_ID]
    assert validate(amazon("  ")).problems == [NO_ORDER_ID]


def test_an_amazon_invoice_with_a_misread_order_id_needs_a_check():
    item = validate(amazon("407-12345-1234567"))
    assert item.extraction_status == "needs_check"
    assert item.problems == ["Amazon order ID “407-12345-1234567” is not in the usual format 407-1234567-1234567. Check it"]


def test_an_amazon_invoice_with_a_good_order_id_is_ok_and_other_vendors_need_none():
    assert validate(amazon(GOOD_ID)).extraction_status == "ok"
    assert validate(amazon(f" {GOOD_ID} ")).extraction_status == "ok"
    assert validate(amazon(None, vendor_key="macfos")).extraction_status == "ok"  # only Amazon is matched by Order ID
    assert order_id_problem("macfos", None) is None and order_id_problem(None, None) is None
    assert AMAZON_ORDER_ID.match(GOOD_ID)


def test_the_order_id_problem_comes_with_the_other_problems_not_instead_of_them():
    item = validate(amazon(None, total_minor=None))
    assert item.problems == ["No total found", NO_ORDER_ID]


def test_an_amazon_image_read_by_the_ai_without_an_order_id_needs_a_check():
    answer = reply(vendor="Amazon Seller Services Private Limited", invoice_date="2026-06-14", currency="INR", total="99.00")
    item = read(Script(answer))
    assert item.vendor_key == "amazon" and item.order_id is None
    assert item.extraction_status == "needs_check" and NO_ORDER_ID in item.problems
    good = read(Script(reply(vendor="Amazon Seller Services Private Limited", order_id=GOOD_ID, invoice_date="2026-06-14", currency="INR", total="99.00")))
    assert good.extraction_status == "ok" and good.order_id == GOOD_ID


# ---- when a person corrects it ------------------------------------------------------------------------------------------------
def invoice_in(repo: FakeRepo, order_id, status="needs_check"):
    cycle = repo.create_cycle("June 2026", "t")
    repo.update_cycle(cycle["id"], {"status": "invoices_extracted"})
    fid = "f1"
    repo.insert_files([{"id": fid, "cycle_id": cycle["id"], "kind": "invoice", "original_name": "scan.png", "status": "uploaded"}])
    (inv,) = repo.insert_invoices([{
        "cycle_id": cycle["id"], "file_id": fid, "block_index": 0, "vendor_key": "amazon", "invoice_no": "N1",
        "order_id": order_id, "invoice_date": "2026-06-14", "order_date": None, "currency": "INR", "total_minor": 9900,
        "amounts_minor": [9900], "is_credit_note": False, "source": "vision", "extraction_status": status,
        "extra": {"problems": [NO_ORDER_ID]},
    }])
    return repo.get_cycle(cycle["id"]), inv


def test_typing_the_order_id_clears_the_problem():
    repo = FakeRepo()
    cycle, inv = invoice_in(repo, None)
    correct_invoice(repo, cycle, inv, {"order_id": GOOD_ID}, "harsh@create-ed.in")
    row = repo.get_invoice(inv["id"])
    assert row["extraction_status"] == "ok" and row["extra"]["problems"] == [] and row["source"] == "manual"


def test_a_correction_that_leaves_the_order_id_missing_or_wrong_keeps_it_flagged():
    repo = FakeRepo()
    cycle, inv = invoice_in(repo, None)
    correct_invoice(repo, cycle, inv, {"total_minor": 9950}, "me")
    row = repo.get_invoice(inv["id"])
    assert row["extraction_status"] == "needs_check" and row["extra"]["problems"] == [NO_ORDER_ID]
    correct_invoice(repo, cycle, repo.get_invoice(inv["id"]), {"order_id": "123"}, "me")
    assert repo.get_invoice(inv["id"])["extraction_status"] == "needs_check"


def test_choosing_amazon_as_the_vendor_of_an_invoice_with_no_order_id_flags_it():
    repo = FakeRepo()
    cycle, inv = invoice_in(repo, None, status="ok")
    repo.update_invoice(inv["id"], {"vendor_key": "macfos"})
    correct_invoice(repo, cycle, repo.get_invoice(inv["id"]), {"vendor_key": "amazon"}, "me")
    assert repo.get_invoice(inv["id"])["extraction_status"] == "needs_check"
