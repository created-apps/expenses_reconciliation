"""In-memory stand-ins for the Supabase repository and storage (same methods, no network)."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db import STATEMENT_RESET
from seed import seed_rows


class FakeRepo:
    def __init__(self) -> None:
        self.cycles: dict[str, dict[str, Any]] = {}
        self.files: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.transactions: list[dict[str, Any]] = []  # {cycle_id, status}
        self.invoices: dict[str, dict[str, Any]] = {}
        self.amazon_rows: list[dict[str, Any]] = []
        self.matches: list[dict[str, Any]] = []
        self.added_vendors: list[dict[str, Any]] = []
        self._tick = 0
        self._start = datetime.now(timezone.utc)  # timestamps run forward from the real clock

    def _now(self) -> str:
        self._tick += 1
        return (self._start + timedelta(milliseconds=self._tick)).isoformat()

    # cycles
    def create_cycle(self, label, created_by):
        row = {
            "id": str(uuid.uuid4()), "label": label, "status": "draft", "statement_date": None,
            "period_start": None, "period_end": None, "created_by": created_by,
            "statement_confirmed_at": None, "statement_confirmed_by": None,
            "job_kind": None, "job_status": None, "job_progress": None, "job_message": None,
            "summary_previous_paise": None, "summary_purchases_paise": None,
            "summary_credits_paise": None, "summary_total_due_paise": None,
            "created_at": self._now(), "updated_at": self._now(),
        }
        self.cycles[row["id"]] = row
        return dict(row)

    def list_cycles(self):
        return sorted((dict(c) for c in self.cycles.values()), key=lambda c: c["created_at"], reverse=True)

    def get_cycle(self, cycle_id):
        c = self.cycles.get(cycle_id)
        return dict(c) if c else None

    def touch_cycle(self, cycle_id):
        self.cycles[cycle_id]["updated_at"] = self._now()

    def _drop_orphan_matches(self):
        """on delete cascade: a link goes when its line or its invoice goes."""
        txn_ids = {t.get("id") for t in self.transactions}
        self.matches = [m for m in self.matches if m["invoice_id"] in self.invoices and m["transaction_id"] in txn_ids]

    def delete_cycle(self, cycle_id):
        self.cycles.pop(cycle_id, None)
        self.files = {k: v for k, v in self.files.items() if v["cycle_id"] != cycle_id}
        self.invoices = {k: v for k, v in self.invoices.items() if v["cycle_id"] != cycle_id}
        self.amazon_rows = [r for r in self.amazon_rows if r["cycle_id"] != cycle_id]
        self.transactions = [t for t in self.transactions if t["cycle_id"] != cycle_id]
        self.events = [e for e in self.events if e["cycle_id"] != cycle_id]
        self._drop_orphan_matches()

    def update_cycle(self, cycle_id, fields):
        self.cycles[cycle_id].update(fields)
        self.cycles[cycle_id]["updated_at"] = self._now()

    def list_transactions(self, cycle_id):
        rows = [dict(t) for t in self.transactions if t["cycle_id"] == cycle_id]
        return sorted(rows, key=lambda t: (t["txn_date"], t.get("sort_order", 0), t["ser_no"]))

    def replace_transactions(self, cycle_id, rows):
        sers = [r["ser_no"] for r in rows]
        if len(set(sers)) != len(sers):
            raise ValueError("duplicate key value violates unique constraint (cycle_id, ser_no)")
        self.transactions = [t for t in self.transactions if t["cycle_id"] != cycle_id]
        self.transactions.extend({"id": str(uuid.uuid4()), "status": None, **r} for r in rows)
        self._drop_orphan_matches()

    def reset_statement(self, cycle_id, clear_label=False):
        self.transactions = [t for t in self.transactions if t["cycle_id"] != cycle_id]
        self.update_cycle(cycle_id, {**STATEMENT_RESET, **({"label": None} if clear_label else {})})
        self._drop_orphan_matches()

    def line_counts(self, cycle_id):
        rows = [t for t in self.transactions if t["cycle_id"] == cycle_id]
        return {
            "total": len(rows),
            "matched": sum(1 for t in rows if t["status"] == "Matched"),
            "open": sum(1 for t in rows if t["status"] in ("Review", "Missing invoice")),
        }

    # files
    def list_files(self, cycle_id):
        return [dict(f) for f in self.files.values() if f["cycle_id"] == cycle_id]

    def live_files(self, cycle_id):
        return [dict(f) for f in self.files.values() if f["cycle_id"] == cycle_id and f["status"] != "duplicate"]

    def get_file(self, file_id):
        f = self.files.get(file_id)
        return dict(f) if f else None

    def _check_unique(self, row, ignoring=None):
        if row["status"] == "duplicate" or not row.get("sha256"):
            return
        for other in self.files.values():
            if other["id"] != ignoring and other["cycle_id"] == row["cycle_id"] and other["status"] != "duplicate" \
                    and other["sha256"] == row["sha256"]:
                raise ValueError("duplicate key value violates unique constraint (cycle_id, sha256) where status <> 'duplicate'")

    def insert_files(self, rows):
        out = []
        for r in rows:
            row = {"note": None, "error": None, "storage_path": None, "parent_file_id": None, **r, "created_at": self._now()}
            if row["parent_file_id"] is not None and row["parent_file_id"] not in self.files:
                raise ValueError("foreign key violation: parent_file_id")
            self._check_unique(row)
            self.files[row["id"]] = row
            out.append(dict(row))
        return out

    def update_file(self, file_id, fields):
        row = {**self.files[file_id], **fields}
        self._check_unique(row, ignoring=file_id)
        self.files[file_id] = row

    def delete_files(self, file_ids):
        for fid in file_ids:
            self.files.pop(fid, None)
        self.invoices = {i: row for i, row in self.invoices.items() if row["file_id"] in self.files}  # cascade
        self.amazon_rows = [r for r in self.amazon_rows if r["file_id"] in self.files]  # cascade
        self._drop_orphan_matches()

    # invoices
    def list_vendor_aliases(self):
        # the vendor table exactly as the migrations seed it, plus vendors added by hand
        return [*seed_rows(), *(dict(v) for v in self.added_vendors)]

    def add_vendor_alias(self, row):
        if any(v["vendor_key"] == row["vendor_key"] for v in self.list_vendor_aliases()):
            raise ValueError("duplicate key value violates unique constraint (vendor_key)")
        self.added_vendors.append(dict(row))
        return dict(row)

    def list_invoices(self, cycle_id):
        rows = [dict(i) for i in self.invoices.values() if i["cycle_id"] == cycle_id]
        return sorted(rows, key=lambda i: (i["file_id"], i["block_index"]))

    def get_invoice(self, invoice_id):
        row = self.invoices.get(invoice_id)
        return dict(row) if row else None

    def insert_invoices(self, rows):
        out = []
        for r in rows:
            if r["file_id"] not in self.files:
                raise ValueError("foreign key violation: file_id")
            if any(i["file_id"] == r["file_id"] and i["block_index"] == r["block_index"] for i in self.invoices.values()):
                raise ValueError("duplicate key value violates unique constraint (file_id, block_index)")
            row = {"id": str(uuid.uuid4()), "duplicate_of": None, "extra": {}, "amounts_minor": [], **r, "updated_at": self._now()}
            self.invoices[row["id"]] = row
            out.append(dict(row))
        return out

    def update_invoice(self, invoice_id, fields):
        self.invoices[invoice_id].update(fields)
        self.invoices[invoice_id]["updated_at"] = self._now()

    def delete_invoices_for_files(self, file_ids):
        gone = {i for i, row in self.invoices.items() if row["file_id"] in set(file_ids)}
        for i in gone:
            del self.invoices[i]
        for row in self.invoices.values():
            if row.get("duplicate_of") in gone:
                row["duplicate_of"] = None  # on delete set null
        self._drop_orphan_matches()

    # matching
    def list_matches(self, cycle_id):
        return [dict(m) for m in self.matches if m["cycle_id"] == cycle_id]

    def insert_matches(self, rows):
        for r in rows:
            if any(m["transaction_id"] == r["transaction_id"] and m["invoice_id"] == r["invoice_id"] for m in self.matches):
                raise ValueError("duplicate key value violates unique constraint (transaction_id, invoice_id)")
            self.matches.append({"id": str(uuid.uuid4()), "created_by": None, "is_suggestion": False, **r})

    def delete_system_matches(self, cycle_id):
        self.matches = [m for m in self.matches if not (m["cycle_id"] == cycle_id and m.get("created_by") is None)]

    def update_transaction(self, transaction_id, fields):
        for t in self.transactions:
            if t.get("id") == transaction_id:
                t.update(fields)
                return
        raise KeyError(transaction_id)

    def get_transaction(self, transaction_id):
        for t in self.transactions:
            if t.get("id") == transaction_id:
                return dict(t)
        return None

    def update_transactions(self, rows):
        """An upsert on id that changes only the columns sent (like the real one)."""
        self.bulk_calls = getattr(self, "bulk_calls", 0) + 1
        for r in rows:
            for t in self.transactions:
                if t.get("id") == r["id"]:
                    t.update({k: v for k, v in r.items() if k != "id"})
                    break
            else:
                raise KeyError(r["id"])

    def delete_matches(self, match_ids):
        gone = set(match_ids)
        self.matches = [m for m in self.matches if m["id"] not in gone]

    def add_events(self, cycle_id, actor, events):
        for action, payload in events:
            self.add_event(cycle_id, actor, action, payload)

    # Amazon report
    def insert_amazon_rows(self, rows):
        for r in rows:
            if r["file_id"] not in self.files:
                raise ValueError("foreign key violation: file_id")
            self.amazon_rows.append({"id": str(uuid.uuid4()), **r})

    def list_amazon_rows(self, cycle_id):
        return sorted((dict(r) for r in self.amazon_rows if r["cycle_id"] == cycle_id), key=lambda r: (r["payment_date"] or "", r["id"]))

    def add_event(self, cycle_id, actor, action, payload):
        self.events.append(
            {"cycle_id": cycle_id, "actor": actor, "action": action, "payload": payload, "created_at": self._now()}
        )

    def last_event_at(self, cycle_id, action):
        times = [e["created_at"] for e in self.events if e["cycle_id"] == cycle_id and e["action"] == action]
        return max(times) if times else None


class FakeStorage:
    def __init__(self, fail_for: tuple[str, ...] = ()) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_for = fail_for
        self.removed: list[str] = []

    def put(self, path, data, content_type):
        if any(marker in path for marker in self.fail_for):
            raise RuntimeError("storage unavailable")
        self.objects[path] = data

    def get(self, path):
        return self.objects[path]

    def signed_url(self, path, expires_in):
        return f"https://storage.test/{path}?expires={expires_in}"

    def remove(self, paths):
        for p in paths:
            self.objects.pop(p, None)
            self.removed.append(p)

    def purge_prefix(self, prefix):
        doomed = [p for p in self.objects if p.startswith(prefix + "/")]
        self.remove(doomed)
        return len(doomed)
