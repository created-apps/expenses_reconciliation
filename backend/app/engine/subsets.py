"""Which invoices add up to a charge. Integer paise only; pure Python.

Amazon and IndiGo charge several invoices at once, so a charge is matched to a SET of invoices whose
totals sum to it (project_context.md section 8, rules 5 and 6). The search returns subsets in the same
order as `itertools.combinations` (by size, then by position in the list), which fixes "the first
option" when several fit.
"""

from collections.abc import Sequence

MAX_SIZE = 12  # most invoices in one charge (rule 5)
STOP_AFTER = 50  # stop growing the subsets once more than this many solutions are known
BUDGET = 3_000_000  # search steps allowed before giving up (a pool this big is not a real month)


class SearchTooLarge(Exception):
    """Too many combinations to check; the caller reports it instead of guessing."""


def exact_subsets(
    totals: Sequence[int], target: int, *, max_size: int = MAX_SIZE, stop_after: int = STOP_AFTER, budget: int = BUDGET
) -> list[tuple[int, ...]]:
    """Positions of every subset (up to `max_size` items) whose totals sum to `target`.

    Totals must be positive. Subsets come smallest first and, within a size, in list order. Like the
    prototype, the search stops after the size at which more than `stop_after` solutions are known.
    """
    n = len(totals)
    found: list[tuple[int, ...]] = []
    steps = 0
    for size in range(1, min(n, max_size) + 1):
        chosen: list[int] = []

        def walk(start: int, need: int, remaining: int) -> None:
            nonlocal steps
            steps += 1
            if steps > budget:
                raise SearchTooLarge
            if need == 0:
                if remaining == 0:
                    found.append(tuple(chosen))
                return
            for i in range(start, n - need + 1):
                value = totals[i]
                if value > remaining:
                    continue
                chosen.append(i)
                walk(i + 1, need - 1, remaining - value)
                chosen.pop()

        walk(0, size, target)
        if len(found) > stop_after:
            break
    return found


def closest_subset(
    totals: Sequence[int], target: int, *, tolerance_percent: int = 5, max_size: int = MAX_SIZE, budget: int = BUDGET
) -> tuple[int, ...] | None:
    """The subset whose sum is nearest to `target` and within `tolerance_percent` of it (rule 8c), or None.

    Nearest first, then fewest invoices, then list order. Totals must be positive. A sum equal to the
    target counts too (the caller decides whether that is possible).
    """
    n = len(totals)
    low = target * (100 - tolerance_percent)  # compared as sum * 100, so no fractions are needed
    high = target * (100 + tolerance_percent)
    best: tuple[int, int, tuple[int, ...]] | None = None
    steps = 0
    chosen: list[int] = []

    def walk(start: int, total: int) -> None:
        nonlocal best, steps
        steps += 1
        if steps > budget:
            raise SearchTooLarge
        if chosen and low <= total * 100 <= high:
            candidate = (abs(total - target), len(chosen), tuple(chosen))
            if best is None or candidate < best:
                best = candidate
        if len(chosen) == min(n, max_size):
            return
        for i in range(start, n):
            if (total + totals[i]) * 100 > high:
                continue  # totals are positive: adding more can only go further over
            chosen.append(i)
            walk(i + 1, total + totals[i])
            chosen.pop()

    walk(0, 0)
    return best[2] if best else None
