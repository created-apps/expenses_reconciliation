"""Statement parser: small synthetic cases for each gotcha, plus the real June statement.

The real-file tests need poppler's pdftotext and the git-ignored PDF in tests/fixtures_private/,
so they run in Docker (`docker compose run --rm tests`) and skip anywhere else.
"""

import shutil
from datetime import date
from pathlib import Path

import pytest

from app.engine.statement_icici import check_totals, format_inr, parse_paise, parse_statement, statement_label
from app.pdf import pdf_text

FIXTURES = Path(__file__).parent / "fixtures_private"
found = sorted(FIXTURES.glob("CC*June*2026*.pdf"))
STATEMENT = found[0] if found else None
needs_june = pytest.mark.skipif(
    STATEMENT is None or shutil.which("pdftotext") is None,
    reason="June statement or pdftotext (poppler) missing; run in Docker",
)

# ---- Synthetic snippets (made-up values, only the layout matters) ----------------------------------
HEADER = "Date        SerNo.      Transaction Details       Reward Points   Intl.# amount   Amount (in`)"


def page(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


def test_a_plain_line_and_a_credit():
    parsed = parse_statement(
        page(
            "0000XXXXXXXX1111",
            "05/01/2026   10000000001   SHOP ONE MUMBAI IN                    12                         1,234.50",
            "06/01/2026   10000000002   SHOP ONE MUMBAI IN                   -12                           100.00 CR",
        )
    )
    debit, credit = parsed.lines
    assert (debit.txn_date, debit.ser_no, debit.amount_paise, debit.is_credit) == (date(2026, 1, 5), "10000000001", 123450, False)
    assert (credit.amount_paise, credit.is_credit, credit.reward_points) == (10000, True, -12)
    assert debit.card_last4 == credit.card_last4 == "1111"
    assert debit.description == "SHOP ONE MUMBAI IN"


def test_the_date_and_serial_can_sit_in_the_middle_of_a_line():
    # Page 1 has sidebar text to the left of the table.
    parsed = parse_statement(
        page("Get some cashback and   27/05/2026 13488732741 OPENAI *THING                 33                1,694.07")
    )
    (line,) = parsed.lines
    assert line.ser_no == "13488732741" and line.amount_paise == 169407
    assert line.description == "OPENAI *THING"


def test_a_description_that_wraps_onto_the_next_line():
    parsed = parse_statement(
        page(
            "                                  27/05/2026  13488732741  OPENAI *CHATGPT SUBSCR OPENAI.COM",
            "                                                           US",
            "                                                                                   33                 1,694.07",
        )
    )
    (line,) = parsed.lines
    assert line.description == "OPENAI *CHATGPT SUBSCR OPENAI.COM US"
    assert line.amount_paise == 169407 and parsed.unparsed == ()


def test_the_sidebar_beside_a_wrapped_line_is_not_added_to_the_description():
    parsed = parse_statement(
        page(
            "                       27/05/2026  13488732741  OPENAI *THING",
            "  savings of 1%                           US",
            "                                                       33                 1,694.07",
        )
    )
    assert parsed.lines[0].description == "OPENAI *THING US"


def test_the_currency_code_can_wrap_onto_the_next_line():
    parsed = parse_statement(
        page(
            "21/05/2026   13463193979   SUPABASE SINGAPORE SG*          167      86.12            8,695.94",
            "                                                                     USD",
            "22/05/2026   13463194859   NEXT VENDOR                       5                       100.00",
        )
    )
    first, second = parsed.lines
    assert (first.foreign_amount_minor, first.foreign_currency, first.amount_paise) == (8612, "USD", 869594)
    assert second.foreign_amount_minor is None and second.foreign_currency is None


def test_a_foreign_amount_with_its_currency_on_the_same_line_and_with_commas():
    parsed = parse_statement(
        page(
            "21/05/2026   13463194859   FATHOM.VIDEO US*                 69      36 USD          3,635.09",
            "21/05/2026   13463194860   BIG VENDOR US*                   69      1,234.5 USD     99,999.00",
        )
    )
    a, b = parsed.lines
    assert (a.foreign_amount_minor, a.foreign_currency) == (3600, "USD")
    assert (b.foreign_amount_minor, b.foreign_currency, b.amount_paise) == (123450, "USD", 9999900)


def test_the_card_changes_when_a_new_card_section_starts():
    parsed = parse_statement(
        page(
            "0000XXXXXXXX2492",
            "11/06/2026   13576983915   Late Payment Fee                  0                          1,300.00",
            "4035XXXXXXXX4002",
            "21/05/2026   13462021874   ASSPL Bangalore IN               24                          1,225.50",
        )
    )
    assert [x.card_last4 for x in parsed.lines] == ["2492", "4002"]
    assert parsed.check().cards == ("2492", "4002")


def test_pages_without_the_transaction_table_are_ignored():
    boilerplate = "Example: on 01/01/2026 10000000009 you spent    5     500.00\nNo table header here"
    parsed = parse_statement(page("05/01/2026   10000000001   SHOP IN    1     100.00") + "\f" + boilerplate)
    assert [x.ser_no for x in parsed.lines] == ["10000000001"]


def test_a_line_that_cannot_be_read_is_reported_not_dropped_silently():
    parsed = parse_statement(page("05/01/2026   10000000001   BROKEN LINE WITH NO AMOUNT"))
    assert parsed.lines == () and len(parsed.unparsed) == 1
    assert parsed.errors() and "could not be read" in parsed.errors()[0]


def test_text_with_no_lines_is_rejected_with_a_clear_message():
    parsed = parse_statement("Tax invoice\nTotal 1,000.00")
    assert parsed.lines == ()
    assert "doesn't look like an ICICI card statement" in parsed.errors()[0]
    check = parsed.check()
    assert not check.ok and parsed.statement_date is None and parsed.purchases_paise is None


def test_a_repeated_serial_number_is_an_error():
    row = "05/01/2026   10000000001   SHOP IN    1     100.00"
    assert parse_statement(page(row, row)).duplicate_serials == ("10000000001",)
    assert parse_statement(page(row, row)).errors()


def test_totals_must_match_to_the_paisa():
    ok = check_totals(line_count=2, debits_paise=100, credits_paise=40, printed_debits_paise=100,
                      printed_credits_paise=40, cards=["4002", "2492", "4002"])
    assert ok.ok and ok.debits_ok and ok.credits_ok and ok.cards == ("2492", "4002")
    off = check_totals(line_count=2, debits_paise=101, credits_paise=40, printed_debits_paise=100,
                       printed_credits_paise=40, cards=[])
    assert not off.ok and not off.debits_ok and off.credits_ok
    assert "₹1.01" in off.problems[0] and "₹1.00" in off.problems[0]
    missing = check_totals(line_count=2, debits_paise=1, credits_paise=0, printed_debits_paise=None,
                           printed_credits_paise=None, cards=[])
    assert not missing.ok and "not found" in missing.problems[0]


SUMMARY = "STATEMENT SUMMARY\n   `{total}     `{previous}     `{purchases}     `{cash}     `{credits}\n"


def statement_with_cash(*, purchases: str, cash: str) -> str:
    return SUMMARY.format(total="9,999.00", previous="1.00", purchases=purchases, cash=cash, credits="50.00") + page(
        "05/01/2026   10000000001   SHOP ONE MUMBAI IN     1     100.00",
        "06/01/2026   10000000002   ATM CASH WITHDRAWAL    0     250.00",
        "07/01/2026   10000000003   REFUND SHOP            0      50.00 CR",
    )


def test_debits_are_checked_against_purchases_plus_cash_advances():
    # Purchases 100.00 + Cash Advances 250.00 = the 350.00 of debit lines.
    parsed = parse_statement(statement_with_cash(purchases="100.00", cash="250.00"))
    assert (parsed.purchases_paise, parsed.cash_advances_paise) == (10000, 25000)
    assert parsed.printed_debits_paise == 35000
    check = parsed.check()
    assert check.ok and check.debits_paise == 35000 and check.printed_debits_paise == 35000


def test_leaving_out_the_cash_advance_makes_the_check_fail():
    # The same lines against Purchases alone would be wrong by the cash advance.
    parsed = parse_statement(statement_with_cash(purchases="100.00", cash="0.00"))
    check = parsed.check()
    assert not check.ok and not check.debits_ok
    assert "Cash Advances" in check.problems[0]


def test_statement_label_is_the_month_and_year():
    assert statement_label(date(2026, 6, 28)) == "June 2026"
    assert statement_label(date(2027, 1, 3)) == "January 2027"
    assert statement_label(None) is None


def test_money_helpers():
    assert parse_paise("1,05,980.00") == 10598000 and parse_paise("0.05") == 5 and parse_paise("12") == 1200
    assert format_inr(131610704) == "₹13,16,107.04" and format_inr(-5598560) == "-₹55,985.60"
    assert format_inr(99) == "₹0.99" and format_inr(100000) == "₹1,000.00"


# ---- The real June statement ------------------------------------------------------------------------
@pytest.fixture(scope="module")
def june():
    return parse_statement(pdf_text(STATEMENT.read_bytes(), last_page=None, timeout=60))


@needs_june
def test_june_header_and_printed_figures(june):
    assert june.statement_date == date(2026, 6, 28)
    assert (june.period_start, june.period_end) == (date(2026, 5, 21), date(2026, 6, 28))
    assert june.total_due_paise == 177453261
    assert june.previous_paise == 104949199
    assert june.purchases_paise == 131610704
    assert june.cash_advances_paise == 0
    assert june.credits_paise == 59106642


@needs_june
def test_june_127_lines_and_the_totals_match_to_the_paisa(june):
    assert june.unparsed == () and june.errors() == ()
    check = june.check()
    assert check.lines == 127
    assert len({x.ser_no for x in june.lines}) == 127
    assert check.debits_paise == 131610704 and check.debits_ok
    assert check.credits_paise == 59106642 and check.credits_ok
    assert check.ok and check.cards == ("2492", "4002")
    assert sum(1 for x in june.lines if not x.is_credit) == 118 and sum(1 for x in june.lines if x.is_credit) == 9
    assert sum(1 for x in june.lines if x.card_last4 == "4002") == 121
    assert sum(1 for x in june.lines if x.card_last4 == "2492") == 6


@needs_june
def test_june_known_lines(june):
    by_ser = {x.ser_no: x for x in june.lines}
    # Sidebar text on the same line and a wrapped description (5.4).
    openai = by_ser["13488732741"]
    assert openai.txn_date == date(2026, 5, 27)
    assert openai.description == "OPENAI *CHATGPT SUBSCR OPENAI.COM US" and openai.amount_paise == 169407
    # A bank charge on the second card (5.5).
    sgst = by_ser["13576983923"]
    assert (sgst.txn_date, sgst.description, sgst.amount_paise, sgst.card_last4) == (date(2026, 6, 11), "SGST-CI@9%", 11700, "2492")
    # The currency code on the next line (5.6).
    supabase = by_ser["13463193979"]
    assert supabase.description == "SUPABASE SINGAPORE SG*"
    assert (supabase.foreign_amount_minor, supabase.foreign_currency, supabase.amount_paise) == (8612, "USD", 869594)
    # A credit (5.7).
    credit = by_ser["13592897886"]
    assert (credit.description, credit.amount_paise, credit.is_credit) == ("ASSPL Bangalore IN", 5299000, True)
    # A whole-dollar amount printed with its currency on the same line.
    fathom = by_ser["13463194859"]
    assert (fathom.foreign_amount_minor, fathom.foreign_currency, fathom.amount_paise) == (3600, "USD", 363509)
    # The payment.
    payment = by_ser["13578455906"]
    assert payment.is_credit and payment.amount_paise == 6047200 and "PAYMENT RECEIVED" in payment.description


@needs_june
def test_june_every_foreign_line_has_a_currency(june):
    foreign = [x for x in june.lines if x.foreign_amount_minor is not None]
    assert foreign and all(x.foreign_currency for x in foreign)
