"""ICICI credit-card statement text -> transaction lines, header and summary figures, and the totals check.

Pure Python: it takes the text that `pdftotext -layout` produced and returns plain values. No database,
network or storage. Rewritten cleanly from doc/reference/parse_stmt.py; the rules are project_context.md 5.1:

* the `date + serial` pattern can sit anywhere in a line (page 1 has sidebar text to its left);
* a description can wrap onto the next line, and so can the currency code;
* a line like `4035XXXXXXXX4002` starts that card's section;
* credits end in ` CR`; serial numbers are unique;
* the sum of debits must equal Purchases/Charges + Cash Advances, and credits must equal
  Payments/Credits, to the paisa;
* pages that are bank boilerplate (example tables with amounts) are never read.

All money is integer paise. Foreign amounts are integer minor units (cents).
"""

import re
from dataclasses import dataclass
from datetime import date

from app.engine.money import format_inr, parse_minor, parse_paise  # noqa: F401 - re-exported for callers and tests

START = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(\d{10,12})\s")
ROW = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(\d{10,12})\s+(.*?)\s{2,}"  # date, serial, description
    r"(-?\d+)\s+"  # reward points (negative on credits)
    r"(?:(\d[\d,]*(?:\.\d+)?(?:\s*[A-Z]{3})?)\s+)?"  # optional foreign amount, with or without its currency
    r"([\d,]+\.\d\d)(\s*CR)?\s*$"  # amount in INR, CR marks a credit
)
CARD = re.compile(r"\d{4}X{8}(\d{4})")
RUPEE_AMOUNT = re.compile(r"[`₹]\s*([\d,]+\.\d\d)")
LONG_DATE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})")
PERIOD = re.compile(r"Statement\s+period\s*:\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})\s+to\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})", re.I)
CURRENCY_AT_END = re.compile(r"(?<![A-Za-z])([A-Z]{3})\s*$")
CURRENCIES = {
    "USD", "EUR", "GBP", "SGD", "AUD", "CAD", "AED", "JPY", "CHF", "HKD", "NZD", "SEK", "DKK",
    "NOK", "CNY", "THB", "MYR", "ZAR", "SAR", "QAR", "KRW", "IDR",
}
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}

# Fixed order of the summary row: Total due, Previous balance, Purchases/Charges, Cash advances, Payments/Credits.
SUMMARY_FIGURES = 5


@dataclass(frozen=True)
class StatementLine:
    sort_order: int
    txn_date: date
    ser_no: str
    description: str
    reward_points: int
    foreign_amount_minor: int | None
    foreign_currency: str | None
    amount_paise: int  # always positive; is_credit marks credits
    is_credit: bool
    card_last4: str | None


@dataclass(frozen=True)
class StatementCheck:
    """Lines read vs the totals the statement prints."""

    lines: int
    debits_paise: int
    credits_paise: int
    printed_debits_paise: int | None
    printed_credits_paise: int | None
    cards: tuple[str, ...]
    problems: tuple[str, ...]

    @property
    def debits_ok(self) -> bool:
        return self.printed_debits_paise is not None and self.debits_paise == self.printed_debits_paise

    @property
    def credits_ok(self) -> bool:
        return self.printed_credits_paise is not None and self.credits_paise == self.printed_credits_paise

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class ParsedStatement:
    statement_date: date | None
    period_start: date | None
    period_end: date | None
    total_due_paise: int | None
    previous_paise: int | None
    purchases_paise: int | None
    cash_advances_paise: int | None
    credits_paise: int | None
    lines: tuple[StatementLine, ...]
    unparsed: tuple[str, ...]  # `date serial ...` lines that could not be read

    @property
    def printed_debits_paise(self) -> int | None:
        """What the debit lines must add up to: Purchases/Charges plus Cash Advances (both printed)."""
        if self.purchases_paise is None:
            return None
        return self.purchases_paise + (self.cash_advances_paise or 0)

    @property
    def duplicate_serials(self) -> tuple[str, ...]:
        seen: set[str] = set()
        dupes: list[str] = []
        for line in self.lines:
            if line.ser_no in seen and line.ser_no not in dupes:
                dupes.append(line.ser_no)
            seen.add(line.ser_no)
        return tuple(dupes)

    def errors(self) -> tuple[str, ...]:
        """Reasons the lines can't be trusted at all (nothing should be saved)."""
        found: list[str] = []
        if not self.lines and not self.unparsed:
            found.append("No statement lines were found. This doesn't look like an ICICI card statement.")
        if self.unparsed:
            n = len(self.unparsed)
            found.append(f"{n} line{'s' if n != 1 else ''} could not be read, for example: {self.unparsed[0][:90]}")
        if self.duplicate_serials:
            found.append(f"The same serial number appears more than once: {', '.join(self.duplicate_serials[:5])}.")
        return tuple(found)

    def check(self) -> StatementCheck:
        return check_totals(
            line_count=len(self.lines),
            debits_paise=sum(x.amount_paise for x in self.lines if not x.is_credit),
            credits_paise=sum(x.amount_paise for x in self.lines if x.is_credit),
            printed_debits_paise=self.printed_debits_paise,
            printed_credits_paise=self.credits_paise,
            cards=[x.card_last4 for x in self.lines if x.card_last4],
        )


def check_totals(
    *,
    line_count: int,
    debits_paise: int,
    credits_paise: int,
    printed_debits_paise: int | None,
    printed_credits_paise: int | None,
    cards: list[str],
) -> StatementCheck:
    """The acceptance rule: debits = Purchases/Charges + Cash Advances and credits = Payments/Credits,
    to the paisa. `printed_debits_paise` is that printed sum (see `ParsedStatement.printed_debits_paise`)."""
    problems: list[str] = []
    if line_count == 0:
        problems.append("No statement lines were found.")
    if printed_debits_paise is None or printed_credits_paise is None:
        problems.append("The statement's printed totals (Purchases/Charges and Payments/Credits) were not found.")
    else:
        if debits_paise != printed_debits_paise:
            problems.append(
                f"Debits read from the lines ({format_inr(debits_paise)}) don't match the statement's "
                f"Purchases/Charges plus Cash Advances ({format_inr(printed_debits_paise)})."
            )
        if credits_paise != printed_credits_paise:
            problems.append(
                f"Credits read from the lines ({format_inr(credits_paise)}) don't match the statement's "
                f"Payments/Credits ({format_inr(printed_credits_paise)})."
            )
    return StatementCheck(
        lines=line_count,
        debits_paise=debits_paise,
        credits_paise=credits_paise,
        printed_debits_paise=printed_debits_paise,
        printed_credits_paise=printed_credits_paise,
        cards=tuple(sorted(set(cards))),
        problems=tuple(problems),
    )


MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December",
]


def statement_label(statement_date: date | None) -> str | None:
    """The cycle's name when nobody gave one: the statement's month, e.g. 'June 2026'."""
    if statement_date is None:
        return None
    return f"{MONTH_NAMES[statement_date.month - 1]} {statement_date.year}"


def parse_statement(text: str) -> ParsedStatement:
    """Read the whole `pdftotext -layout` text of a statement."""
    pages = text.replace("\r", "").split("\f")
    lines: list[StatementLine] = []
    unparsed: list[str] = []
    card: str | None = None

    for page in pages:
        # Only pages with the transaction table are read; the boilerplate pages are skipped.
        if "SerNo" not in page or "Transaction Details" not in page:
            continue
        rows = page.split("\n")
        for i, row in enumerate(rows):
            found = CARD.search(row)
            if found:
                card = found.group(1)
            start = START.search(row)
            if not start:
                continue
            col = start.start()
            full = row[col:].rstrip()
            match = ROW.match(full)
            k = 1
            while not match and k <= 3 and i + k < len(rows) and not START.search(rows[i + k]):
                extra = _tail(rows[i + k], col)
                if extra:
                    full = f"{full}  {extra}"
                match = ROW.match(full)
                k += 1
            if not match:
                unparsed.append(re.sub(r"\s+", " ", row[col:]).strip())
                continue

            day, ser_no, description, points, foreign, amount, credit = match.groups()
            amount_minor, currency = _foreign(foreign)
            if amount_minor is not None and currency is None:
                currency = _currency_below(rows, i, col)
            lines.append(
                StatementLine(
                    sort_order=len(lines),
                    txn_date=_slash_date(day),
                    ser_no=ser_no,
                    description=re.sub(r"\s+", " ", description).strip(),
                    reward_points=int(points),
                    foreign_amount_minor=amount_minor,
                    foreign_currency=currency,
                    amount_paise=parse_paise(amount),
                    is_credit=bool(credit),
                    card_last4=card,
                )
            )

    period_start, period_end = _period(text)
    figures = _summary_figures(text)
    return ParsedStatement(
        statement_date=_statement_date(text),
        period_start=period_start,
        period_end=period_end,
        total_due_paise=figures[0],
        previous_paise=figures[1],
        purchases_paise=figures[2],
        cash_advances_paise=figures[3],
        credits_paise=figures[4],
        lines=tuple(lines),
        unparsed=tuple(unparsed),
    )


# -- helpers ---------------------------------------------------------------------------------------
def _tail(row: str, col: int) -> str:
    """A continuation line without the page-1 sidebar text that sits to the left of the table."""
    return row[max(col - 2, 0):].strip()


def _slash_date(text: str) -> date:
    d, m, y = text.split("/")
    return date(int(y), int(m), int(d))


def _foreign(text: str | None) -> tuple[int | None, str | None]:
    if not text:
        return None, None
    found = re.match(r"([\d,]+(?:\.\d+)?)\s*([A-Z]{3})?$", text.strip())
    if not found:
        return None, None
    return parse_minor(found.group(1)), found.group(2)


def _currency_below(rows: list[str], i: int, col: int) -> str | None:
    """The currency code can wrap onto one of the next lines (86.12 / USD)."""
    for k in (1, 2, 3):
        if i + k >= len(rows) or START.search(rows[i + k]):
            return None
        found = CURRENCY_AT_END.search(_tail(rows[i + k], col))
        if found and found.group(1) in CURRENCIES:
            return found.group(1)
    return None


def _long_date(text: str) -> date | None:
    found = LONG_DATE.search(text)
    if not found:
        return None
    month = MONTHS.get(found.group(1).lower())
    if month is None:
        return None
    return date(int(found.group(3)), month, int(found.group(2)))


def _statement_date(text: str) -> date | None:
    rows = text.replace("\r", "").split("\n")
    for i, row in enumerate(rows):
        if "STATEMENT DATE" in row:
            for nxt in rows[i + 1 : i + 4]:  # the date is printed on a line below its heading
                found = _long_date(nxt)
                if found:
                    return found
    return None


def _period(text: str) -> tuple[date | None, date | None]:
    found = PERIOD.search(text)
    if not found:
        return None, None
    return _long_date(found.group(1)), _long_date(found.group(2))


def _summary_figures(text: str) -> list[int | None]:
    """Total due, Previous, Purchases, Cash advances, Payments: the first row under STATEMENT SUMMARY
    that carries five amounts (the rupee sign comes out of pdftotext as a backtick)."""
    rows = text.replace("\r", "").split("\n")
    for i, row in enumerate(rows):
        if "STATEMENT SUMMARY" not in row:
            continue
        for nxt in rows[i + 1 : i + 12]:
            amounts = RUPEE_AMOUNT.findall(nxt)
            if len(amounts) >= SUMMARY_FIGURES:
                return [parse_paise(a) for a in amounts[:SUMMARY_FIGURES]]
    return [None] * SUMMARY_FIGURES
