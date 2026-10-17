"""Invoice reading: small made-up snippets for each rule, plus the real June invoices.

The real-file tests need poppler's pdftotext and the git-ignored June ZIP in tests/fixtures_private/,
so they run in Docker (`docker compose run --rm tests`) and skip anywhere else. The vendor patterns come
from the seed migration itself (tests/seed.py).
"""

import collections
import hashlib
import shutil
import zipfile
from datetime import date
from pathlib import Path

import pytest

from app.engine.invoices import ExtractedInvoice, VendorPattern, detect_vendor, duplicate_indexes, extract_invoices, has_text_layer
from app.engine.invoices.amounts import amounts_in, distinct_amounts
from app.engine.invoices.dates import date_after_label, find_dates
from app.pdf import pdf_text
from seed import seed_vendors

VENDORS = seed_vendors()

FIXTURES = Path(__file__).parent / "fixtures_private"
found = sorted(FIXTURES.glob("June2026*invoice*.zip"))
JUNE_ZIP = found[0] if found else None
needs_june = pytest.mark.skipif(
    JUNE_ZIP is None or shutil.which("pdftotext") is None,
    reason="June invoice ZIP or pdftotext (poppler) missing; run in Docker",
)


def one(text: str) -> ExtractedInvoice:
    (item,) = extract_invoices(text, VENDORS)
    return item


# ---- Dates ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("Invoice Date: 28.06.2026", date(2026, 6, 28)),
        ("on 04/06/2026 at", date(2026, 6, 4)),
        ("Date : 04-Jun-2026", date(2026, 6, 4)),
        ("Invoice Date  : 30 JUN 2026", date(2026, 6, 30)),
        ("Dated 16-Jun-26", date(2026, 6, 16)),
        ("Date of issue  June 20, 2026", date(2026, 6, 20)),
        ("Invoice Date Jun 09, 2026", date(2026, 6, 9)),
        ("issued 2026-06-04.", date(2026, 6, 4)),
    ],
)
def test_the_date_formats_seen_on_invoices(text, expected):
    assert [d for _, d in find_dates(text)] == [expected]


def test_numeric_dates_are_day_first_and_impossible_dates_are_skipped():
    assert [d for _, d in find_dates("12/06/2026")] == [date(2026, 6, 12)]  # 12 June, not 6 December
    assert find_dates("31/02/2026 and 99/99/2026") == []


def test_a_date_can_sit_under_its_label():
    text = "Invoice#  X1\nInvoice Date:    Sale Order:\n19/06/2026     3537022"
    assert date_after_label(text, r"Invoice Date\s*:", 3) == date(2026, 6, 19)


# ---- Amounts -------------------------------------------------------------------------------------------
def test_amounts_are_integer_minor_units_with_their_currency():
    found = amounts_in("Total ₹ 1,05,980.00 and $133.50 USD, 36 USD, US$17.49, INR 94,146, bare 9100.00, 0.000011")
    assert [(a.minor, a.currency) for a in found] == [
        (10598000, "INR"), (13350, "USD"), (1749, "USD"), (9414600, "INR"), (910000, "INR"),
    ]


def test_distinct_amounts_are_per_currency_and_sorted():
    text = "₹10.00 ₹10.00 ₹5.50 $3.00 US$3.00"
    assert distinct_amounts(text, "INR") == [550, 1000]
    assert distinct_amounts(text, "USD") == [300]


# ---- Vendor detection (text only) -------------------------------------------------------------------------
def test_the_issuer_printed_first_wins_over_a_brand_named_later():
    # A supplier header that links to Google, further down: the first name is the issuer.
    text = "MACFOS LIMITED\nTax invoice\nsee https://plus.google.com/+Robu"
    assert detect_vendor(text, VENDORS) == "macfos"


def test_an_amazon_invoice_is_amazon_even_when_a_product_carries_another_brand():
    text = "Order Number: 408-1-2\nRobocraze ESP32 board\n*ASSPL-Amazon Seller Services Pvt. Ltd."
    assert detect_vendor(text, VENDORS) == "amazon"


def test_no_vendor_and_a_broken_pattern_do_not_raise():
    assert detect_vendor("Some other company", VENDORS) is None
    assert detect_vendor("Acme", [VendorPattern("bad", "(unclosed"), VendorPattern("acme", "Acme")]) == "acme"
    assert detect_vendor("x", [VendorPattern("none", None)]) is None


# ---- Amazon -------------------------------------------------------------------------------------------------
AMAZON_TWO = "\f".join(
    [
        "Order Number: 111-2222222-3333333      Invoice Number : AB1-100\nOrder Date: 01.06.2026\n"
        "Invoice Date : 05.06.2026\nTOTAL:        ₹18.00 ₹118.00\n*ASSPL-Amazon Seller Services Pvt. Ltd.",
        "Order Number: 111-2222222-3333333      Invoice Number : AB1-200\nOrder Date: 01.06.2026\n"
        "Invoice Date : 05.06.2026\nTOTAL:        ₹10.00 ₹60.00\n",
        "continued: Amount in Words\nTOTAL:  ₹5.00 ₹275.00\n",  # a continuation page: belongs to the invoice above
    ]
)


def test_amazon_splits_on_pages_with_an_order_number_and_takes_the_last_total_row():
    first, second = extract_invoices(AMAZON_TWO, VENDORS)
    assert (first.block_index, first.invoice_no, first.total_minor) == (0, "AB1-100", 11800)
    assert (second.block_index, second.invoice_no, second.total_minor) == (1, "AB1-200", 27500)  # last TOTAL: row
    assert first.order_id == second.order_id == "111-2222222-3333333"
    assert (first.order_date, first.invoice_date) == (date(2026, 6, 1), date(2026, 6, 5))
    assert first.amounts_minor == [11800] and first.vendor_key == "amazon" and first.extraction_status == "ok"


def test_an_amazon_credit_note_is_positive_and_flagged():
    text = "Credit Note\nOrder Number: 1-2-3   Invoice Number : CN-1\nOrder Date: 01.06.2026\nInvoice Date : 02.06.2026\n" \
           "TOTAL: ₹1.00 ₹149.00\n*ASSPL-Amazon Seller Services"
    item = one(text)
    assert item.is_credit_note and item.total_minor == 14900


# ---- Vendor layouts ------------------------------------------------------------------------------------------
def test_macfos_uses_its_own_total_line_not_the_items():
    text = (
        "MACFOS LIMITED\nInvoice# INV2627/105815\nInvoice Date:   Sale Order:\n19/06/2026   3537022\n"
        "1  item   ₹ 238.13   2.00   ₹ 562.00\nSubtotal   ₹ 517.80\n2  9% SGST (Sale)  ₹ 46.60    Total    ₹ 611.00\n"
    )
    item = one(text)
    assert (item.vendor_key, item.invoice_no, item.invoice_date) == ("macfos", "INV2627/105815", date(2026, 6, 19))
    assert item.total_minor == 61100 and item.amounts_minor == [61100]  # not 562.00, not the Subtotal


def test_indigo_grand_total_date_and_pnr():
    text = (
        "InterGlobe Aviation Limited\nNumber : MH1262706AY53125\n\nDate : 04-Jun-2026\n\nPNR : YGDDKH   Flight No : 6E - 310\n"
        "   Grand Total      7,451.0   509.00  7,960.0     0.00   186.50   186.50   0.00    8,333.00\n"
    )
    item = one(text)
    assert (item.vendor_key, item.invoice_no, item.invoice_date) == ("indigo", "MH1262706AY53125", date(2026, 6, 4))
    assert item.total_minor == 833300 and item.extra == {"pnr": "YGDDKH"}


def test_dtdc_total_invoice_value_keeps_the_paise():
    text = "DTDC Express Limited\nInvoice No.     MH2727WI016103\nInvoice Date    08.06.2026\nTotal invoice Value     215.01\n"
    item = one(text)
    assert (item.vendor_key, item.invoice_no, item.invoice_date, item.total_minor) == (
        "dtdc", "MH2727WI016103", date(2026, 6, 8), 21501,
    )


# ---- Generic -------------------------------------------------------------------------------------------------
def test_a_usd_receipt_reads_in_dollars():
    text = "Fathom Video Inc.\nInvoice number B8HTVTIE-0007\nDate of issue  June 20, 2026\n$36.00 USD due June 20, 2026\n" \
           "Fathom Team   2   $18.00   $36.00\nSubtotal   $36.00\nTotal   $36.00\nAmount due   $36.00 USD\n"
    item = one(text)
    assert (item.vendor_key, item.invoice_no, item.invoice_date) == ("fathom", "B8HTVTIE-0007", date(2026, 6, 20))
    assert (item.currency, item.total_minor, item.amounts_minor) == ("USD", 3600, [1800, 3600])


def test_total_excluding_tax_is_not_the_total():
    text = "Anthropic, PBC\nInvoice number X-1\nDate of issue June 29, 2026\nTotal excluding tax  $100.00\n" \
           "GST - India (18% on $100.00)  $18.00\nTotal  $118.00\nAmount due  $118.00 USD\n"
    assert one(text).total_minor == 11800


def test_rounded_total_beats_grand_total():
    text = "Shott Amusement Limited  Tax Invoice\nInvoice No:MH1\nInvoice Date: 25-06-2026\n" \
           "Grand Total:  ₹ 8,787.44\nRounded Total:  ₹ 8,787.00\n"
    item = one(text)
    assert item.total_minor == 878700 and 878744 in item.amounts_minor  # the exact figure stays a candidate


def test_a_note_after_the_paid_amount_is_not_the_total():
    text = "MakemyTrip\nBooking Id: NH7915\n(Booked on 07 Jun 2026)\nPaid Amount     INR 94,146       You saved INR 8,071\n"
    item = one(text)
    assert item.total_minor == 9414600 and item.invoice_no == "NH7915" and item.invoice_date == date(2026, 6, 7)


def test_a_table_total_with_no_currency_sign_is_skipped_unless_the_label_has_one():
    sign_in_label = "Airtel\nBill number MF1\nBill date   18-Jun-2026\nTotal (`)      2,192.52\n"
    assert one(sign_in_label).total_minor == 219252
    tax_table_only = "Acme Corp\nInvoice No: A12345\nInvoice Date: 01/06/2026\nTotal   8,885.16   1,599.32\n"
    assert one(tax_table_only).total_minor is None  # no sign, no clear label: left for a person


def test_a_booking_date_is_read_as_the_order_date():
    # A flight-ticket invoice dated at month end that says when the booking was made.
    text = ("Tripify Pvt. Ltd.\nTax Invoice(Air)\nInvoice No.            : TFY336123\n"
            "Invoice Date           : 30 JUN 2026\nBooking Date           : 07 Jun 2026\nNet Payable   INR 54116.08\n")
    item = one(text)
    assert (item.vendor_key, item.invoice_date, item.order_date, item.total_minor) == (
        "tripify", date(2026, 6, 30), date(2026, 6, 7), 5411608,
    )


def test_an_e_invoice_total_is_read_from_the_row_under_its_heading():
    text = "Cimpress India Private Limited\nDocument No: 260615101039522\nDocument Date: 15/06/2026\n" \
           "Cess  Off  Other Charges   Total Invoice Amount\n\n8666.66  216.67  216.67  0.0  0  0  0  0   9100.00\n"
    item = one(text)
    assert item.vendor_key == "vistaprint" and item.total_minor == 910000 and item.invoice_no == "260615101039522"


def test_the_number_under_its_column_header_is_read_not_text_beside_it():
    text = "AqTronics Technologies\nNo.1 9TH MAIN ROAD                  Invoice No.      Dated\n" \
           "Bangalore                                 Aq/LP/26-27/1505   25-Jun-26\nTotal   6 Nos   ₹ 10,484.00\n"
    item = one(text)
    assert item.invoice_no == "Aq/LP/26-27/1505" and item.invoice_date == date(2026, 6, 25) and item.total_minor == 1048400


# ---- Validation -----------------------------------------------------------------------------------------------
def test_an_invoice_with_everything_is_ok():
    item = one("Fathom\nInvoice number AB-1\nDate of issue June 20, 2026\nTotal  $36.00\n")
    assert item.extraction_status == "ok" and item.problems == []


@pytest.mark.parametrize(
    "text, problem",
    [
        ("Acme Ltd\nInvoice No: A12345\nInvoice Date: 01/06/2026\n", "Vendor not recognised"),
        ("Fathom\nInvoice number AB-1\nDate of issue June 20, 2026\n", "No total found"),
        ("Fathom\nInvoice number AB-1\nTotal  $36.00\n", "No date found"),
    ],
)
def test_a_missing_vendor_total_or_date_makes_it_needs_check_and_says_why(text, problem):
    item = one(text)
    assert item.extraction_status == "needs_check" and problem in item.problems


def test_text_layer_check():
    assert has_text_layer("Invoice number AB-1 Total 36.00 USD thank you")
    assert not has_text_layer(" \n \f  ")
    assert not has_text_layer("12 34")


# ---- Invoice-level duplicates -----------------------------------------------------------------------------------
def row(vendor="amazon", number="IN-1", total=1000, currency="INR"):
    return {"vendor_key": vendor, "invoice_no": number, "total_minor": total, "currency": currency}


def test_the_same_vendor_number_and_total_again_is_a_duplicate_of_the_first():
    rows = [row(), row(number="IN-2"), row(number=" in-1 ")]
    assert duplicate_indexes(rows) == {2: 0}  # case and spaces in the number don't hide a copy


def test_a_different_total_vendor_or_currency_is_not_a_duplicate():
    rows = [row(), row(total=1001), row(vendor="macfos"), row(currency="USD")]
    assert duplicate_indexes(rows) == {}


def test_an_invoice_missing_its_number_or_total_is_never_called_a_duplicate():
    rows = [row(number=None), row(number=None), row(total=None), row(total=None), row(vendor=None), row(vendor=None)]
    assert duplicate_indexes(rows) == {}


def test_a_third_copy_points_at_the_first():
    assert duplicate_indexes([row(), row(), row()]) == {1: 0, 2: 0}


# ---- The real June invoices -------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def june():
    """{file name: [ExtractedInvoice]} for the PDF invoices in the June ZIP, as upload would keep them:
    byte-identical copies counted once, and the copy of the statement left out."""
    out: dict[str, list[ExtractedInvoice]] = {}
    seen: set[str] = set()
    with zipfile.ZipFile(JUNE_ZIP) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if info.is_dir() or "__MACOSX" in info.filename or name.startswith(".") or not name.lower().endswith(".pdf"):
                continue
            data = z.read(info)
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            text = pdf_text(data, last_page=None, timeout=60)
            if "CREDIT CARD STATEMENT" in text and "STATEMENT SUMMARY" in text:
                continue
            out[name] = extract_invoices(text, VENDORS)
    return out


@needs_june
def test_june_112_invoices_from_111_pdf_files(june):
    assert len(june) == 111
    assert sum(len(v) for v in june.values()) == 112
    assert all(v for v in june.values())  # every file gave at least one invoice (all have a text layer)


@needs_june
def test_june_62_amazon_invoices_from_61_files(june):
    amazon = {name: [i for i in items if i.vendor_key == "amazon"] for name, items in june.items()}
    amazon = {name: items for name, items in amazon.items() if items}
    assert len(amazon) == 61 and sum(len(v) for v in amazon.values()) == 62
    assert [len(v) for n, v in amazon.items() if len(v) > 1] == [2]  # only 280626_Amazon_1263.pdf holds two


@needs_june
def test_june_amazon_two_invoices_in_one_file(june):
    first, second = june["280626_Amazon_1263.pdf"]
    assert (first.invoice_no, first.total_minor) == ("MAA4-1138", 34900)
    assert (second.invoice_no, second.total_minor) == ("MAA4-982422", 91400)
    assert first.order_id == second.order_id == "408-8124784-9796354"
    assert (first.order_date, first.invoice_date) == (date(2026, 6, 28), date(2026, 6, 28))


@needs_june
def test_june_amazon_single_invoice(june):
    (inv,) = june["130626_Amazon_928.27.pdf"]
    assert (inv.order_id, inv.invoice_no, inv.invoice_date, inv.total_minor) == (
        "408-4454576-4641947", "IN-9370", date(2026, 6, 13), 92827,
    )
    assert inv.order_date == date(2026, 6, 13) and not inv.is_credit_note


@needs_june
def test_june_the_eight_amazon_invoices_behind_the_2557_44_charge_add_up(june):
    names = ["130626_Amazon_187.16(2).pdf", "130626_Amazon_198.pdf", "130626_Amazon_220.pdf", "130626_Amazon_238.pdf",
             "130626_Amazon_499.pdf", "130626_Amazon_928.27.pdf", "130626_Amazon_98.01.pdf", "130626_amazon_189(1).pdf"]
    assert sum(june[n][0].total_minor for n in names) == 255744


@needs_june
def test_june_a_file_name_is_not_trusted_for_the_amount(june):
    (inv,) = june["190626_Macfos_715.pdf"]  # named 715, really a Rs 611 invoice
    assert (inv.vendor_key, inv.total_minor, inv.invoice_date) == ("macfos", 61100, date(2026, 6, 19))


@needs_june
def test_june_indigo_dtdc_and_a_usd_receipt(june):
    (indigo,) = june["TaxInvoiceMH1262706AY53125.pdf"]
    assert (indigo.vendor_key, indigo.total_minor, indigo.invoice_date, indigo.extra["pnr"]) == (
        "indigo", 833300, date(2026, 6, 4), "YGDDKH",
    )
    (dtdc,) = june["DTDC_215.pdf"]
    assert (dtdc.vendor_key, dtdc.total_minor) == ("dtdc", 21501)
    (fathom,) = june["Fathom $36.pdf"]
    assert (fathom.vendor_key, fathom.currency, fathom.total_minor, fathom.invoice_date) == (
        "fathom", "USD", 3600, date(2026, 6, 20),
    )


@needs_june
def test_june_no_invoice_level_duplicates(june):
    rows = [
        {"vendor_key": i.vendor_key, "invoice_no": i.invoice_no, "total_minor": i.total_minor, "currency": i.currency}
        for items in june.values() for i in items
    ]
    assert duplicate_indexes(rows) == {}


@needs_june
def test_june_every_invoice_has_a_vendor_and_a_date_and_only_one_needs_a_check(june):
    everything = [(n, i) for n, items in june.items() for i in items]
    assert all(i.vendor_key for _, i in everything)
    assert all(i.invoice_date or i.order_date for _, i in everything)
    assert [n for n, i in everything if i.extraction_status == "needs_check"] == ["mailchimp-receipt-MC26118597.pdf"]
    assert collections.Counter(i.vendor_key for _, i in everything)["amazon"] == 62
