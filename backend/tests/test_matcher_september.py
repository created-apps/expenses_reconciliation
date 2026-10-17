"""Test 9.6: CSV mode on September. The September Amazon report, the September bulk invoice ZIP and the
TEST-ONLY statement lines (typed in from a screenshot; there is no September statement PDF).

Docker only (the invoices are read with poppler); skips when the real files are missing. The engine is
called directly: nothing is uploaded and no database is involved."""

import csv
import glob
import hashlib
import shutil
import zipfile
from datetime import date
from pathlib import Path

import pytest

from app.engine.amazon_csv import card_groups, parse_amazon_csv
from app.engine.invoices import VendorPattern, extract_invoices, has_text_layer
from app.engine.matcher import CsvGroup, CsvReport, Inv, Txn, Vendor, match
from app.engine.money import parse_minor
from app.pdf import pdf_text
from seed import seed_rows

FIXTURES = Path(__file__).parent / "fixtures_private"
DOC = next((p for p in (Path(__file__).resolve().parents[2] / "doc" / "reference", Path("/doc/reference")) if p.exists()), None)
ZIPS = sorted(FIXTURES.glob("Tax invoice documents*.zip"))
REPORTS = sorted(FIXTURES.glob("reconciliation_from_*.csv"))
LINES = DOC / "september_2026_statement_lines_TEST_ONLY.csv" if DOC else None

pytestmark = [
    pytest.mark.skipif(not (ZIPS and REPORTS and LINES and LINES.exists()), reason="September fixtures missing"),
    pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext (poppler) not installed; run in Docker"),
]


@pytest.fixture(scope="module")
def september():
    rows = seed_rows()
    patterns = [VendorPattern(r["vendor_key"], r["invoice_pattern"], r["display_name"]) for r in rows]
    vendors = [
        Vendor(r["vendor_key"], r["display_name"], r["statement_pattern"], r["match_mode"], r["date_before_days"], r["date_after_days"])
        for r in rows
    ]
    invoices, numbers, seen = [], {}, set()
    with zipfile.ZipFile(ZIPS[0]) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if info.is_dir() or name.startswith(".") or "__MACOSX" in info.filename or not name.lower().endswith(".pdf"):
                continue
            data = z.read(info)
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            text = pdf_text(data, last_page=None, timeout=60)
            assert has_text_layer(text), name
            for item in extract_invoices(text, patterns):
                iid = f"{name}#{item.block_index}"
                numbers[iid] = item.invoice_no
                invoices.append(Inv(
                    id=iid, vendor_key=item.vendor_key, currency=item.currency, total_minor=item.total_minor,
                    amounts_minor=tuple(item.amounts_minor), invoice_date=item.invoice_date, order_date=item.order_date,
                    order_id=item.order_id, is_credit_note=item.is_credit_note,
                ))

    report_rows = parse_amazon_csv(REPORTS[0].read_bytes())
    paid = [r.payment_date for r in report_rows if r.payment_date]
    report = CsvReport(
        min(paid), max(paid),
        tuple(CsvGroup(g.payment_ref, g.payment_date, g.card_last4, g.order_ids, g.amount_paise) for g in card_groups(report_rows)),
    )
    txns = []
    with open(LINES, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d, m, y = r["date"].split("/")
            txns.append(Txn(
                id=r["ser_no"], ser_no=r["ser_no"], date=date(int(y), int(m), int(d)), description=r["description"],
                amount_paise=parse_minor(r["amount_inr"]), is_credit=r["is_credit"] == "true", card_last4=r["card_last4"],
                foreign_amount_minor=parse_minor(r["foreign_amount"]) if r["foreign_amount"] else None,
                foreign_currency=r["foreign_currency"] or None,
            ))
    results = {r.ser_no: r for r in match(txns, invoices, vendors, csv=report)}
    return {"results": results, "invoices": {i.id: i for i in invoices}, "numbers": numbers, "report": report, "txns": txns,
            "vendors": vendors}


def attached(september, ser_no):
    result = september["results"][ser_no]
    invoices = [september["invoices"][link.invoice_id] for link in result.links]
    return result, invoices, sum(i.total_minor for i in invoices)


def test_the_september_invoices_are_43_amazon_invoices_with_order_ids(september):
    assert len(september["invoices"]) == 43
    assert {i.vendor_key for i in september["invoices"].values()} == {"amazon"}
    assert all(i.order_id and i.total_minor for i in september["invoices"].values())


def test_the_report_covers_the_whole_month_so_every_amazon_debit_is_in_csv_mode(september):
    report = september["report"]
    assert (report.payment_from, report.payment_to) == (date(2026, 9, 9), date(2026, 9, 30))
    amazon_debits = [t for t in september["txns"] if "ASSPL" in t.description and not t.is_credit]
    assert amazon_debits and all(report.covers(t.date) for t in amazon_debits)


def test_717_attaches_one_invoice_and_names_the_missing_order(september):
    result, invoices, total = attached(september, "14220206486")
    assert result.status == "Missing invoice" and len(invoices) == 1 and total == 48400
    assert september["numbers"][invoices[0].id] == "IN-468"
    assert result.missing_orders == ("404-2278140-2557951",)


def test_11713_46_attaches_four_invoices_and_names_four_missing_orders(september):
    result, invoices, total = attached(september, "14220159813")
    assert result.status == "Missing invoice" and len(invoices) == 4 and total == 386146
    assert result.missing_orders == ("407-0648176-5773946", "407-1162474-9663537", "407-5543022-9991556", "407-8748703-0233950")


def test_12713_14_attaches_seven_invoices_and_names_two_missing_orders(september):
    result, invoices, total = attached(september, "14220238586")
    assert result.status == "Missing invoice" and len(invoices) == 7 and total == 1061202
    assert result.missing_orders == ("407-1432135-3264328", "407-6016348-1857969")


def test_4542_46_attaches_nothing_and_names_two_missing_orders(september):
    result, invoices, _ = attached(september, "14247617858")
    assert result.status == "Missing invoice" and invoices == []
    assert result.missing_orders == ("407-1181179-3994762", "407-5639317-8731563")


def test_3892_06_has_no_group_of_that_amount_and_the_nearest_is_more_than_five_percent_away(september):
    result = september["results"]["14225699283"]
    assert result.status == "Missing invoice" and result.links == [] and result.missing_orders == ()
    assert "No group in the Amazon report equals this charge" in result.note and "₹3,537.71" in result.note


def test_no_invoice_only_fallback_inside_the_report_range(september):
    # The September invoices could be summed to the same amounts by date; inside the report's range the
    # matcher must not try: only the groups' own orders are ever attached.
    for ser in ("14220206486", "14220159813", "14220238586"):
        result = september["results"][ser]
        group_orders = {o for g in september["report"].groups for o in g.order_ids}
        assert all(september["invoices"][link.invoice_id].order_id in group_orders for link in result.links)


def test_the_two_amazon_credits_are_left_for_a_person(september):
    assert september["results"]["14196198995"].status == "Credit – manual"
    assert september["results"]["14230532933"].status == "Credit – manual"
