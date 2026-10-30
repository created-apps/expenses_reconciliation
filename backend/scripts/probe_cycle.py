"""Run a statement + invoice ZIP (+ optional Amazon report) from tests/fixtures_private through the real pipeline,
in memory (Docker only: needs poppler). Prints every invoice read and every line's decision.

    docker compose run --rm -e PYTHONPATH=/app:/app/tests tests python scripts/probe_cycle.py "CC Statement October.pdf" "October 2026 CC Invoices.zip" "reconciliation by shipment*.csv"

Nothing is uploaded and no model is called: images stay unread (pending).
"""

import sys
from collections import Counter
from pathlib import Path

from app.services.ingest import Incoming, ingest_upload
from app.services.invoices import run_extract
from app.services.run_matching import run_matching, start_matching
from app.services.statement import confirm_statement, run_parse, statement_file
from fakes import FakeRepo, FakeStorage
from june_cycle import FIXTURES, LIMITS


def find(pattern: str) -> Path:
    return sorted(FIXTURES.glob(pattern))[0]


def main(statement: str, zip_name: str, report: str | None) -> None:
    repo, storage = FakeRepo(), FakeStorage()
    cid = repo.create_cycle(None, "t")["id"]
    uploads = [("statement", find(statement)), ("invoices", find(zip_name))]
    if report:
        uploads.append(("amazon_report", find(report)))
    for kind, path in uploads:
        ingest_upload(repo=repo, storage=storage, cycle=repo.get_cycle(cid), kind=kind,
                      uploads=[Incoming(path.name, path.read_bytes())], actor="t", limits=LIMITS)
    run_parse(repo=repo, storage=storage, cycle_id=cid, file=statement_file(repo, cid), actor="t")
    print("statement:", repo.get_cycle(cid)["job_status"], repo.get_cycle(cid)["job_message"])
    confirm_statement(repo, repo.get_cycle(cid), "t")
    run_extract(repo=repo, storage=storage, cycle_id=cid, actor="t", vision=None)
    names = {f["id"]: f["original_name"] for f in repo.list_files(cid)}
    print("\n== INVOICES ==")
    for inv in sorted(repo.list_invoices(cid), key=lambda i: names[i["file_id"]]):
        print(f"{names[inv['file_id']][:44]:44} v={inv.get('vendor_key')!s:12} {inv.get('currency')} "
              f"tot={inv.get('total_minor')} inv={inv.get('invoice_date')} ord={inv.get('order_date')} "
              f"st={inv.get('extraction_status')} dup={bool(inv.get('duplicate_of'))}")
    cycle = repo.get_cycle(cid)
    start_matching(repo, cycle)
    run_matching(repo, cycle, "t")
    print("\n== LINES ==")
    inv_name = {i["id"]: names[i["file_id"]] for i in repo.list_invoices(cid)}
    links: dict[str, list[str]] = {}
    for m in repo.list_matches(cid):
        links.setdefault(m["transaction_id"], []).append(inv_name[m["invoice_id"]] + ("?" if m.get("is_suggestion") else ""))
    counts: Counter = Counter()
    for t in sorted(repo.list_transactions(cid), key=lambda t: (t["txn_date"], t["ser_no"])):
        counts[t["status"]] += 1
        sign = "-" if t["is_credit"] else " "
        print(f"{t['txn_date']} {t['ser_no'][-6:]} {sign}{t['amount_paise']/100:>10.2f} {t['status']:16} "
              f"{t['description'][:34]:34} {', '.join(links.get(t['id'], []))[:60]} | {(t.get('notes') or '')[:110]}")
    print("\n", dict(counts))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
