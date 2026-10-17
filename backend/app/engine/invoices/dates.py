"""Dates as they are printed on invoices. Day first for numeric dates (India)."""

import re
from datetime import date

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"

# 04/06/2026  04-06-2026  04.06.2026
NUMERIC = re.compile(r"(?<![\d.])(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)")
# 04-Jun-2026  4 Jun 2026  30 JUN 2026  16-Jun-26
DAY_MONTH = re.compile(rf"(?<!\d)(\d{{1,2}})[- ]({_MON})\.?[- ,]+(\d{{4}}|\d{{2}})(?!\d)", re.I)
# June 20, 2026  Jun 09, 2026  June 5, 2026
MONTH_DAY = re.compile(rf"(?<![A-Za-z])({_MON})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})(?!\d)", re.I)
# 2026-06-04
ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")


def _make(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_dates(text: str) -> list[tuple[int, date]]:
    """Every date in `text` as (position, date), in reading order."""
    found: list[tuple[int, date]] = []
    for m in NUMERIC.finditer(text):
        d = _make(int(m[3]), int(m[2]), int(m[1]))
        if d:
            found.append((m.start(), d))
    for m in DAY_MONTH.finditer(text):
        year = int(m[3])
        d = _make(year + 2000 if year < 100 else year, MONTHS[m[2][:3].lower()], int(m[1]))
        if d:
            found.append((m.start(), d))
    for m in MONTH_DAY.finditer(text):
        d = _make(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2]))
        if d:
            found.append((m.start(), d))
    for m in ISO.finditer(text):
        d = _make(int(m[1]), int(m[2]), int(m[3]))
        if d:
            found.append((m.start(), d))
    found.sort(key=lambda item: item[0])
    return found


def date_after_label(text: str, label: str, lines_ahead: int = 2) -> date | None:
    """The first date printed after `label` on the same line, or on one of the next lines.
    Some layouts put the value under the label (a table header), so the next lines count too."""
    rows = text.split("\n")
    for i, row in enumerate(rows):
        m = re.search(label, row, re.I)
        if not m:
            continue
        # Same line after the label first, then the lines below.
        chunk = row[m.end():] + "\n" + "\n".join(rows[i + 1 : i + 1 + lines_ahead])
        dates = find_dates(chunk)
        if dates:
            return dates[0][1]
    return None
