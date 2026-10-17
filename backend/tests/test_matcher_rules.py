"""Each matching rule of project_context.md section 8 on small made-up cases (fake merchants, fake amounts).
The real June and September data are in test_matcher.py and test_matcher_september.py."""

from datetime import date

import pytest

from app.engine.matcher import CsvGroup, CsvReport, Inv, Pinned, Txn, Vendor, match, vendor_for_line
from app.engine.subsets import SearchTooLarge, closest_subset, exact_subsets
from seed import seed_rows

VENDORS = [
    Vendor(r["vendor_key"], r["display_name"], r["statement_pattern"], r["match_mode"], r["date_before_days"], r["date_after_days"])
    for r in seed_rows()
]


def d(day: int, month: int = 6) -> date:
    return date(2026, month, day)


_serial = iter(range(1, 10_000))


def T(day, description, rupees, *, credit=False, card="4002", usd=None, month=6) -> Txn:
    n = next(_serial)
    return Txn(id=f"t{n}", ser_no=f"{n:011d}", date=d(day, month), description=description, amount_paise=round(rupees * 100),
               is_credit=credit, card_last4=card,
               foreign_amount_minor=round(usd * 100) if usd is not None else None, foreign_currency="USD" if usd is not None else None)


def I(iid, vendor, rupees, day=None, *, order=None, order_day=None, usd=False, credit_note=False, dup=None, pnr=None,
      amounts=None, usd_amounts=()) -> Inv:  # noqa: E743
    total = round(rupees * 100) if rupees is not None else None
    return Inv(id=iid, vendor_key=vendor, currency="USD" if usd else "INR", total_minor=total,
               amounts_minor=tuple(round(a * 100) for a in amounts) if amounts is not None else ((total,) if total else ()),
               invoice_date=d(day) if day else None, order_date=d(order_day) if order_day else None, order_id=order,
               is_credit_note=credit_note, duplicate_of=dup, pnr=pnr, usd_amounts_minor=tuple(round(a * 100) for a in usd_amounts))


def run(txns, invoices=(), **kw):
    return {r.txn_id: r for r in match(txns, list(invoices), VENDORS, **kw)}


def status(results, txn):
    return results[txn.id].status


def linked(results, txn):
    return sorted(link.invoice_id for link in results[txn.id].links)


# ---- Rules 1 to 4 ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("description", ["DCC Fee", "SGST-CI@9%", "CGST-CI@9%", "Late Payment Fee", "Interest Charges", "dcc fee on trip"])
def test_rule_1_bank_charges(description):
    t = T(5, description, 59.29)
    assert status(run([t]), t) == "Bank charge"


def test_rule_1_only_when_the_description_starts_with_the_name():
    t = T(5, "THE DCC FEE SHOP", 59.29)
    assert status(run([t]), t) == "No invoice"


def test_rule_2_payment():
    t = T(10, "CLICK TO PAY PAYMENT RECEIVED", 60472, credit=True)
    assert status(run([t]), t) == "Payment"


def test_rule_3_a_credit_and_a_debit_of_the_same_merchant_and_amount_within_seven_days_are_reversed():
    debit, credit = T(13, "ASSPL Bangalore IN", 400.82), T(20, "ASSPL Bangalore IN", 400.82, credit=True)
    results = run([debit, credit])
    assert status(results, debit) == status(results, credit) == "Reversed"
    assert credit.ser_no in results[debit.id].note and debit.ser_no in results[credit.id].note  # cross-referenced


@pytest.mark.parametrize("credit_day, rupees", [(21, 400.82), (17, 400.83)])
def test_rule_3_not_after_seven_days_and_not_for_a_different_amount(credit_day, rupees):
    debit, credit = T(13, "ASSPL Bangalore IN", 400.82), T(credit_day, "ASSPL Bangalore IN", rupees, credit=True)
    results = run([debit, credit])
    assert status(results, credit) == "Credit – manual" and status(results, debit) != "Reversed"


def test_rule_3_the_merchant_key_is_the_first_18_characters_with_spaces_collapsed():
    debit = T(13, "SWIGGY  GINIE   BENGALURU IN", 2008)
    credit = T(13, "swiggy ginie bengaluru Maharashtra", 2008, credit=True)
    assert status(run([debit, credit]), debit) == "Reversed"


def test_rule_3_one_credit_reverses_one_debit():
    first, second = T(13, "CREATED ANDHERI", 200), T(13, "CREATED ANDHERI", 200)
    credit = T(14, "CREATED ANDHERI", 200, credit=True)
    results = run([first, second, credit])
    assert [status(results, first), status(results, second)] == ["Reversed", "No invoice"]


def test_rule_4_other_credits_are_left_to_a_person():
    t = T(12, "ASSPL Bangalore IN", 149, credit=True)
    assert status(run([t]), t) == "Credit – manual"


# ---- Rule 5: Amazon, invoices only -------------------------------------------------------------------------------
def test_rule_5_one_amazon_invoice_of_the_exact_amount():
    t, inv = T(11, "AMAZONIN GURGAON IN", 269), I("a1", "amazon", 269, 10, order_day=10)
    results = run([t], [inv])
    assert status(results, t) == "Matched" and linked(results, t) == ["a1"]
    assert not results[t.id].links[0].is_suggestion


def test_rule_5_invoices_that_sum_exactly_to_the_charge():
    t = T(13, "ASSPL Bangalore IN", 1018)
    invs = [I("a1", "amazon", 300, 12, order_day=12), I("a2", "amazon", 400, 13, order_day=13), I("a3", "amazon", 318, 13, order_day=13),
            I("a4", "amazon", 99, 13, order_day=13)]
    results = run([t], invs)
    assert status(results, t) == "Matched" and linked(results, t) == ["a1", "a2", "a3"]
    assert "3 invoices sum exactly" in results[t.id].note


@pytest.mark.parametrize("order_day, expected", [(10, "Matched"), (13, "Matched"), (9, "Missing invoice"), (14, "Missing invoice")])
def test_rule_5_window_is_three_days_back_and_none_forward(order_day, expected):
    t, inv = T(13, "ASSPL Bangalore IN", 500), I("a1", "amazon", 500, order_day, order_day=order_day)
    assert status(run([t], [inv]), t) == expected


def test_rule_5_the_order_date_places_an_invoice_not_the_invoice_date():
    t = T(14, "ASSPL Bangalore IN", 99)
    late_invoice = I("a1", "amazon", 99, 22, order_day=14)  # ordered 14/06, invoiced 22/06
    assert status(run([t], [late_invoice]), t) == "Matched"
    no_order_date = I("a2", "amazon", 99, 22)
    assert status(run([t], [no_order_date]), t) == "Missing invoice"  # falls back to the invoice date, 8 days away


def test_rule_5_credit_notes_never_match_a_debit():
    t, note = T(11, "AMAZONIN GURGAON IN", 269), I("cn", "amazon", 269, 10, order_day=10, credit_note=True)
    results = run([t], [note])
    assert status(results, t) == "Missing invoice" and results[t.id].links == []


def test_rule_5_duplicate_invoices_are_never_used():
    t, dup = T(11, "AMAZONIN GURGAON IN", 269), I("d1", "amazon", 269, 10, order_day=10, dup="a1")
    assert status(run([t], [dup]), t) == "Missing invoice"


def test_rule_5_an_invoice_is_used_once():
    first, second = T(11, "ASSPL Bangalore IN", 269), T(12, "ASSPL Bangalore IN", 269)
    results = run([first, second], [I("a1", "amazon", 269, 10, order_day=10)])
    assert [status(results, first), status(results, second)] == ["Matched", "Missing invoice"]


def test_rule_5_a_single_invoice_is_tried_before_sums():
    t = T(13, "ASSPL Bangalore IN", 500)
    invs = [I("sum1", "amazon", 200, 12, order_day=12), I("sum2", "amazon", 300, 12, order_day=12), I("one", "amazon", 500, 13, order_day=13)]
    assert linked(run([t], invs), t) == ["one"]


def test_rule_5_sums_keep_all_the_invoices_of_an_order_together_then_prefer_the_closest_dates():
    t = T(13, "ASSPL Bangalore IN", 500)
    # Four sums make ₹500. Two of them split an order ({o1a, x}, {o1b, y}); {o1a, o1b} and {x, y} do not.
    # Of those two, ORD-1's invoices were ordered on the 13th (0 days away) and the others on the 11th.
    invs = [I("x", "amazon", 300, 11, order="ORD-2", order_day=11), I("y", "amazon", 200, 11, order="ORD-3", order_day=11),
            I("o1a", "amazon", 200, 13, order="ORD-1", order_day=13), I("o1b", "amazon", 300, 13, order="ORD-1", order_day=13)]
    results = run([t], invs)
    assert status(results, t) == "Matched" and linked(results, t) == ["o1a", "o1b"]  # not the list's first, {x, y}


def test_rule_5_when_several_sums_tie_it_is_a_review_suggesting_the_first():
    t = T(13, "ASSPL Bangalore IN", 500)
    invs = [I("x1", "amazon", 250, 13, order_day=13), I("x2", "amazon", 250, 13, order_day=13),
            I("x3", "amazon", 250, 13, order_day=13)]  # any two of three add up: a real tie
    results = run([t], invs)
    assert status(results, t) == "Review" and all(link.is_suggestion for link in results[t.id].links)
    assert linked(results, t) == ["x1", "x2"] and "3 invoice combinations" in results[t.id].note


def test_rule_5_up_to_twelve_invoices_in_one_charge():
    t = T(13, "ASSPL Bangalore IN", 12 * 100)
    invs = [I(f"a{i}", "amazon", 100, 13, order_day=13) for i in range(12)]
    results = run([t], invs)
    assert status(results, t) == "Matched" and len(results[t.id].links) == 12
    t13 = T(13, "ASSPL Bangalore IN", 13 * 100)
    assert status(run([t13], [I(f"b{i}", "amazon", 100, 13, order_day=13) for i in range(13)]), t13) != "Matched"


# ---- Rule 6: IndiGo ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("day, expected", [(4, "Matched"), (7, "Matched"), (8, "Matched"), (3, "Missing invoice"), (9, "Missing invoice")])
def test_rule_6_window_is_three_days_back_and_one_forward(day, expected):
    t, inv = T(7, "INDIGO AIRLINE GURGAON IN", 5000), I("i1", "indigo", 5000, day, pnr="AAAAAA")
    assert status(run([t], [inv]), t) == expected


def test_rule_6_two_sector_invoices_sum_to_the_charge():
    t = T(7, "INDIGO AIRLINE GURGAON IN", 13000)
    invs = [I("out", "indigo", 7000, 6, pnr="PNR111"), I("back", "indigo", 6000, 6, pnr="PNR111")]
    results = run([t], invs)
    assert status(results, t) == "Matched" and linked(results, t) == ["back", "out"]


def test_rule_6_a_sum_from_one_pnr_is_preferred_over_a_mixed_one_that_comes_first():
    t = T(7, "INDIGO AIRLINE GURGAON IN", 13000)
    # m1 + m2 and m1 + m3 both make ₹13,000; m1 + m2 mixes two bookings and comes first in the list.
    invs = [I("m1", "indigo", 7000, 6, pnr="PNR111"), I("m2", "indigo", 6000, 6, pnr="PNR222"),
            I("m3", "indigo", 6000, 6, pnr="PNR111")]
    results = run([t], invs)
    assert status(results, t) == "Matched" and linked(results, t) == ["m1", "m3"]


# ---- Rule 7: every other vendor ---------------------------------------------------------------------------------------
def test_rule_7_exact_inr_amount():
    t, inv = T(8, "MACFOS LIMITED MUMBAI IN", 422), I("m1", "macfos", 422, 8)
    results = run([t], [inv])
    assert status(results, t) == "Matched" and results[t.id].note == "Exact INR amount"


def test_rule_7_a_foreign_amount_equal_to_the_usd_invoice():
    t, inv = T(21, "FATHOM.VIDEO FATHOM.VIDEO US*", 3544.37, usd=36), I("f1", "fathom", 36, 20, usd=True)
    results = run([t], [inv])
    assert status(results, t) == "Matched" and results[t.id].note == "USD 36 matches invoice"


def test_rule_7_usd_cents_are_never_mistaken_for_rupees():
    t, inv = T(21, "FATHOM.VIDEO FATHOM.VIDEO US*", 36, usd=None), I("f1", "fathom", 36, 20, usd=True)
    assert status(run([t], [inv]), t) != "Matched"  # a ₹36.00 charge is not a $36.00 invoice


def test_rule_7_within_one_rupee_for_paise_rounding_ranks_below_an_exact_amount():
    near, exact = I("near", "dtdc", 215.01, 7), I("exact", "dtdc", 215, 7)
    t = T(7, "WWW DTDC IN BANGALORE IN", 215)
    results = run([t], [near, exact])
    assert linked(results, t) == ["exact"] and results[t.id].note == "Exact INR amount"
    only_near = run([t], [near])
    assert linked(only_near, t) == ["near"] and "within Rs 1" in only_near[t.id].note


def test_rule_7_two_rupees_apart_is_not_a_match():
    t = T(7, "WWW DTDC IN BANGALORE IN", 215)
    assert status(run([t], [I("d1", "dtdc", 217, 7)]), t) != "Matched"


@pytest.mark.parametrize("invoice_day, expected", [(1, "Matched"), (15, "Matched"), (16, "Missing invoice"), (24, "Missing invoice")])
def test_rule_7_the_invoice_must_be_within_seven_days(invoice_day, expected):  # the charge is on the 8th: 1st to 15th
    t, inv = T(8, "MACFOS LIMITED MUMBAI IN", 422), I("m1", "macfos", 422, invoice_day)
    assert status(run([t], [inv]), t) == expected


def test_rule_7_an_invoice_with_no_date_is_allowed():
    t, inv = T(8, "MACFOS LIMITED MUMBAI IN", 422), I("m1", "macfos", 422)
    assert status(run([t], [inv]), t) == "Matched"


def test_rule_7_the_order_date_counts_too():
    t = T(7, "TRIPIFY PVT LTD new delhi IN", 54116.08)
    ticket = I("tf", "tripify", 54116.08, 30, order_day=7)  # invoiced 30/06 for a 07/06 booking
    assert status(run([t], [ticket]), t) == "Matched"


def test_rule_7_pairs_are_assigned_globally_closest_date_first():
    near_line, far_line = T(10, "MACFOS LIMITED MUMBAI IN", 500), T(12, "MACFOS LIMITED MUMBAI IN", 500)
    only = I("m1", "macfos", 500, 11)  # one day from the 10th... and one day from the 12th: tie, lowest SerNo wins
    results = run([near_line, far_line], [only])
    assert [status(results, near_line), status(results, far_line)] == ["Matched", "Missing invoice"]
    closer = I("m2", "macfos", 500, 12)
    results = run([near_line, far_line], [closer])
    assert [status(results, near_line), status(results, far_line)] == ["Missing invoice", "Matched"]  # the 12th is the closer line


def test_rule_7_a_usd_amount_printed_on_an_inr_invoice_matches_a_foreign_amount():
    t = T(20, "GOOGLE CLOUD CYBS SI MUMBAI IN", 1700, usd=20)
    inv = I("g1", "google", 1700, 20, usd_amounts=[20])
    assert status(run([t], [inv]), t) == "Matched"


def test_a_candidate_amount_other_than_the_total_matches_even_when_the_invoice_needs_a_check():
    # An invoice with no total line (total unknown) but with every amount it shows.
    t = T(13, "Mailchimp 678-9990141 US", 3069.59)
    inv = I("mc", "mailchimp", None, 13, amounts=[2299.55, 770.04, 73931.40, 3069.59])
    assert inv.total_minor is None
    assert status(run([t], [inv]), t) == "Matched"


def test_an_invoice_without_a_vendor_cannot_match_automatically():
    t = T(1, "WWW DTDC IN BANGALORE IN", 769)
    assert status(run([t], [I("v0", None, 769, 1)]), t) == "Missing invoice"
    assert status(run([t], [I("v1", "dtdc", 769, 1)]), t) == "Matched"  # once a person has chosen the vendor


# ---- Rule 8: near misses ----------------------------------------------------------------------------------------------
def test_rule_8a_the_only_invoice_is_in_usd_and_the_line_shows_inr_only():
    t, inv = T(5, "GENSPARK.AI SINGAPORE SG", 1733.27), I("g1", "genspark", 17.49, 5, usd=True)
    results = run([t], [inv])
    assert status(results, t) == "Review" and results[t.id].links[0].is_suggestion


def test_rule_8a_not_when_the_line_shows_a_foreign_amount_or_there_are_two_invoices():
    t = T(5, "GENSPARK.AI SINGAPORE SG", 1733.27, usd=20)
    assert status(run([t], [I("g1", "genspark", 17.49, 5, usd=True)]), t) == "Missing invoice"
    plain = T(5, "GENSPARK.AI SINGAPORE SG", 1733.27)
    two = [I("g1", "genspark", 17.49, 5, usd=True), I("g2", "genspark", 20, 6, usd=True)]
    assert status(run([plain], two), plain) == "Missing invoice"


def test_rule_8b_an_amazon_debit_equal_to_the_sum_of_the_same_days_credits():
    debit = T(12, "ASSPL Bangalore IN", 53139)
    credits = [T(12, "ASSPL Bangalore IN", 52990, credit=True), T(12, "ASSPL Bangalore IN", 149, credit=True)]
    results = run([debit, *credits])
    assert status(results, debit) == "Review" and results[debit.id].links == []
    assert "₹52,990.00 + ₹149.00" in results[debit.id].note


@pytest.mark.parametrize("invoice, expected", [(100, "Matched"), (104.99, "Review"), (105, "Review"), (105.01, "Missing invoice"),
                                               (95, "Review"), (94.99, "Missing invoice")])
def test_rule_8c_within_five_percent_of_the_charge_is_a_review_beyond_it_is_missing(invoice, expected):
    # The tolerance is 5% of the CHARGE (₹100): an invoice of ₹95 to ₹105 is close enough, ₹105.01 is not.
    t, inv = T(8, "MACFOS LIMITED MUMBAI IN", 100), I("m1", "macfos", invoice, 8)
    assert status(run([t], [inv]), t) == expected


def test_rule_8c_suggests_the_closest_sum_of_invoices_for_amazon_and_indigo():
    t = T(7, "INDIGO AIRLINE GURGAON IN", 15846)
    invs = [I("a", "indigo", 8268, 7, pnr="EBU8WT"), I("b", "indigo", 8313, 7, pnr="EBU8WT")]
    results = run([t], invs)
    assert status(results, t) == "Review" and linked(results, t) == ["a", "b"]
    assert "₹735.00 more" in results[t.id].note and all(link.is_suggestion for link in results[t.id].links)


def test_rule_8c_a_suggestion_reserves_its_invoices_so_no_other_line_is_offered_them():
    first, second = T(8, "MACFOS LIMITED MUMBAI IN", 102), T(9, "MACFOS LIMITED MUMBAI IN", 103)
    results = run([first, second], [I("m1", "macfos", 100, 8)])
    assert [status(results, first), status(results, second)] == ["Review", "Missing invoice"]


def test_rule_8c_other_vendors_suggest_a_single_invoice_only():
    t = T(8, "MACFOS LIMITED MUMBAI IN", 200)
    two = [I("m1", "macfos", 100, 8), I("m2", "macfos", 100, 8)]  # together exact, but Macfos is one invoice per charge
    assert status(run([t], two), t) == "Missing invoice"


def test_rule_8d_the_second_of_two_identical_charges_with_one_invoice_is_a_possible_duplicate():
    first, second = T(6, "SCRIPTIT.FR/CANCEL PARIS FR*", 896.69, usd=8.99), T(6, "SCRIPTIT.FR/CANCEL PARIS FR*", 896.69, usd=8.99)
    results = run([first, second], [I("s1", "scriptit", 8.99, 5, usd=True)])
    assert [status(results, first), status(results, second)] == ["Matched", "Review"]
    assert "Possible duplicate charge" in results[second.id].note and results[second.id].links == []


# ---- Rules 9 and 10 -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("description", ["ATR FOODS LLP SOUTH WEST DE IN", "SWIGGY BANGALORE IN", "CREATED ANDHERI WEST IN"])
def test_rule_9_no_vendor_or_a_vendor_with_no_invoice_expected_is_no_invoice(description):
    t = T(8, description, 314)
    assert status(run([t]), t) == "No invoice"


def test_rule_10_a_known_vendor_with_nothing_matching_is_missing_invoice():
    t = T(8, "MACFOS LIMITED MUMBAI IN", 422)
    assert status(run([t], [I("other", "macfos", 999, 8)]), t) == "Missing invoice"


def test_rule_10_the_note_says_when_the_charge_predates_the_invoice_set():
    early, normal = T(21, "ASSPL Bangalore IN", 1225.5, month=5), T(27, "MACFOS LIMITED MUMBAI IN", 2400)
    results = run([early, normal], [I("m1", "macfos", 100, 8)])
    assert "before the invoice set" in results[early.id].note and "before the invoice set" not in results[normal.id].note


# ---- Amazon report mode (CSV) -------------------------------------------------------------------------------------------------
def group(ref, rupees, day, orders, card="4002"):
    return CsvGroup(ref, d(day), card, tuple(orders), round(rupees * 100))


def report(*groups, start=1, end=30):
    return CsvReport(d(start), d(end), tuple(groups))


def test_report_mode_a_group_of_the_exact_amount_attaches_its_orders_invoices():
    t = T(22, "ASSPL Bangalore IN", 600)
    invs = [I("i1", "amazon", 250, 22, order="O1"), I("i2", "amazon", 350, 22, order="O2"), I("other", "amazon", 600, 22, order="OX")]
    results = run([t], invs, csv=report(group("G1", 600, 22, ["O1", "O2"])))
    assert status(results, t) == "Matched" and linked(results, t) == ["i1", "i2"]
    assert all(link.rule == "amazon_csv" for link in results[t.id].links)


def test_report_mode_missing_orders_make_it_missing_invoice_with_the_attached_ones_listed():
    t = T(22, "ASSPL Bangalore IN", 600)
    invs = [I("i1", "amazon", 250, 22, order="O1")]
    results = run([t], invs, csv=report(group("G1", 600, 22, ["O1", "O2", "O3"])))
    assert status(results, t) == "Missing invoice" and linked(results, t) == ["i1"]
    assert results[t.id].missing_orders == ("O2", "O3")


def test_report_mode_has_no_invoice_only_fallback_inside_the_range():
    # An exact ₹500 invoice is in the date window, but no group equals ₹500: inside the range it is Missing.
    t = T(22, "ASSPL Bangalore IN", 500)
    inv = I("a1", "amazon", 500, 22, order="OX", order_day=22)
    inside = run([t], [inv], csv=report(group("G1", 600, 22, ["O1"])))
    assert status(inside, t) == "Missing invoice" and inside[t.id].links == []
    outside = run([t], [inv], csv=report(group("G1", 600, 22, ["O1"]), start=1, end=10))
    assert status(outside, t) == "Matched"  # the debit is outside the report's range: invoices only


@pytest.mark.parametrize("start, end, expected", [(1, 30, "Missing invoice"), (22, 22, "Missing invoice"), (23, 30, "Matched"), (1, 21, "Matched")])
def test_report_mode_range_is_inclusive_and_decides_the_mode(start, end, expected):
    t = T(22, "ASSPL Bangalore IN", 500)
    inv = I("a1", "amazon", 500, 22, order_day=22)
    assert status(run([t], [inv], csv=report(start=start, end=end)), t) == expected


def test_report_mode_uses_only_groups_of_the_lines_card():
    t = T(22, "ASSPL Bangalore IN", 600, card="2492")
    results = run([t], csv=report(group("G1", 600, 22, ["O1"], card="4002")))
    assert status(results, t) == "Missing invoice" and "No group" in results[t.id].note


@pytest.mark.parametrize("payment_day, found", [(19, True), (22, True), (25, True), (18, False), (26, False)])
def test_report_mode_a_groups_payment_date_must_be_within_three_days_of_the_charge(payment_day, found):
    t = T(22, "ASSPL Bangalore IN", 600)  # charged on the 22nd: groups paid from the 19th to the 25th count
    note = run([t], csv=report(group("G1", 600, payment_day, ["O1"])))[t.id].note
    assert ("equals the charge" in note) is found and ("No group" in note) is not found


def test_report_mode_a_group_within_five_percent_is_a_review_with_its_invoices_suggested():
    t = T(23, "ASSPL Bangalore IN", 1000)
    inv = I("i1", "amazon", 1040, 23, order="O1")
    results = run([t], [inv], csv=report(group("G1", 1040, 23, ["O1"])))
    assert status(results, t) == "Review" and results[t.id].links[0].is_suggestion
    far = run([T(23, "ASSPL Bangalore IN", 1000)], [inv], csv=report(group("G1", 1060, 23, ["O1"])))
    assert list(far.values())[0].status == "Missing invoice"


def test_report_mode_a_group_serves_one_charge():
    first, second = T(22, "ASSPL Bangalore IN", 600), T(22, "ASSPL Bangalore IN", 600)
    results = run([first, second], csv=report(group("G1", 600, 22, ["O1"])))
    assert sorted([status(results, first), status(results, second)]) == ["Missing invoice", "Missing invoice"]
    assert "equals the charge" in results[first.id].note and "No group" in results[second.id].note


def test_report_mode_credit_notes_and_duplicates_are_not_attached():
    t = T(22, "ASSPL Bangalore IN", 600)
    invs = [I("cn", "amazon", 600, 22, order="O1", credit_note=True), I("dup", "amazon", 600, 22, order="O1", dup="x")]
    results = run([t], invs, csv=report(group("G1", 600, 22, ["O1"])))
    assert results[t.id].links == [] and results[t.id].missing_orders == ("O1",)


def test_report_mode_does_not_touch_other_vendors():
    t, inv = T(8, "MACFOS LIMITED MUMBAI IN", 422), I("m1", "macfos", 422, 8)
    assert status(run([t], [inv], csv=report()), t) == "Matched"


# ---- Lines a person decided ----------------------------------------------------------------------------------------------------
def test_pinned_lines_are_left_alone_and_their_invoices_count_as_used():
    pinned_line, other = T(8, "MACFOS LIMITED MUMBAI IN", 422), T(9, "MACFOS LIMITED MUMBAI IN", 422)
    inv = I("m1", "macfos", 422, 8)
    results = run([pinned_line, other], [inv], pinned=[Pinned(pinned_line.ser_no, ("m1",))])
    assert results[pinned_line.id].pinned and results[pinned_line.id].status is None
    assert status(results, other) == "Missing invoice"  # the invoice belongs to the person's line


def test_a_pinned_line_with_no_links_is_still_left_alone():
    t = T(8, "MACFOS LIMITED MUMBAI IN", 422)
    results = run([t], [I("m1", "macfos", 422, 8)], pinned=[Pinned(t.ser_no)])
    assert results[t.id].pinned and results[t.id].links == []


# ---- Odds and ends --------------------------------------------------------------------------------------------------------------
def test_the_same_input_always_gives_the_same_output():
    txns = [T(13, "ASSPL Bangalore IN", 500), T(13, "ASSPL Bangalore IN", 500), T(8, "MACFOS LIMITED MUMBAI IN", 422)]
    invs = [I("a1", "amazon", 250, 13, order_day=13), I("a2", "amazon", 250, 13, order_day=13), I("a3", "amazon", 250, 13, order_day=13),
            I("m1", "macfos", 422, 8)]
    first = [(r.status, [(l.invoice_id, l.is_suggestion) for l in r.links], r.note) for r in match(txns, invs, VENDORS)]
    for _ in range(3):
        assert [(r.status, [(l.invoice_id, l.is_suggestion) for l in r.links], r.note) for r in match(txns, invs, VENDORS)] == first


def test_every_line_gets_a_result_in_the_order_given():
    txns = [T(8, "MACFOS LIMITED MUMBAI IN", 422), T(5, "DCC Fee", 59.29), T(9, "ASSPL Bangalore IN", 10, credit=True)]
    assert [r.txn_id for r in match(txns, [], VENDORS)] == [t.id for t in txns]


def test_the_vendor_whose_statement_pattern_appears_first_wins_and_a_bad_pattern_is_ignored():
    assert vendor_for_line("WWW DTDC IN BANGALORE IN", VENDORS).key == "dtdc"
    assert vendor_for_line("SOMETHING UNKNOWN", VENDORS) is None
    vendors = [Vendor("bad", "Bad", "(unclosed", "single"), Vendor("ok", "Ok", "OK", "single")]
    assert vendor_for_line("an OK shop", vendors).key == "ok"


# ---- The subset search ------------------------------------------------------------------------------------------------------------------
def test_subsets_come_smallest_first_and_in_list_order():
    # 400 alone; then 100+300 and 300+100 (never 200+200: there is one 200); then 100+200+100.
    assert exact_subsets([100, 200, 300, 100, 400], 400) == [(4,), (0, 2), (2, 3), (0, 1, 3)]


def test_subsets_stop_growing_after_fifty_solutions():
    assert len(exact_subsets([1] * 12, 2, stop_after=50)) == 66  # all pairs; size 1 has none, size 2 has 66 (> 50): stop


def test_a_search_that_is_far_too_big_is_reported_not_guessed():
    with pytest.raises(SearchTooLarge):
        exact_subsets([i + 1 for i in range(60)], 1830, budget=10_000)


@pytest.mark.parametrize("total, expected", [(10000, (0,)), (10500, (0,)), (9500, (0,)), (10501, None), (9499, None)])
def test_closest_subset_five_percent_boundaries(total, expected):
    assert closest_subset([total], 10000) == expected  # 5% of the target (10000) is 500


def test_closest_subset_prefers_the_nearest_then_the_fewest():
    assert closest_subset([60, 30, 99], 100) == (2,)  # 99 (off by 1) beats 60 + 30 (off by 10)
    assert closest_subset([100, 60, 40], 100) == (0,)  # 100 and 60 + 40 are both exact: the single invoice wins
