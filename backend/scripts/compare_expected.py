"""Compare a matched cycle with an expected-results CSV, line by line (statuses and files). READ-ONLY.

    docker compose run --rm tests python scripts/compare_expected.py <cycle id>
    docker compose run --rm tests python scripts/compare_expected.py <cycle id> /doc/reference/june_2026_expected_results.csv

It only reads the database (with the service key from backend/.env) and writes nothing. It prints every
line that differs (SerNo, what was expected, what the app saved) and exits with 1 if there is any.
Byte-identical pairs count as the same file (140626_Amazon_525.pdf = 140626_Amazon_525(1).pdf,
DTDC_488.pdf = MH2727WI016880_GC001_10-Jun-2026.pdf), as in the implementation plan.
"""

import csv
import sys
from pathlib import Path
from typing import Any

SAME_FILE = {"140626_Amazon_525.pdf": "140626_Amazon_525(1).pdf", "MH2727WI016880_GC001_10-Jun-2026.pdf": "DTDC_488.pdf"}
DEFAULT_CSV = "/doc/reference/june_2026_expected_results.csv"


def canon(name: str) -> str:
    return SAME_FILE.get(name, name)


def saved_lines(repo: Any, cycle_id: str) -> dict[str, tuple[str | None, set[str]]]:
    """{ser_no: (status, files)} as saved: every linked invoice's file, suggestions included."""
    file_names = {f["id"]: f["original_name"] for f in repo.list_files(cycle_id)}
    invoice_file = {i["id"]: file_names.get(i["file_id"], "?") for i in repo.list_invoices(cycle_id)}
    linked: dict[str, set[str]] = {}
    for m in repo.list_matches(cycle_id):
        linked.setdefault(m["transaction_id"], set()).add(canon(invoice_file.get(m["invoice_id"], "?")))
    return {t["ser_no"]: (t.get("status"), linked.get(t["id"], set())) for t in repo.list_transactions(cycle_id)}


def differences(repo: Any, cycle_id: str, expected_csv: str | Path) -> list[str]:
    """One text line per difference (empty when the cycle agrees with the CSV)."""
    actual = saved_lines(repo, cycle_id)
    with open(expected_csv, encoding="utf-8") as f:
        expected = list(csv.DictReader(f))
    found: list[str] = []
    if len(actual) != len(expected):
        found.append(f"the cycle has {len(actual)} lines but the CSV has {len(expected)}")
    for row in expected:
        want_files = {canon(n.strip()) for n in row["files"].split(",") if n.strip()}
        if row["ser_no"] not in actual:
            found.append(f"{row['date']} {row['ser_no']} {row['description']}: not in the cycle")
            continue
        status, files = actual[row["ser_no"]]
        if status != row["status"] or files != want_files:
            found.append(
                f"{row['date']} {row['ser_no']} {row['description']} ₹{row['amount_inr']}: expected {row['status']} "
                f"{sorted(want_files)}, saved {status} {sorted(files)}"
            )
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.config import get_settings
    from app.db import SupabaseRepo, supabase_client

    repo = SupabaseRepo(supabase_client(get_settings()))
    cycle_id, csv_path = argv[0], (argv[1] if len(argv) > 1 else DEFAULT_CSV)
    if repo.get_cycle(cycle_id) is None:
        print(f"No cycle with id {cycle_id}")
        return 2
    found = differences(repo, cycle_id, csv_path)
    lines = len(saved_lines(repo, cycle_id))
    if not found:
        print(f"All {lines} lines agree with {Path(csv_path).name} (status and files).")
        return 0
    print(f"{len(found)} line(s) differ from {Path(csv_path).name}:")
    for text in found:
        print(" -", text)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
