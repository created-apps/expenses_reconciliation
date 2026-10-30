"""The four October 2026 findings (project_context.md section 11, 2026-10-29): a refund only reverses an earlier
charge, an exact report group is never lost to a near miss, an invoice with no vendor is matched on amount and
date, and the amounts, dates and issuers read from invoices. Made-up values only; the real October files are
checked by scripts/probe_cycle.py (Docker)."""

from dataclasses import replace
from datetime import date

from app.engine.invoices.dates import find_dates
from app.engine.invoices.detect import detect_vendor
from app.engine.invoices.generic import extract_generic
from app.engine.matcher import CsvGroup, CsvReport, Inv, Txn, match
from seed import seed_rows, seed_vendors
from test_matcher_rules import I as June, T, VENDORS, d, linked, run, status

from app.engine.invoices.types import VendorPattern

AMAZON = "ASSPL Bangalore IN"


def I(iid, vendor, amount, day, **kw):  # noqa: E743 - the shared helper dates invoices in June; these are October
    inv = June(iid, vendor, amount, None, **{**kw, "order_day": None})
    order_day = kw.get("order_day")
    return replace(inv, invoice_date=d(day, 10), order_date=d(order_day, 10) if order_day else None)


def group(ref, day, orders, paise):
    return CsvGroup(reference=ref, payment_date=d(day, 10), card_last4="4002", order_ids=tuple(orders), amount_paise=paise)


def report(*groups):
    return CsvReport(payment_from=d(1, 10), payment_to=d(28, 10), groups=tuple(groups))


# ---- 1.1 a refund never reverses a later charge --------------------------------------------------------------
def test_1_1_a_credit_does_not_reverse_a_charge_five_days_after_it():
    credit, charge = T(2, AMAZON, 299, credit=True, month=10), T(7, AMAZON, 299, month=10)
    inv = I("i299", "amazon", 299, 7, order_day=7)
    results = run([credit, charge], [inv])
    assert status(results, charge) == "Matched" and linked(results, charge) == ["i299"]
    assert status(results, credit) == "Credit – manual"


def test_1_1_a_credit_still_reverses_an_earlier_or_same_day_charge():
    for charge_day in (2, 5):  # the credit is on the 5th: same day, and three days later
        charge, credit = T(charge_day, "CREATED ANDHERI WEST", 500, month=10), T(5, "CREATED ANDHERI WEST", 500, credit=True, month=10)
        results = run([charge, credit])
        assert status(results, charge) == status(results, credit) == "Reversed"


def test_1_1_the_nearest_earlier_charge_is_the_one_reversed():
    far, near = T(1, "CREATED ANDHERI WEST", 500, month=10), T(4, "CREATED ANDHERI WEST", 500, month=10)
    credit = T(5, "CREATED ANDHERI WEST", 500, credit=True, month=10)
    results = run([far, near, credit])
    assert status(results, near) == "Reversed" and status(results, far) != "Reversed"


def test_1_1_a_charge_with_its_own_exact_invoice_is_not_taken_for_reversed():
    charge, credit = T(3, "MACFOS LIMITED MUMBAI IN", 1096, month=10), T(4, "MACFOS LIMITED MUMBAI IN", 1096, credit=True, month=10)
    results = run([charge, credit], [I("m1", "macfos", 1096, 3)])
    assert status(results, charge) == "Matched" and status(results, credit) == "Credit – manual"


# ---- 1.2 exact report groups are given out before near misses ------------------------------------------------------------
def test_1_2_the_exact_charge_gets_the_group_even_though_a_near_miss_comes_first():
    exact, near = T(2, AMAZON, 989, month=10), T(2, AMAZON, 969, month=10)  # the 969 charge is sorted first
    g = group("G989", 2, ("A", "B", "C"), 98900)
    invoices = [I(f"i{o}", "amazon", p, 2, order=o, order_day=2) for o, p in (("A", 181), ("B", 299), ("C", 509))]
    results = run([near, exact], invoices, csv=report(g))
    assert status(results, exact) == "Matched" and linked(results, exact) == ["iA", "iB", "iC"]
    assert status(results, near) == "Missing invoice" and linked(results, near) == []


def test_1_2_a_near_miss_may_still_use_a_group_nobody_equals():
    near = T(2, AMAZON, 1020, month=10)
    results = run([near], [I("iA", "amazon", 1000, 2, order="A", order_day=2)], csv=report(group("G1", 2, ("A",), 100000)))
    assert status(results, near) == "Review" and results[near.id].links[0].is_suggestion


# ---- 1.3 invoices with no vendor, matched on amount and date -----------------------------------------------------------------
def test_1_3_an_inr_invoice_with_no_vendor_matches_the_one_line_with_that_amount():
    krisp = T(2, "UNKNOWN SHOP MUMBAI IN", 3564, month=10)
    other = T(3, "ANOTHER SHOP MUMBAI IN", 3000, month=10)
    results = run([krisp, other], [I("n1", None, 3564, 2)])
    assert status(results, krisp) == "Matched" and linked(results, krisp) == ["n1"]
    assert "Vendor taken from the statement line" in results[krisp.id].note
    assert status(results, other) == "No invoice"


def test_1_3_a_usd_invoice_with_no_vendor_matches_the_statement_foreign_amount():
    line = T(2, "UNKNOWN SAAS PARIS FR*", 1894.02, usd=18.88, month=10)
    results = run([line], [I("u1", None, 18.88, 1, usd=True)])
    assert status(results, line) == "Matched" and linked(results, line) == ["u1"]


def test_1_3_several_lines_that_fit_one_invoice_make_a_review_never_a_guess():
    a, b = T(2, "UNKNOWN SHOP MUMBAI IN", 718, month=10), T(5, "ANOTHER SHOP MUMBAI IN", 718, month=10)
    results = run([a, b], [I("n1", None, 718, 3)])
    reviews = [t for t in (a, b) if status(results, t) == "Review"]
    assert len(reviews) == 1 and results[reviews[0].id].links[0].is_suggestion
    assert "2 statement lines fit" in results[reviews[0].id].note
    assert sum(status(results, t) == "Matched" for t in (a, b)) == 0


def test_1_3_a_date_outside_the_window_or_a_different_amount_never_matches():
    line = T(2, "UNKNOWN SHOP MUMBAI IN", 500, month=10)
    assert status(run([line], [I("n1", None, 500, 20)]), line) == "No invoice"
    assert status(run([line], [I("n1", None, 501, 2)]), line) == "No invoice"
    assert status(run([line], [I("n1", None, 500, 2, dup="x")]), line) == "No invoice"  # a duplicate is not used twice
    assert status(run([line], [I("n1", None, 500, 2, credit_note=True)]), line) == "No invoice"


def test_1_3_a_vendor_invoice_still_goes_through_its_own_vendor_first():
    line = T(2, "MACFOS LIMITED MUMBAI IN", 1096, month=10)
    results = run([line], [I("v1", None, 1096, 2), I("m1", "macfos", 1096, 2)])
    assert linked(results, line) == ["m1"]


# ---- the October vendors (migration 0005) ------------------------------------------------------------------------------
def test_the_october_aliases_resolve_their_statement_descriptions():
    from app.engine.matcher import vendor_for_line

    wanted = {
        "INDIANHOBBYCENTER KHORDHA IN": "indianhobbycenter", "SEMBLY AI, INC SEMBLY.AI US*": "sembly",
        "KRISP KRISP.AI US*": "krisp", "GAMMA.APP GAMMA.APP US": "gamma", "PADDLE.NET* STEALTH WR London GB*": "stealthwriter",
        "RAZ*PROMEAL BIOTECH PRIVA NASHIK M": "promeal", "RETAIL CC MUMBAI IN": "retailmumbai",
        "Phantombuster Paris FR*": "phantombuster", "NETFLIX DI SI MUMBAI IN": "netflix", "IND*LINKEDIN (PGSI) WWW.LINKEDIN.": "linkedin",
    }
    for description, key in wanted.items():
        found = vendor_for_line(description, VENDORS)
        assert found is not None and found.key == key, description
    assert len(seed_rows()) == 40


# ---- 1.4 what is read from the invoice -----------------------------------------------------------------------------------------
IHC = """THE HOBBY SHOP   TAX INVOICE
Date: 02 Oct 2026
  Total Items / Qty : 17 / 49                                          ₹63.56
  Total amount (in words): INR Three Thousand, Five Hundred And Sixty-Four Rupees Only.
                                            Taxable Amount             ₹3,020.34
                                            IGST 18.0%                 ₹543.66
                                            Total                      ₹3,564.00
"""

NETFLIX = """29/10/2026, 16:06      Netflix
  Date               Description                            Service Period               Rate     Amount   Total

  03/10/26           Streaming Service                      03/10/26—02/11/26                       ₹550   ₹649
                     CGST                                                                 9%      ₹49.50
                                                                                         SUBTOTAL         ₹550
                                                                                         TAX TOTAL         ₹99
                                                                                         TOTAL      ₹649
  Payment Date: 10/3/26, 1:06 AM
"""

LINKEDIN = """Tax Invoice from LinkedIn Singapore Pte Ltd      SAC: 998439
Effective Date                Transaction ID             Invoice Number
10/13/2026                    P3103150979                511326745028

Amount                        Transaction Date           Billing Frequency
₹847.03                       10/12/2026                 Monthly
Andheri West Railway Station Locality/Sub Locality: Andheri West
                                    Total :                         ₹847.03
"""

PADDLE = """Tax invoice PAID
Stealthwriter
16th October 2026 - $16.95   via Paddle.com
Billing period: 16th October 2026 - 16th November 2026
Subtotal   $16.95
Total   $16.95
"""

TWILIO = """Tax Invoice for
Sep 1 2026 - Sep 30 2026
Invoice Number   Issue Date
Invoice Amount in USD
MFGRPI-2026-09   Sep 30 2026
$0.60
Invoice Amount   $0.60
"""


def test_1_4_the_total_is_the_total_row_not_a_shipping_or_tax_row():
    ihc, netflix = extract_generic(IHC, "x")[0], extract_generic(NETFLIX, "x")[0]
    assert ihc.total_minor == 356400 and ihc.currency == "INR"
    assert netflix.total_minor == 64900


def test_1_4_dates_with_a_day_first_header_a_short_year_or_an_ordinal():
    assert extract_generic(NETFLIX, "x")[0].invoice_date == date(2026, 10, 3)  # not the 29/10 print stamp, not 10/3/26 as 10 March
    assert extract_generic(PADDLE, "x")[0].invoice_date == date(2026, 10, 16)
    assert extract_generic(TWILIO, "x")[0].invoice_date == date(2026, 9, 30)
    assert [x for _, x in find_dates("October 27th, 2026")] == [date(2026, 10, 27)]


def test_1_4_a_document_with_a_second_field_above_12_is_month_first():
    invoice = extract_generic(LINKEDIN, "x")[0]
    assert invoice.invoice_date == date(2026, 10, 12) and invoice.total_minor == 84703
    assert [x for _, x in find_dates("10/12/2026")] == [date(2026, 12, 10)]  # on its own, still day first (India)
    assert [x for _, x in find_dates("10/12/2026 and 10/13/2026")] == [date(2026, 10, 12), date(2026, 10, 13)]
    assert [x for _, x in find_dates("13/10/2026 and 10/11/2026")] == [date(2026, 10, 13), date(2026, 11, 10)]


def test_1_4_the_issuer_is_the_vendor_not_a_word_in_the_address():
    vendors = seed_vendors()
    assert detect_vendor(LINKEDIN, vendors) == "linkedin"  # "Railway Station" in the address no longer makes it Railway
    assert detect_vendor("Invoice from\nSomeone\nRailway", vendors) == "railway"  # a column heading is not an issuer
    assert detect_vendor(PADDLE, vendors) == "stealthwriter"
    assert detect_vendor(IHC, vendors) == "indianhobbycenter"
    assert detect_vendor("Billed by:\nThe Phantom Company\nInvoice 275998", vendors) == "phantombuster"
