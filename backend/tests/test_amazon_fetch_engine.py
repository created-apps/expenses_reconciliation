"""The "Amazon invoices to fetch" rules and the report coverage (engine/amazon_fetch.py), on small cases, and
their agreement with the matcher."""

from datetime import date

from app.engine.amazon_csv import AmazonRow
from app.engine.amazon_fetch import Coverage, order_amounts, orders_to_fetch, report_coverage
from app.engine.matcher import CsvGroup, CsvReport, Inv, Txn, match
from seed import seed_rows
from app.engine.matcher import Vendor

D = date


def txn(n: int, day: date, paise: int, card: str = "4002") -> Txn:
    return Txn(f"T{n}", f"S{n}", day, "ASSPL Bangalore IN", paise, False, card)


def group(ref: str, day: date, orders: tuple[str, ...], paise: int, card: str | None = "4002") -> CsvGroup:
    return CsvGroup(ref, day, card, orders, paise)


def report(*groups: CsvGroup, start=D(2026, 6, 1), end=D(2026, 6, 30)) -> CsvReport:
    return CsvReport(start, end, tuple(groups))


def row(order: str, ref: str | None, paise: int, *, method: str | None = "Visa", day=D(2026, 6, 20), card="4002") -> AmazonRow:
    return AmazonRow(order, day, ref, day if method else None, method, card, 1, paise)


# ---- the list ---------------------------------------------------------------------------------------------------------------
def test_the_orders_of_the_group_that_pays_a_charge_and_have_no_invoice_are_listed():
    g = group("R1", D(2026, 6, 20), ("A", "B", "C"), 1000000)
    amounts = {("R1", "A"): 300000, ("R1", "B"): 400000, ("R1", "C"): 300000}
    found = orders_to_fetch([txn(1, D(2026, 6, 20), 1000000)], report(g), amounts, {"A"})
    assert [(o.order_id, o.amount_paise, o.group_reference, o.ser_no, o.charge_date) for o in found] == [
        ("B", 400000, "R1", "S1", D(2026, 6, 20)), ("C", 300000, "R1", "S1", D(2026, 6, 20)),
    ]
    assert orders_to_fetch([txn(1, D(2026, 6, 20), 1000000)], report(g), amounts, {"A", "B", "C"}) == []


def test_a_charge_with_no_group_of_its_amount_lists_nothing():
    g = group("R1", D(2026, 6, 20), ("A",), 700000)
    assert orders_to_fetch([txn(1, D(2026, 6, 20), 1000000)], report(g), {}, set()) == []


def test_only_groups_of_the_same_card_and_within_three_days_of_the_charge_count():
    other_card = group("R1", D(2026, 6, 20), ("A",), 100000, card="9999")
    too_late = group("R2", D(2026, 6, 24), ("B",), 100000)
    near = group("R3", D(2026, 6, 23), ("C",), 100000)
    found = orders_to_fetch([txn(1, D(2026, 6, 20), 100000)], report(other_card, too_late, near), {}, set())
    assert [o.order_id for o in found] == ["C"]


def test_a_charge_outside_the_reports_payment_range_is_not_looked_at():
    g = group("R1", D(2026, 5, 21), ("A",), 100000)
    assert orders_to_fetch([txn(1, D(2026, 5, 21), 100000)], report(g, start=D(2026, 6, 1)), {}, set()) == []


def test_two_charges_of_the_same_amount_take_two_different_groups():
    g1 = group("R1", D(2026, 6, 20), ("A",), 100000)
    g2 = group("R2", D(2026, 6, 21), ("B",), 100000)
    found = orders_to_fetch([txn(1, D(2026, 6, 20), 100000), txn(2, D(2026, 6, 21), 100000)], report(g1, g2), {}, set())
    assert sorted((o.ser_no, o.order_id) for o in found) == [("S1", "A"), ("S2", "B")]


def test_an_exact_group_goes_to_its_charge_before_a_near_miss_can_take_it_just_as_in_the_matcher():
    vendors = [Vendor(r["vendor_key"], r["display_name"], r["statement_pattern"], r["match_mode"], r["date_before_days"], r["date_after_days"]) for r in seed_rows()]
    only = group("R1", D(2026, 6, 20), ("A",), 100000)  # 1,000.00
    # S1 (20/06, 1,020.00) has no equal group, but R1 is within 5%. S2 (21/06, 1,000.00) equals R1 exactly. The exact
    # charge wins although it comes later: S2 takes R1 and S1 is left with nothing.
    lines = [txn(1, D(2026, 6, 20), 102000), txn(2, D(2026, 6, 21), 100000)]
    results = {r.ser_no: r for r in match(lines, [], vendors, csv=report(only))}
    assert results["S2"].status == "Missing invoice" and results["S2"].missing_orders == ("A",)
    assert results["S1"].status == "Missing invoice" and results["S1"].missing_orders == () and not results["S1"].links
    assert [(o.ser_no, o.order_id) for o in orders_to_fetch(lines, report(only), {}, set())] == [("S2", "A")]  # the list agrees

def test_it_picks_exactly_what_the_matcher_picks_and_names_the_same_missing_orders():
    vendors = [Vendor(r["vendor_key"], r["display_name"], r["statement_pattern"], r["match_mode"], r["date_before_days"], r["date_after_days"]) for r in seed_rows()]
    g1 = group("R1", D(2026, 6, 20), ("A", "B", "C"), 1000000)
    g2 = group("R2", D(2026, 6, 25), ("D", "E"), 250000)
    rep = report(g1, g2)
    lines = [txn(1, D(2026, 6, 20), 1000000), txn(2, D(2026, 6, 25), 250000), txn(3, D(2026, 6, 26), 77700)]
    invoices = [Inv("I1", "amazon", "INR", 300000, (), D(2026, 6, 20), D(2026, 6, 20), "A")]
    results = match(lines, invoices, vendors, csv=rep)
    from_matcher = sorted(o for r in results for o in r.missing_orders)
    from_list = sorted(o.order_id for o in orders_to_fetch(lines, rep, {}, {"A"}))
    assert from_matcher == from_list == ["B", "C", "D", "E"]


# ---- amounts and coverage --------------------------------------------------------------------------------------------------
def test_an_orders_amount_is_the_sum_of_its_card_paid_rows():
    rows = [row("A", "R1", 100000), row("A", "R1", 50000), row("B", "R1", 20000), row("G", "RG", 999, method="Gift Certificate/Card", card=None)]
    assert order_amounts(rows) == {("R1", "A"): 150000, ("R1", "B"): 20000}


def test_coverage_counts_orders_with_missing_partly_covered_and_gift_invoices():
    rows = [
        row("A", "R1", 300000), row("B", "R1", 400000), row("C", "R1", 300000), row("D", "R2", 100000),
        row("G1", "RG", 15800, method="Gift Certificate/Card", card=None), row("G2", "RG2", 9900, method="Gift Certificate/Card", card=None),
        row("U", None, 5000, method=None),  # ordered, never paid: in neither list
    ]
    cov = report_coverage(rows, {"A": 300000, "B": 350000, "G1": 15800})  # B is only partly invoiced
    assert cov == Coverage(card_orders=4, with_invoice=2, without_invoice=2, partly_invoiced=1, gift_orders=2, gift_with_invoice=1)
