"""The numbers and wording of the Results step (engine/results.py): sum vs charge, search, unused reasons."""

from datetime import date

from app.engine.results import (
    AttachedInvoice,
    attached_sum_paise,
    compare,
    invoice_matches,
    line_matches,
    ReportOrder,
    VendorLine,
    unused_reason,
)

INR = lambda minor: AttachedInvoice("INR", minor)  # noqa: E731
USD = lambda minor: AttachedInvoice("USD", minor)  # noqa: E731


# ---- sum, difference, foreign currency ------------------------------------------------------------------------------
def test_inr_invoices_add_up_to_the_charge():
    c = compare(255744, None, None, [INR(18716), INR(19800), INR(22000), INR(23800), INR(49900), INR(92827), INR(9801), INR(18900)])
    assert (c.attached_sum_paise, c.difference_paise, c.state, c.needs_note) == (255744, 0, "matches", False)


def test_a_suggestion_that_is_149_short_needs_a_note():
    c = compare(5253900, None, None, [INR(5239000)])
    assert (c.attached_sum_paise, c.difference_paise, c.state, c.needs_note) == (5239000, 14900, "differs", True)


def test_invoices_that_are_more_than_the_charge_give_a_negative_difference():
    c = compare(100000, None, None, [INR(120000)])
    assert c.difference_paise == -20000 and c.state == "differs"


def test_no_invoice_attached_is_state_none_and_needs_no_note():
    c = compare(71501, None, None, [])
    assert (c.attached_sum_paise, c.difference_paise, c.state, c.needs_note) == (0, 71501, "none", False)


def test_a_usd_invoice_counts_as_the_whole_charge_only_when_it_equals_the_foreign_amount():
    assert attached_sum_paise(354437, 3600, "USD", [USD(3600)]) == 354437
    assert attached_sum_paise(354437, 3600, "USD", [USD(2000)]) == 0  # a different dollar amount: no rate is assumed
    assert attached_sum_paise(354437, None, None, [USD(3600)]) == 0  # the line has no foreign amount
    assert attached_sum_paise(354437, 3600, "EUR", [USD(3600)]) == 0  # another currency
    c = compare(354437, 3600, "USD", [USD(3600)])
    assert c.state == "matches" and c.difference_paise == 0


def test_an_invoice_without_a_total_adds_nothing():
    assert attached_sum_paise(1000, None, None, [AttachedInvoice("INR", None), INR(400)]) == 400


# ---- search ------------------------------------------------------------------------------------------------------------------
LINE = dict(ser_no="13598184078", description="AMAZON SELLER SERVICES MUMBAI", amount_paise=5253900,
            note="Review: ₹149 less", vendor_name="Amazon", file_names=["200626_Amazon_52390.pdf"])


def test_a_line_is_found_by_its_amount_with_or_without_the_rupee_sign_and_commas():
    for q in ("52539", "52,539", "₹52,539", "52539.00", "5253"):
        assert line_matches(q, **LINE), q
    assert not line_matches("52540", **LINE)


def test_a_line_is_found_by_description_serial_note_vendor_or_file_name():
    for q in ("seller", "mumbai", "13598184078", "149 less", "amazon", "52390.pdf"):
        assert line_matches(q, **LINE), q
    assert line_matches("vistaprint", **{**LINE, "description": "VISTAPRINT INDIA"})
    assert not line_matches("vistaprint", **LINE)


def test_every_word_typed_must_be_found_and_an_empty_search_finds_everything():
    assert line_matches("amazon 52539", **LINE)
    assert not line_matches("amazon 99999", **LINE)
    assert line_matches("", **LINE) and line_matches(None, **LINE) and line_matches("   ", **LINE)


def test_an_invoice_is_found_by_vendor_and_amount_together():
    inv = dict(file_name="240626_Amazon_175.pdf", vendor_key="amazon", vendor_name="Amazon", invoice_no="IN-1",
               order_id="407-1", total_minor=17500)
    assert invoice_matches("amazon 175", **inv)
    assert invoice_matches("175", **inv) and invoice_matches("175.00", **inv) and invoice_matches("₹175", **inv)
    assert not invoice_matches("amazon 176", **inv)
    assert not invoice_matches("macfos", **inv)
    assert invoice_matches("407-1", **inv) and invoice_matches("in-1", **inv)
    assert invoice_matches("amazon", **{**inv, "total_minor": None})  # no total: still found by name


# ---- why an invoice is unused -------------------------------------------------------------------------------------------
D = date
LINES = [VendorLine(D(2026, 6, 20), 5253900, None, None, False)]
BASE = dict(vendor_key="amazon", is_credit_note=False, total_minor=17500, currency="INR", when=D(2026, 6, 24),
            statement_date=D(2026, 6, 28), vendor_lines=LINES, window_days=3, last_amazon_charge=None,
            report_order=None, statement_cards=("4002",))


def test_the_reasons_in_order_without_a_report():
    assert unused_reason(**{**BASE, "is_credit_note": True, "vendor_key": None}) == "Credit note: never matched to a charge"
    assert unused_reason(**{**BASE, "vendor_key": None}) == "No vendor set. Open the invoice and choose one"
    assert unused_reason(**{**BASE, "total_minor": None}) == "No total could be read"
    assert unused_reason(**{**BASE, "when": D(2026, 6, 29)}) == "Dated after the statement date"
    assert unused_reason(**{**BASE, "vendor_lines": []}) == "No statement line for this vendor"
    assert unused_reason(**BASE) == "No charge of this amount found"


def test_an_amazon_invoice_dated_after_the_last_amazon_charge_says_so_with_that_date():
    why = unused_reason(**{**BASE, "when": D(2026, 6, 28), "last_amazon_charge": D(2026, 6, 27)})
    assert why == "Dated after the last Amazon charge on this statement (27/06)"
    # On or before the last charge it is not that reason; the statement date still comes first.
    assert unused_reason(**{**BASE, "when": D(2026, 6, 27), "last_amazon_charge": D(2026, 6, 27)}) == "No charge of this amount found"
    assert unused_reason(**{**BASE, "when": D(2026, 6, 30), "last_amazon_charge": D(2026, 6, 27)}) == "Dated after the statement date"
    # Another vendor never gets the Amazon wording (the caller passes no last Amazon charge for it).
    assert unused_reason(**{**BASE, "vendor_key": "macfos", "when": D(2026, 6, 28)}) == "No charge of this amount found"


def test_with_a_report_the_order_says_how_it_was_paid():
    gift = ReportOrder(paid_on=D(2026, 6, 9), is_gift=True, card_last4=None)
    assert unused_reason(**{**BASE, "report_order": gift}) == "Paid by gift balance"
    other = ReportOrder(paid_on=D(2026, 6, 20), is_gift=False, card_last4="9999")
    assert unused_reason(**{**BASE, "report_order": other}) == "Paid on another card"
    later = ReportOrder(paid_on=D(2026, 7, 2), is_gift=False, card_last4="4002")
    assert unused_reason(**{**BASE, "report_order": later}) == "Paid on 02/07 (after this statement)"
    # Paid on this card before the statement date: the report adds nothing, the ordinary reasons follow.
    mine = ReportOrder(paid_on=D(2026, 6, 20), is_gift=False, card_last4="4002")
    assert unused_reason(**{**BASE, "report_order": mine}) == "No charge of this amount found"
    # No card known on the statement: "another card" can't be said.
    assert unused_reason(**{**BASE, "report_order": other, "statement_cards": ()}) == "No charge of this amount found"


def test_the_report_reasons_are_for_amazon_orders_found_by_order_id_and_come_before_the_date_rules():
    later = ReportOrder(paid_on=D(2026, 7, 2), is_gift=False, card_last4="4002")
    assert unused_reason(**{**BASE, "report_order": later, "when": D(2026, 6, 29)}) == "Paid on 02/07 (after this statement)"
    gift = ReportOrder(paid_on=None, is_gift=True, card_last4=None)
    assert unused_reason(**{**BASE, "report_order": gift, "last_amazon_charge": D(2026, 6, 1)}) == "Paid by gift balance"


def test_a_charge_of_the_same_amount_is_described_by_what_happened_to_it():
    window = 7
    matched = [VendorLine(D(2026, 6, 22), 90000, None, None, True)]
    assert unused_reason(**{**BASE, "vendor_key": "vistaprint", "total_minor": 90000, "when": D(2026, 6, 22), "vendor_lines": matched, "window_days": window}) \
        == "A charge of ₹900.00 on 22/06/2026 is matched to another invoice"
    unmatched_near = [VendorLine(D(2026, 6, 22), 90000, None, None, False)]
    assert unused_reason(**{**BASE, "vendor_key": "vistaprint", "total_minor": 90000, "when": D(2026, 6, 22), "vendor_lines": unmatched_near, "window_days": window}) \
        == "A charge of ₹900.00 exists on 22/06/2026 but was not matched to this invoice"
    far = [VendorLine(D(2026, 5, 22), 90000, None, None, False)]
    assert unused_reason(**{**BASE, "vendor_key": "vistaprint", "total_minor": 90000, "when": D(2026, 6, 22), "vendor_lines": far, "window_days": window}) \
        == "A charge of ₹900.00 exists on 22/05/2026, 31 days from the invoice date (invoices are matched within 7 days)"


def test_a_usd_invoice_is_compared_by_its_dollar_amount_like_fathom():
    fathom = [VendorLine(D(2026, 5, 28), 199518, 2000, "USD", False), VendorLine(D(2026, 6, 21), 354437, 3600, "USD", True)]
    why = unused_reason(**{**BASE, "vendor_key": "fathom", "currency": "USD", "total_minor": 2000, "when": D(2026, 6, 26),
                           "vendor_lines": fathom, "window_days": 7})
    assert why == "A charge of $20.00 exists on 28/05/2026, 29 days from the invoice date (invoices are matched within 7 days)"
    # A dollar amount no charge has (and a rupee charge of the same number does not count).
    other = [VendorLine(D(2026, 6, 26), 2000, None, None, False)]
    assert unused_reason(**{**BASE, "vendor_key": "fathom", "currency": "USD", "total_minor": 2000, "when": D(2026, 6, 26),
                            "vendor_lines": other, "window_days": 7}) == "No charge of this amount found"