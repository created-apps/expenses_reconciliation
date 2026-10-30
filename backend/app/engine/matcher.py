"""Match statement lines to invoices: rules 1 to 10 of project_context.md section 8, in that order.

Pure Python: no database, no network, no clock. Everything is passed in (lines, invoices, vendors, the
optional Amazon report, the lines a person already decided) and a decision comes back for every line.
The AI never reaches this module: invoices arrive as plain values.

All money is integer paise (INR) or cents (USD). Statuses are the eight in the database.

Order of work (a line takes the first rule that applies):
  1. bank charges and 2. payments, 3. reversal pairs, 4. other credits;
  5. Amazon (the Amazon report's payment groups when the debit is inside its payment-date range,
     otherwise sums of invoices in the date window), 6. IndiGo (sums of invoices, one PNR preferred);
  7. every other vendor, assigned globally by (rank, date gap); then invoices with no recognised vendor, on
     exact amount and date alone (one line, one invoice: Matched; shared: Review);
  8. near misses (a USD-only invoice, same-day Amazon credits, within 5%, a possible duplicate charge);
  9. no vendor -> No invoice, 10. otherwise -> Missing invoice.
A suggestion (Review) reserves its invoices so no other line is offered the same ones.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.engine.money import format_inr
from app.engine.subsets import SearchTooLarge, closest_subset, exact_subsets

# -- statuses ----------------------------------------------------------------------------------------------
MATCHED = "Matched"
REVIEW = "Review"
MISSING = "Missing invoice"
NO_INVOICE = "No invoice"
REVERSED = "Reversed"
CREDIT = "Credit – manual"
PAYMENT = "Payment"
BANK_CHARGE = "Bank charge"

BANK_CHARGE_START = re.compile(r"^(DCC Fee|SGST-CI|CGST-CI|Late Payment Fee|Interest Charges)", re.I)
REVERSAL_DAYS = 7
NEAR_MISS_DAYS = 7  # rule 8: "within 7 days"
NEAR_MISS_PERCENT = 5
PNR_PREFERRED = "indigo"
AMAZON = "amazon"
CSV_DAYS = 3  # rule 5: a CSV group's payment date is within 3 days of the charge


# -- inputs --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Txn:
    id: str
    ser_no: str
    date: date
    description: str
    amount_paise: int  # always positive; is_credit marks credits
    is_credit: bool
    card_last4: str | None = None
    foreign_amount_minor: int | None = None
    foreign_currency: str | None = None


@dataclass(frozen=True)
class Inv:
    id: str
    vendor_key: str | None
    currency: str  # INR | USD
    total_minor: int | None
    amounts_minor: tuple[int, ...] = ()  # every amount the invoice shows, in its own currency
    invoice_date: date | None = None
    order_date: date | None = None
    order_id: str | None = None
    is_credit_note: bool = False
    duplicate_of: str | None = None
    pnr: str | None = None
    usd_amounts_minor: tuple[int, ...] = ()  # USD amounts shown on an INR invoice


@dataclass(frozen=True)
class Vendor:
    key: str
    display_name: str
    statement_pattern: str | None
    match_mode: str  # single | subset | none
    before_days: int = 7
    after_days: int = 7


@dataclass(frozen=True)
class CsvGroup:
    """One card charge in the Amazon Business report (rows sharing a Payment Reference ID)."""

    reference: str
    payment_date: date | None
    card_last4: str | None
    order_ids: tuple[str, ...]
    amount_paise: int

    @property
    def orders(self) -> int:
        return len(self.order_ids)

    def orders_text(self) -> str:
        return f"{self.orders} order{'s' if self.orders != 1 else ''}"


@dataclass(frozen=True)
class CsvReport:
    payment_from: date
    payment_to: date
    groups: tuple[CsvGroup, ...]

    def covers(self, day: date) -> bool:
        return self.payment_from <= day <= self.payment_to


@dataclass(frozen=True)
class Pinned:
    """A line a person has decided: the matcher leaves it alone and treats its invoices as used."""

    ser_no: str
    invoice_ids: tuple[str, ...] = ()


# -- output ----------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Link:
    invoice_id: str
    rule: str
    is_suggestion: bool = False


@dataclass
class LineResult:
    txn_id: str
    ser_no: str
    status: str | None  # None for a pinned line (left as it is)
    vendor_key: str | None = None
    note: str = ""
    links: list[Link] = field(default_factory=list)
    missing_orders: tuple[str, ...] = ()  # Amazon report orders that have no invoice
    pinned: bool = False


# -- helpers -----------------------------------------------------------------------------------------------------
def _day(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "?"


def _usd(minor: int) -> str:
    whole, cents = divmod(minor, 100)
    if cents == 0:
        return str(whole)
    return f"{whole}.{cents // 10}" if cents % 10 == 0 else f"{whole}.{cents:02d}"


def _merchant_key(description: str) -> str:
    return re.sub(r"\s+", " ", description.upper())[:18]


def _inv_date(inv: Inv) -> date | None:
    """The date an invoice is placed by in the window: the order date, else the invoice date."""
    return inv.order_date or inv.invoice_date


def _candidate_amounts(inv: Inv) -> set[int]:
    values = set(inv.amounts_minor)
    if inv.total_minor is not None:
        values.add(inv.total_minor)
    return values


def vendor_for_line(description: str, vendors: Iterable[Vendor]) -> Vendor | None:
    """The vendor whose statement pattern appears first in the description (ties: the table's order)."""
    best: tuple[int, int, Vendor] | None = None
    for order, vendor in enumerate(vendors):
        if not vendor.statement_pattern:
            continue
        try:
            found = re.search(vendor.statement_pattern, description, re.I)
        except re.error:
            continue  # a bad pattern in the vendor table must not stop the others
        if found and (best is None or (found.start(), order) < (best[0], best[1])):
            best = (found.start(), order, vendor)
    return best[2] if best else None


def candidate_groups(t: Txn, groups: Iterable[CsvGroup], used: set[str]) -> list[CsvGroup]:
    """Report groups that could pay this debit: not used by another line, the same card, and a payment date
    within CSV_DAYS of the charge. Shared with the "Amazon invoices to fetch" list so both always agree."""
    return [
        g for g in groups
        if g.reference not in used and g.card_last4 is not None and g.card_last4 == t.card_last4
        and g.payment_date is not None and abs((t.date - g.payment_date).days) <= CSV_DAYS
    ]


def pick_equal_group(t: Txn, candidates: Sequence[CsvGroup]) -> CsvGroup | None:
    """The candidate group whose amount equals the charge (nearest payment date first), or None."""
    equal = [g for g in candidates if g.amount_paise == t.amount_paise]
    if not equal:
        return None
    return min(equal, key=lambda g: (abs((t.date - g.payment_date).days), g.payment_date, g.reference))


def pick_near_group(t: Txn, candidates: Sequence[CsvGroup]) -> CsvGroup | None:
    """When no group equals the charge: the closest group within NEAR_MISS_PERCENT of it, or None."""
    near = [g for g in candidates if abs(g.amount_paise - t.amount_paise) * 100 <= NEAR_MISS_PERCENT * t.amount_paise]
    if not near:
        return None
    return min(near, key=lambda g: (abs(g.amount_paise - t.amount_paise), g.payment_date, g.reference))


class _NoVendor:
    """Stands in for 'no vendor' so `.key` can always be read."""

    key = None


_NONE = _NoVendor()


@dataclass(frozen=True)
class _Pair:
    """A line that could take an invoice (rule 7), with how good the fit is."""

    rank: int  # 0 exact or USD, 1 within Rs 1
    gap: int  # days between the line and the invoice
    ser_no: str
    index: int  # the invoice's position in the input
    txn: Txn
    invoice: Inv
    note: str
    rule: str

    def order(self) -> tuple[int, int, str, int]:
        return self.rank, self.gap, self.ser_no, self.index


class _Matcher:
    def __init__(self, txns: Sequence[Txn], invoices: Sequence[Inv], vendors: Sequence[Vendor],
                 csv: CsvReport | None, pinned: Sequence[Pinned]):
        self.txns = list(txns)
        self.invoices = list(invoices)
        self.vendors = {v.key: v for v in vendors}
        self.vendor_list = list(vendors)
        self.csv = csv
        self.results: dict[str, LineResult] = {}
        self.used: set[str] = set()
        self.used_groups: set[str] = set()
        self.vendor_of: dict[str, Vendor | None] = {t.id: vendor_for_line(t.description, vendors) for t in txns}
        self.pinned_serials = {p.ser_no for p in pinned}
        for p in pinned:
            self.used.update(p.invoice_ids)
        dates = [d for inv in invoices if not inv.duplicate_of for d in (inv.order_date, inv.invoice_date) if d]
        self.earliest_invoice = min(dates) if dates else None

    # ---- bookkeeping ---------------------------------------------------------------------------------------
    def open_lines(self) -> list[Txn]:
        return [t for t in self.txns if t.id not in self.results]

    def set(self, t: Txn, status: str, note: str, links: Iterable[Link] = (), missing: Iterable[str] = ()) -> None:
        vendor = self.vendor_of[t.id]
        self.results[t.id] = LineResult(
            txn_id=t.id, ser_no=t.ser_no, status=status, vendor_key=vendor.key if vendor else None,
            note=note, links=list(links), missing_orders=tuple(missing),
        )
        for link in links:
            self.used.add(link.invoice_id)

    def free(self, inv: Inv, vendor_key: str | None) -> bool:
        """Can this invoice still be given to a line of this vendor?"""
        return (
            inv.vendor_key == vendor_key
            and inv.id not in self.used
            and not inv.duplicate_of
            and not inv.is_credit_note
        )

    def has_own_match(self, t: Txn) -> bool:
        """Does this debit have an exact invoice (or exact report group) of its own? Used before any line has been
        decided, so a refund of the same amount does not take a real purchase for a reversed one."""
        vendor = self.vendor_of[t.id]
        if vendor is None or vendor.match_mode == "none":
            return False
        if vendor.key == AMAZON and self.csv is not None and self.csv.covers(t.date):
            return pick_equal_group(t, candidate_groups(t, self.csv.groups, set())) is not None
        if vendor.match_mode == "subset":
            pool = self.pool(t, vendor)
            try:
                return bool(pool) and bool(exact_subsets([inv.total_minor or 0 for inv in pool], t.amount_paise, max_size=12))
            except SearchTooLarge:
                return False
        low, high = t.date - timedelta(days=vendor.before_days), t.date + timedelta(days=vendor.after_days)
        for inv in self.invoices:
            if not self.free(inv, vendor.key):
                continue
            dates = [d for d in (inv.invoice_date, inv.order_date) if d]
            if dates and not any(low <= d <= high for d in dates):
                continue
            hit = self.amount_hit(t, inv)
            if hit and hit[0] == 0:
                return True
        return False

    # ---- rules 1 to 4 --------------------------------------------------------------------------------------
    def rules_1_to_4(self) -> None:
        for t in self.txns:
            if t.ser_no in self.pinned_serials:
                self.results[t.id] = LineResult(t.id, t.ser_no, None, pinned=True)
            elif BANK_CHARGE_START.match(t.description):
                self.set(t, BANK_CHARGE, "Card fee or GST on a fee; no vendor invoice.")
            elif "PAYMENT RECEIVED" in t.description.upper():
                self.set(t, PAYMENT, "Card bill payment")

        # 3. A credit cancels an EARLIER (or same-day) debit of the same merchant and amount, at most 7 days before it.
        #    A credit never reverses a later charge. A charge that has its own exact invoice or report group is a real
        #    purchase and is not cancelled by a refund of the same amount; of several candidates the nearest date wins.
        for credit in [t for t in self.txns if t.is_credit and t.id not in self.results]:
            candidates = [
                debit for debit in self.txns
                if not debit.is_credit
                and debit.id not in self.results
                and _merchant_key(debit.description) == _merchant_key(credit.description)
                and debit.amount_paise == credit.amount_paise
                and 0 <= (credit.date - debit.date).days <= REVERSAL_DAYS
                and not self.has_own_match(debit)
            ]
            if candidates:
                debit = min(candidates, key=lambda d: ((credit.date - d.date).days, d.ser_no))
                self.set(debit, REVERSED,
                         f"Reversed by credit on {_day(credit.date)} (SerNo {credit.ser_no}); no invoice needed")
                self.set(credit, REVERSED, f"Reverses the charge on {_day(debit.date)} (SerNo {debit.ser_no})")

        # 4. Every other credit is handled by a person.
        for t in self.open_lines():
            if t.is_credit:
                self.set(t, CREDIT, "Refund or credit; handled manually by the client")

    # ---- rule 5 (Amazon) and rule 6 (IndiGo): sums of invoices ----------------------------------------------
    def subset_vendors(self) -> None:
        for vendor in sorted((v for v in self.vendor_list if v.match_mode == "subset"), key=lambda v: v.key):
            lines = [t for t in self.open_lines() if (self.vendor_of[t.id] or _NONE).key == vendor.key]
            lines.sort(key=lambda t: (t.date, t.amount_paise))
            if vendor.key == AMAZON and self.csv is not None:
                csv_lines = [t for t in lines if self.csv.covers(t.date)]
                # Every exact group goes to its charge first; only then may a near miss take a group that is left.
                for t in csv_lines:
                    self.amazon_csv_line(t)
                for t in csv_lines:
                    if t.id not in self.results:
                        self.amazon_csv_near_line(t)
                lines = [t for t in lines if t.id not in self.results]
            for pass_no in (1, 2):  # pass 1: one invoice of the exact amount; pass 2: sums of up to 12
                for t in lines:
                    if t.id in self.results:
                        continue
                    self.subset_line(t, vendor, pass_no)

    def pool(self, t: Txn, vendor: Vendor) -> list[Inv]:
        low, high = t.date - timedelta(days=vendor.before_days), t.date + timedelta(days=vendor.after_days)
        return [
            inv for inv in self.invoices
            if self.free(inv, vendor.key) and inv.currency == "INR" and (inv.total_minor or 0) > 0
            and (d := _inv_date(inv)) is not None and low <= d <= high
        ]

    def subset_line(self, t: Txn, vendor: Vendor, pass_no: int) -> None:
        pool = self.pool(t, vendor)
        if not pool:
            return
        try:
            found = exact_subsets([inv.total_minor or 0 for inv in pool], t.amount_paise,
                                  max_size=1 if pass_no == 1 else 12)
        except SearchTooLarge:
            self.set(t, REVIEW, "Too many invoice combinations to check automatically; match this line by hand.")
            return
        solutions = [tuple(pool[i] for i in combo) for combo in found]
        if not solutions:
            return
        if vendor.key == PNR_PREFERRED:  # prefer invoices of a single PNR
            single = [s for s in solutions if len({inv.pnr for inv in s}) == 1]
            solutions = single or solutions
        rule = f"{vendor.key}_{'single' if len(solutions[0]) == 1 else 'subset'}"
        if len(solutions) > 1 and vendor.key == AMAZON:
            # Prefer sums that keep all invoices of an order together, then the closest dates.
            def score(s: tuple[Inv, ...]) -> tuple[int, int]:
                orders = {inv.order_id or inv.id for inv in s}
                split = sum(1 for inv in pool if (inv.order_id or inv.id) in orders and inv not in s)
                return split, sum(abs((t.date - (_inv_date(inv) or t.date)).days) for inv in s)

            solutions.sort(key=score)
            if score(solutions[0]) == score(solutions[1]):
                self.suggest(t, solutions[0], f"{len(solutions)} invoice combinations add up to this amount", rule)
                return
        elif len(solutions) > 1:
            self.suggest(t, solutions[0], f"{len(solutions)} invoice combinations add up to this amount", rule)
            return
        chosen = solutions[0]
        note = "Exact amount" if len(chosen) == 1 else f"{len(chosen)} invoices sum exactly to the charge"
        self.set(t, MATCHED, note, [Link(inv.id, rule) for inv in chosen])

    def suggest(self, t: Txn, invoices: Iterable[Inv], note: str, rule: str) -> None:
        self.set(t, REVIEW, note, [Link(inv.id, rule, is_suggestion=True) for inv in invoices])

    # ---- rule 5, report mode ----------------------------------------------------------------------------------
    def csv_groups_for(self, t: Txn) -> list[CsvGroup]:
        assert self.csv is not None
        return candidate_groups(t, self.csv.groups, self.used_groups)

    def group_invoices(self, group: CsvGroup) -> list[Inv]:
        orders = set(group.order_ids)
        return [
            inv for inv in self.invoices
            if inv.order_id in orders and inv.id not in self.used and not inv.duplicate_of and not inv.is_credit_note
        ]

    def amazon_csv_line(self, t: Txn) -> None:
        """A debit inside the report's payment-date range: only the report's groups are used, never the
        invoice-only method. This pass takes exact groups only; amazon_csv_near_line handles the rest."""
        group = pick_equal_group(t, self.csv_groups_for(t))
        if group is not None:
            self.used_groups.add(group.reference)
            attached = self.group_invoices(group)
            have = {inv.order_id for inv in attached}
            missing = sorted(o for o in group.order_ids if o not in have)
            total = sum(inv.total_minor or 0 for inv in attached if inv.currency == "INR")
            links = [Link(inv.id, "amazon_csv") for inv in attached]
            if not missing and total == t.amount_paise:
                self.set(t, MATCHED, f"Amazon report group {group.reference}: {group.orders_text()} paid on "
                         f"{_day(group.payment_date)}; its invoices add up to the charge", links)
            else:
                detail = f"orders without an invoice: {', '.join(missing)}" if missing else \
                    f"the invoices add up to {format_inr(total)}"
                self.set(t, MISSING, f"Amazon report group {group.reference} ({_day(group.payment_date)}) equals the "
                         f"charge, but {detail}.", links, missing)

    def amazon_csv_near_line(self, t: Txn) -> None:
        """No group equals the charge: only the near-miss rule applies, against the groups no charge has taken."""
        groups = self.csv_groups_for(t)
        group = pick_near_group(t, groups)
        if group is not None:
            self.used_groups.add(group.reference)
            attached = self.group_invoices(group)
            self.set(t, REVIEW, f"No Amazon report group equals this charge; group {group.reference} "
                     f"({format_inr(group.amount_paise)}, {_day(group.payment_date)}) is within {NEAR_MISS_PERCENT}%.",
                     [Link(inv.id, "amazon_csv_near", is_suggestion=True) for inv in attached])
            return
        nearest = min(groups, key=lambda g: abs(g.amount_paise - t.amount_paise), default=None)
        hint = f" (nearest group {format_inr(nearest.amount_paise)})" if nearest else ""
        self.set(t, MISSING, f"No group in the Amazon report equals this charge{hint}.")

    # ---- rule 7: every other vendor, assigned globally ---------------------------------------------------------
    def other_vendors(self) -> None:
        pairs: list[_Pair] = []
        for t in self.open_lines():
            vendor = self.vendor_of[t.id]
            if vendor is None or vendor.match_mode != "single":
                continue
            low, high = t.date - timedelta(days=vendor.before_days), t.date + timedelta(days=vendor.after_days)
            for index, inv in enumerate(self.invoices):
                if not self.free(inv, vendor.key):
                    continue
                dates = [d for d in (inv.invoice_date, inv.order_date) if d]
                gap = min((abs((t.date - d).days) for d in dates), default=None)
                if dates and not any(low <= d <= high for d in dates):
                    continue  # an invoice with a date must be inside the window
                hit = self.amount_hit(t, inv)
                if hit:
                    rank, note, rule = hit
                    pairs.append(_Pair(rank, gap if gap is not None else 5, t.ser_no, index, t, inv, note, rule))
        for pair in sorted(pairs, key=_Pair.order):
            if pair.txn.id in self.results or pair.invoice.id in self.used:
                continue
            self.set(pair.txn, MATCHED, pair.note, [Link(pair.invoice.id, pair.rule)])

    # ---- rule 7, second part: invoices no vendor was found for, matched on amount and date ---------------------------
    def amount_led(self) -> None:
        """An invoice with no vendor (or an unrecognised one) is tried against the lines still open: the invoice's
        total must equal the charge exactly (INR, or USD against the statement's foreign amount) and its date must be
        inside the rule 7 window. One line and one invoice that fit only each other are Matched, the merchant being
        taken from the line. Anything shared is a Review, never a guess."""
        invoices = [
            (index, inv) for index, inv in enumerate(self.invoices)
            if inv.vendor_key is None and inv.id not in self.used and not inv.duplicate_of
            and not inv.is_credit_note and inv.total_minor
        ]
        lines = [
            t for t in self.open_lines()
            if not t.is_credit and ((v := self.vendor_of[t.id]) is None or v.match_mode == "single")
        ]
        pairs: list[_Pair] = []
        for index, inv in invoices:
            dates = [d for d in (inv.invoice_date, inv.order_date) if d]
            for t in lines:
                if inv.currency == "INR":
                    fits = inv.total_minor == t.amount_paise
                else:
                    fits = t.foreign_currency == inv.currency and t.foreign_amount_minor == inv.total_minor
                if not fits:
                    continue
                gap = min((abs((t.date - d).days) for d in dates), default=None)
                if dates and (gap is None or gap > NEAR_MISS_DAYS):
                    continue
                pairs.append(_Pair(0, gap if gap is not None else 5, t.ser_no, index, t, inv,
                                   "Exact amount. Vendor taken from the statement line.", "amount_led"))
        lines_of: dict[str, int] = defaultdict(int)
        invoices_of: dict[str, int] = defaultdict(int)
        for pair in pairs:
            lines_of[pair.invoice.id] += 1
            invoices_of[pair.txn.id] += 1
        for pair in sorted(pairs, key=_Pair.order):
            if pair.txn.id in self.results or pair.invoice.id in self.used:
                continue
            if lines_of[pair.invoice.id] == 1 and invoices_of[pair.txn.id] == 1:
                self.set(pair.txn, MATCHED, pair.note, [Link(pair.invoice.id, pair.rule)])
        for pair in sorted(pairs, key=_Pair.order):
            if pair.txn.id in self.results or pair.invoice.id in self.used:
                continue
            if lines_of[pair.invoice.id] > 1:
                note = f"{lines_of[pair.invoice.id]} statement lines fit this invoice (same amount, dates close). Check which one it belongs to."
            else:
                note = f"{invoices_of[pair.txn.id]} invoices with no vendor fit this line (same amount, dates close). Check which one it belongs to."
            self.suggest(pair.txn, [pair.invoice], note, pair.rule)

    @staticmethod
    def amount_hit(t: Txn, inv: Inv) -> tuple[int, str, str] | None:
        amounts = _candidate_amounts(inv)
        if inv.currency == "INR":
            if t.amount_paise in amounts:
                return 0, "Exact INR amount", "exact_inr"
            if t.foreign_currency == "USD" and t.foreign_amount_minor in inv.usd_amounts_minor:
                return 0, f"USD {_usd(t.foreign_amount_minor)} matches invoice", "usd_amount"
            if any(abs(t.amount_paise - a) <= 100 for a in amounts):
                return 1, "INR amount within Rs 1 (paise rounding on invoice)", "within_rs1"
        elif inv.currency == "USD":
            if t.foreign_currency == "USD" and t.foreign_amount_minor is not None and t.foreign_amount_minor in amounts:
                return 0, f"USD {_usd(t.foreign_amount_minor)} matches invoice", "usd_amount"
        return None

    # ---- rule 8: near misses --------------------------------------------------------------------------------
    def near_misses(self) -> None:
        lines = sorted(self.open_lines(), key=lambda t: (t.date, t.amount_paise, t.ser_no))
        for t in lines:
            vendor = self.vendor_of[t.id]
            if t.id in self.results or vendor is None or vendor.match_mode == "none":
                continue
            if self.near_usd_only(t, vendor) or self.same_day_credits(t, vendor) or self.within_percent(t, vendor):
                continue
            self.possible_duplicate(t)

    def near_usd_only(self, t: Txn, vendor: Vendor) -> bool:
        """(a) The only unused invoice of the vendor within 7 days is in USD and the line shows INR only."""
        low, high = t.date - timedelta(days=NEAR_MISS_DAYS), t.date + timedelta(days=NEAR_MISS_DAYS)
        near = [
            inv for inv in self.invoices
            if self.free(inv, vendor.key) and any(d and low <= d <= high for d in (inv.invoice_date, inv.order_date))
        ]
        if len(near) == 1 and near[0].currency == "USD" and t.foreign_amount_minor is None:
            self.suggest(t, near, "Only invoice from this vendor near this date; it is in USD and the statement "
                         "shows INR only", "near_usd_only")
            return True
        return False

    def same_day_credits(self, t: Txn, vendor: Vendor) -> bool:
        """(b) An Amazon debit equal to the sum of the Amazon credits of the same day."""
        if vendor.key != AMAZON:
            return False
        credits = [
            c for c in self.txns
            if c.is_credit and c.date == t.date and (self.vendor_of[c.id] or _NONE).key == AMAZON
            and self.results.get(c.id) is not None and self.results[c.id].status == CREDIT
        ]
        if credits and sum(c.amount_paise for c in credits) == t.amount_paise:
            parts = " + ".join(format_inr(c.amount_paise) for c in credits)
            self.set(t, REVIEW, f"Equals the Amazon credits of the same day ({parts}). Possibly a re-charge; no "
                     "separate invoice was supplied.")
            return True
        return False

    def within_percent(self, t: Txn, vendor: Vendor) -> bool:
        """(c) An unused invoice, or sum of invoices, of the vendor within the date window and within 5%."""
        low, high = t.date - timedelta(days=vendor.before_days), t.date + timedelta(days=vendor.after_days)
        pool = [
            inv for inv in self.invoices
            if self.free(inv, vendor.key) and inv.currency == "INR" and (inv.total_minor or 0) > 0
            and (d := _inv_date(inv)) is not None and low <= d <= high
        ]
        if not pool:
            return False
        try:
            combo = closest_subset(
                [inv.total_minor or 0 for inv in pool], t.amount_paise, tolerance_percent=NEAR_MISS_PERCENT,
                max_size=12 if vendor.match_mode == "subset" else 1,  # only Amazon and IndiGo charge several invoices
            )
        except SearchTooLarge:
            return False
        if combo is None:
            return False
        chosen = [pool[i] for i in combo]
        total = sum(inv.total_minor or 0 for inv in chosen)
        gap = total - t.amount_paise
        direction = "more" if gap > 0 else "less"
        names = ", ".join(f"{format_inr(inv.total_minor or 0)} ({_day(_inv_date(inv))})" for inv in chosen)
        self.suggest(t, chosen, f"Closest unused {vendor.display_name} invoice{'s' if len(chosen) > 1 else ''}: {names}, "
                     f"{format_inr(abs(gap))} {direction} than the charge.", "near_miss_5_percent")
        return True

    def possible_duplicate(self, t: Txn) -> None:
        """(d) An identical debit (same description, amount and date) already has the only matching invoice."""
        for other in self.txns:
            if (
                other.id != t.id and not other.is_credit and other.description == t.description
                and other.amount_paise == t.amount_paise and other.date == t.date
                and other.id in self.results and self.results[other.id].status == MATCHED
            ):
                self.set(t, REVIEW, f"Second identical {format_inr(t.amount_paise)} charge on the same day; only one "
                         "invoice was supplied. Possible duplicate charge.")
                return

    # ---- rules 9 and 10 -------------------------------------------------------------------------------------
    def the_rest(self) -> None:
        for t in self.open_lines():
            vendor = self.vendor_of[t.id]
            if vendor is None or vendor.match_mode == "none":
                self.set(t, NO_INVOICE, "No invoice supplied for this merchant")
            elif self.earliest_invoice is not None and t.date < self.earliest_invoice:
                self.set(t, MISSING, f"The charge is dated before the invoice set (the earliest invoice is dated "
                         f"{_day(self.earliest_invoice)}).")
            else:
                self.set(t, MISSING, "No invoice with this amount was supplied.")


def match(
    txns: Sequence[Txn],
    invoices: Sequence[Inv],
    vendors: Sequence[Vendor],
    *,
    csv: CsvReport | None = None,
    pinned: Sequence[Pinned] = (),
) -> list[LineResult]:
    """A decision for every line, in the order the lines were given. Deterministic: the same input
    always gives the same output."""
    m = _Matcher(txns, invoices, vendors, csv, pinned)
    m.rules_1_to_4()
    m.subset_vendors()
    m.other_vendors()
    m.amount_led()
    m.near_misses()
    m.the_rest()
    return [m.results[t.id] for t in m.txns]
