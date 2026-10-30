"""Compare a matched cycle's "Invoices not used" list with the one in a reference workbook. READ-ONLY.

    docker compose run --rm tests python scripts/compare_unused_sheet.py <cycle id> <reference.xlsx>

For June the reference is `CC_Expense_June_2026.xlsx` (put it in backend/tests/fixtures_private/, which the
tests container mounts at /app/tests/fixtures_private). The script reads the cycle from the database with the
service key in backend/.env, writes nothing, and prints the file names that are only in the app's list and
only in the reference sheet, with the app's reason for each. A Review suggestion reserves its invoices
(project_context.md section 8, rule 8), so the app's list can legitimately be shorter than the prototype's.
Byte-identical pairs count as the same file, as in compare_expected.py. Exit code 1 when the lists differ.
"""

import sys
from io import BytesIO
from pathlib import Path

SAME_FILE = {"140626_Amazon_525.pdf": "140626_Amazon_525(1).pdf", "MH2727WI016880_GC001_10-Jun-2026.pdf": "DTDC_488.pdf"}


def canon(name: str) -> str:
    return SAME_FILE.get(name, name)


def reference_names(data: bytes) -> list[str]:
    """File names from the reference workbook's unused-invoices sheet: the sheet whose name mentions
    "not used" or "unused", and the column whose header mentions "file" (else the first column)."""
    from openpyxl import load_workbook

    wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    sheet = next((n for n in wb.sheetnames if "not used" in n.lower() or "unused" in n.lower()), None)
    if sheet is None:
        raise SystemExit(f"No unused-invoices sheet in the reference workbook. Sheets: {', '.join(wb.sheetnames)}")
    rows = list(wb[sheet].iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(c or "").lower() for c in rows[0]]
    col = next((i for i, h in enumerate(header) if "file" in h), 0)
    return [str(r[col]).strip() for r in rows[1:] if len(r) > col and r[col] not in (None, "")]


def differences(ours: dict[str, str], reference: list[str]) -> tuple[list[str], list[str]]:
    """(only in the app, only in the reference), names as the reference writes them. `ours` is {file: reason}."""
    mine = {canon(n) for n in ours}
    theirs = {canon(n) for n in reference}
    return sorted(mine - theirs), sorted(theirs - mine)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.config import get_settings
    from app.db import SupabaseRepo, supabase_client
    from app.services.results import unused_view

    repo = SupabaseRepo(supabase_client(get_settings()))
    cycle = repo.get_cycle(argv[0])
    if cycle is None:
        print(f"No cycle with id {argv[0]}")
        return 2
    ours = {i["file_name"]: i["reason"] for i in unused_view(repo, cycle)["items"]}
    reference = reference_names(Path(argv[1]).read_bytes())
    only_app, only_reference = differences(ours, reference)
    print(f"The app lists {len(ours)} unused invoices; {Path(argv[1]).name} lists {len(reference)}.")
    if not only_app and not only_reference:
        print("The two lists agree.")
        return 0
    if only_app:
        print(f"\nOnly in the app ({len(only_app)}):")
        for n in only_app:
            print(f" - {n}  [{ours.get(n) or ours.get(SAME_FILE.get(n, n)) or '?'}]")
    if only_reference:
        print(f"\nOnly in {Path(argv[1]).name} ({len(only_reference)}):")
        for n in only_reference:
            print(f" - {n}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
