"""June 2026 through the engine without the UI (Docker only: needs poppler and the git-ignored June files).

    docker compose run --rm -e PYTHONPATH=/app:/app/tests tests python scripts/compare_june.py

Prints the count per status and every line whose status or linked files differ from
doc/reference/june_2026_expected_results.csv (date, serial, amount, expected, now). No AI call, nothing uploaded.
The two byte-identical duplicate files are treated as the same file, as in test_export_fixtures.py.
"""

import csv
from collections import Counter
from pathlib import Path

from app.services.run_matching import run_matching, start_matching
from june_cycle import build_june

EXPECTED = next(p for p in (Path("/doc/reference"), Path(__file__).resolve().parents[2] / "doc" / "reference")
                if (p / "june_2026_expected_results.csv").exists()) / "june_2026_expected_results.csv"
SAME_FILE = {"140626_Amazon_525.pdf": "140626_Amazon_525(1).pdf", "MH2727WI016880_GC001_10-Jun-2026.pdf": "DTDC_488.pdf"}


def canon(name: str) -> str:
    return SAME_FILE.get(name, name)


def main() -> None:
    june = build_june()
    cycle = june.repo.get_cycle(june.cid)
    start_matching(june.repo, cycle)
    assert run_matching(june.repo, cycle, "t") is not None
    names = {i["id"]: june.names[i["file_id"]] for i in june.repo.list_invoices(june.cid)}
    files: dict[str, set[str]] = {}
    for m in june.repo.list_matches(june.cid):
        files.setdefault(m["transaction_id"], set()).add(canon(names[m["invoice_id"]]))
    now = {t["ser_no"]: t for t in june.repo.list_transactions(june.cid)}
    with open(EXPECTED, encoding="utf-8") as f:
        expected = list(csv.DictReader(f))

    print("Lines:", len(now), "(expected", len(expected), ")")
    counts = Counter(t["status"] for t in now.values())
    want = Counter(e["status"] for e in expected)
    for status in sorted(set(counts) | set(want)):
        print(f"  {status:16} now {counts[status]:3}   expected {want[status]:3}")
    amazon = [t for t in now.values() if "ASSPL" in t["description"].upper() and not t["is_credit"]]
    print("Amazon charges:", len(amazon), "->", dict(Counter(t["status"] for t in amazon)))

    differences = 0
    for e in expected:
        t = now.get(e["ser_no"])
        want_files = {canon(n.strip()) for n in e["files"].split(",") if n.strip()}
        got_files = files.get(t["id"], set()) if t else set()
        if t is None or t["status"] != e["status"] or got_files != want_files:
            differences += 1
            print(f"DIFF {e['date']} {e['ser_no']} {e['amount_inr']:>10}  expected {e['status']} {sorted(want_files)}"
                  f"  now {t['status'] if t else 'MISSING'} {sorted(got_files)}")
    print("Differences from the expected CSV:", differences)


if __name__ == "__main__":
    main()
