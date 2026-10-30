"""Amazon orders that still have no invoice: the list a person works from, and how well the uploaded invoices
cover the Amazon Business report.

Pure Python (no database, network or clock). The report says which orders each card payment paid; the
uploaded invoices say which orders have a file. The charge a payment group belongs to is chosen by the same
functions the matcher uses (`candidate_groups`, `pick_equal_group`), walking the lines in the same order, so
this list can never disagree with the "Missing invoice" notes that matching wrote.

Money is integer paise. Only a *missing order* is listed; an order that has an invoice covering only part of
its amount is counted (`partly_invoiced`) but not listed.
"""

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.engine.amazon_csv import AmazonRow
from app.engine.matcher import CsvReport, Txn, candidate_groups, pick_equal_group


@dataclass(frozen=True)
class FetchOrder:
    """One Amazon order to fetch an invoice for, and the statement charge it was paid in."""

    order_id: str
    payment_date: date | None
    amount_paise: int  # the order's total in the report (sum of its Net totals)
    group_reference: str  # the report's Payment Reference ID
    txn_id: str
    ser_no: str
    charge_date: date
    charge_amount_paise: int
    description: str


@dataclass(frozen=True)
class Coverage:
    """How the uploaded invoices cover the whole report (not only the charges on one statement)."""

    card_orders: int  # distinct orders paid by card
    with_invoice: int  # ... that have an invoice file with their Order ID
    without_invoice: int  # ... that have none
    partly_invoiced: int  # of those with an invoice: the invoices add up to less than the order
    gift_orders: int  # paid from the gift balance (never on the card)
    gift_with_invoice: int  # ... that have an invoice file


def order_amounts(rows: Iterable[AmazonRow]) -> dict[tuple[str, str], int]:
    """(Payment Reference ID, Order ID) -> the order's Net totals added up, for card-paid rows."""
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        if r.is_card and r.payment_ref and r.order_id:
            totals[(r.payment_ref, r.order_id)] += r.net_total_paise
    return dict(totals)


def orders_to_fetch(
    lines: Sequence[Txn],
    report: CsvReport,
    amounts: Mapping[tuple[str, str], int],
    invoiced: Collection[str],
) -> list[FetchOrder]:
    """Orders of the report groups that pay these debits and have no invoice (`invoiced` = Order IDs that do).

    `lines` are the Amazon debits matching decided by the report, in statement order: not credits, not lines
    decided by rules 1 to 4 (reversals, fees, payments), not lines a person changed. Each line takes its
    group exactly as the matcher does, so a group is never listed for two lines.
    """
    used: set[str] = set()
    found: list[FetchOrder] = []
    covered = [t for t in sorted(lines, key=lambda x: (x.date, x.amount_paise)) if report.covers(t.date)]  # the matcher's order
    # The matcher gives every exact group to its charge first; a near miss can only take a group that is left over,
    # and lists nothing, so only the exact pass matters here.
    for t in covered:
        group = pick_equal_group(t, candidate_groups(t, report.groups, used))
        if group is None:
            continue
        used.add(group.reference)
        for order in group.order_ids:
            if order not in invoiced:
                found.append(FetchOrder(
                    order_id=order, payment_date=group.payment_date,
                    amount_paise=amounts.get((group.reference, order), 0), group_reference=group.reference,
                    txn_id=t.id, ser_no=t.ser_no, charge_date=t.date, charge_amount_paise=t.amount_paise,
                    description=t.description,
                ))
    return found


def report_coverage(rows: Iterable[AmazonRow], invoice_totals: Mapping[str, int]) -> Coverage:
    """How many of the report's orders have an invoice. `invoice_totals` maps an Order ID to the INR total of
    its uploaded invoices (an order that has any invoice is a key)."""
    rows = list(rows)
    net: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.is_card and r.order_id:
            net[r.order_id] += r.net_total_paise
    have = [o for o in net if o in invoice_totals]
    gift = {r.order_id for r in rows if r.is_gift and r.order_id}
    return Coverage(
        card_orders=len(net),
        with_invoice=len(have),
        without_invoice=len(net) - len(have),
        partly_invoiced=sum(1 for o in have if invoice_totals[o] < net[o]),
        gift_orders=len(gift),
        gift_with_invoice=sum(1 for o in gift if o in invoice_totals),
    )
