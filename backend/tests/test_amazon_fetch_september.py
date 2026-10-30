"""The "Amazon invoices to fetch" rules and the report coverage on the real September report and the real
September bulk invoice ZIP (Docker only; skipped when the files are missing). Nothing is uploaded anywhere."""

import shutil
from collections import defaultdict

import pytest

from app.engine.amazon_csv import gift_orders, parse_amazon_csv
from app.engine.amazon_fetch import Coverage, order_amounts, orders_to_fetch, report_coverage
from app.engine.matcher import Txn
from test_matcher_september import LINES, REPORTS, ZIPS, september  # noqa: F401 - the fixture is reused

pytestmark = [
    pytest.mark.skipif(not (ZIPS and REPORTS and LINES and LINES.exists()), reason="September fixtures missing"),
    pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext (poppler) not installed; run in Docker"),
]

PARTLY = {"404-0510362-7968329", "404-5788313-8785103"}  # the invoice covers only part of the order


@pytest.fixture(scope="module")
def rows():
    return parse_amazon_csv(REPORTS[0].read_bytes())


@pytest.fixture(scope="module")
def invoice_totals(september):  # noqa: F811
    totals: dict[str, int] = defaultdict(int)
    for inv in september["invoices"].values():
        if inv.order_id and not inv.is_credit_note and not inv.duplicate_of:
            totals[inv.order_id] += inv.total_minor if inv.currency == "INR" else 0
    return dict(totals)


def test_the_september_bulk_zip_has_43_invoices_for_41_orders(september, invoice_totals):  # noqa: F811
    assert len(september["invoices"]) == 43 and len(invoice_totals) == 41


def test_of_60_card_paid_orders_36_have_an_invoice_and_24_do_not_and_2_of_the_36_are_only_partly_covered(rows, invoice_totals):
    cov = report_coverage(rows, invoice_totals)
    assert cov == Coverage(card_orders=60, with_invoice=36, without_invoice=24, partly_invoiced=2, gift_orders=5, gift_with_invoice=5)
    assert cov.without_invoice / cov.card_orders == 0.4  # the measured September figure: 24 of 60, 40%


def test_the_two_partly_invoiced_orders_are_these(rows, invoice_totals):
    net: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.is_card and r.order_id:
            net[r.order_id] += r.net_total_paise
    partly = {o for o in net if o in invoice_totals and invoice_totals[o] < net[o]}
    assert partly == PARTLY
    assert [(net[o], invoice_totals[o]) for o in sorted(PARTLY)] == [(62090, 37390), (178894, 113094)]


def test_all_five_gift_balance_orders_have_an_invoice_in_the_zip(rows, invoice_totals):
    gifts = {g.order_id for g in gift_orders(rows)}
    assert len(gifts) == 5 and gifts <= set(invoice_totals)


def charges(september):  # noqa: F811
    return [
        Txn(t.id, t.ser_no, t.date, t.description, t.amount_paise, False, t.card_last4)
        for t in september["txns"] if "ASSPL" in t.description and not t.is_credit
    ]


def test_the_four_amazon_charges_list_nine_orders_with_no_invoice(september, rows, invoice_totals):  # noqa: F811
    found = orders_to_fetch(charges(september), september["report"], order_amounts(rows), set(invoice_totals))
    by_charge: dict[str, list[str]] = defaultdict(list)
    for o in found:
        by_charge[o.charge_amount_paise].append(o.order_id)
    assert dict(by_charge) == {
        71700: ["404-2278140-2557951"],
        1171346: ["407-0648176-5773946", "407-1162474-9663537", "407-5543022-9991556", "407-8748703-0233950"],
        1271314: ["407-1432135-3264328", "407-6016348-1857969"],
        454246: ["407-1181179-3994762", "407-5639317-8731563"],
    }
    assert len(found) == 9
    # The 3,892.06 charge has no group of that amount: nothing is listed for it.
    assert all(o.charge_amount_paise != 389206 for o in found)


def test_each_listed_order_carries_its_own_total_from_the_report_and_the_payment_date(september, rows, invoice_totals):  # noqa: F811
    found = orders_to_fetch(charges(september), september["report"], order_amounts(rows), set(invoice_totals))
    net: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.is_card and r.order_id:
            net[r.order_id] += r.net_total_paise
    assert all(o.amount_paise == net[o.order_id] > 0 for o in found)
    # For the three charges whose attached invoices are complete orders, the missing orders add up to the gap.
    gap = {71700: 71700 - 48400, 1171346: 1171346 - 386146, 1271314: 1271314 - 1061202}
    for charge, expected in gap.items():
        assert sum(o.amount_paise for o in found if o.charge_amount_paise == charge) == expected
    assert sum(o.amount_paise for o in found if o.charge_amount_paise == 454246) == 454246
    assert {o.payment_date.isoformat() for o in found} == {"2026-09-22", "2026-09-27"}


def test_the_list_names_the_same_orders_as_the_matcher_does(september, rows, invoice_totals):  # noqa: F811
    found = orders_to_fetch(charges(september), september["report"], order_amounts(rows), set(invoice_totals))
    from_matcher = sorted(o for r in september["results"].values() for o in r.missing_orders)
    assert sorted(o.order_id for o in found) == from_matcher
