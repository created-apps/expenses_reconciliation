"""Supabase (service role) access for the recon_* tables. Only this module talks to the database.

The frontend never queries tables; everything goes through the API, which uses this repository.
Tests replace it with an in-memory fake that has the same methods.
"""

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, status
from supabase import Client, create_client

from app.config import Settings, get_settings

PAGE = 1000  # PostgREST returns at most 1000 rows per request, so reads are paged

# What an unread statement looks like on the cycle row (used when the statement is replaced).
STATEMENT_RESET: dict[str, Any] = {
    "status": "draft",
    "statement_date": None,
    "period_start": None,
    "period_end": None,
    "summary_previous_paise": None,
    "summary_purchases_paise": None,
    "summary_credits_paise": None,
    "summary_total_due_paise": None,
    "statement_confirmed_at": None,
    "statement_confirmed_by": None,
    "job_kind": None,
    "job_status": None,
    "job_progress": None,
    "job_message": None,
}


class SupabaseRepo:
    def __init__(self, client: Client):
        self.c = client

    # -- cycles ---------------------------------------------------------------------------------
    def create_cycle(self, label: str | None, created_by: str) -> dict[str, Any]:
        res = self.c.table("recon_cycles").insert({"label": label, "created_by": created_by}).execute()
        return res.data[0]

    def list_cycles(self) -> list[dict[str, Any]]:
        return self._all(lambda: self.c.table("recon_cycles").select("*").order("created_at", desc=True))

    def get_cycle(self, cycle_id: str) -> dict[str, Any] | None:
        res = self.c.table("recon_cycles").select("*").eq("id", cycle_id).limit(1).execute()
        return res.data[0] if res.data else None

    def touch_cycle(self, cycle_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.c.table("recon_cycles").update({"updated_at": now}).eq("id", cycle_id).execute()

    def delete_cycle(self, cycle_id: str) -> None:
        """Rows in recon_files, recon_transactions, ... go with it (on delete cascade)."""
        self.c.table("recon_cycles").delete().eq("id", cycle_id).execute()

    def update_cycle(self, cycle_id: str, fields: dict[str, Any]) -> None:
        self.c.table("recon_cycles").update(fields).eq("id", cycle_id).execute()

    # -- statement lines ------------------------------------------------------------------------
    def list_transactions(self, cycle_id: str) -> list[dict[str, Any]]:
        return self._all(
            lambda: self.c.table("recon_transactions")
            .select("*")
            .eq("cycle_id", cycle_id)
            .order("txn_date")
            .order("sort_order")
            .order("ser_no")
        )

    def replace_transactions(self, cycle_id: str, rows: list[dict[str, Any]]) -> None:
        """Swap the cycle's statement lines for `rows` (used when a statement is read again)."""
        self.c.table("recon_transactions").delete().eq("cycle_id", cycle_id).execute()
        for i in range(0, len(rows), 200):
            self.c.table("recon_transactions").insert(rows[i : i + 200]).execute()

    def reset_statement(self, cycle_id: str, clear_label: bool = False) -> None:
        """Back to an unread statement: no lines, no header or summary figures, status draft.
        `clear_label` also drops a name that was filled in from the old statement's month."""
        self.c.table("recon_transactions").delete().eq("cycle_id", cycle_id).execute()
        self.update_cycle(cycle_id, {**STATEMENT_RESET, **({"label": None} if clear_label else {})})

    def line_counts(self, cycle_id: str) -> dict[str, int]:
        """Statement-line counts for the home list: all lines, matched, and open (needs attention)."""

        def count(extra=None) -> int:
            q = self.c.table("recon_transactions").select("id", count="exact", head=True).eq("cycle_id", cycle_id)
            if extra:
                q = extra(q)
            return q.execute().count or 0

        return {
            "total": count(),
            "matched": count(lambda q: q.eq("status", "Matched")),
            "open": count(lambda q: q.in_("status", ["Review", "Missing invoice"])),
        }

    # -- files ----------------------------------------------------------------------------------
    def list_files(self, cycle_id: str) -> list[dict[str, Any]]:
        return self._all(
            lambda: self.c.table("recon_files").select("*").eq("cycle_id", cycle_id).order("created_at").order("original_name")
        )

    def live_files(self, cycle_id: str) -> list[dict[str, Any]]:
        """Files that count as the live copy of their content (everything except duplicates)."""
        return self._all(
            lambda: self.c.table("recon_files")
            .select("id,kind,sha256,status,storage_path,original_name")
            .eq("cycle_id", cycle_id)
            .neq("status", "duplicate")
            .order("created_at")
        )

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        res = self.c.table("recon_files").select("*").eq("id", file_id).limit(1).execute()
        return res.data[0] if res.data else None

    def insert_files(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i in range(0, len(rows), 200):
            out.extend(self.c.table("recon_files").insert(rows[i : i + 200]).execute().data)
        return out

    def update_file(self, file_id: str, fields: dict[str, Any]) -> None:
        self.c.table("recon_files").update(fields).eq("id", file_id).execute()

    def delete_files(self, file_ids: list[str]) -> None:
        for i in range(0, len(file_ids), 100):
            self.c.table("recon_files").delete().in_("id", file_ids[i : i + 100]).execute()

    # -- invoices -------------------------------------------------------------------------------
    def list_vendor_aliases(self) -> list[dict[str, Any]]:
        return self._all(lambda: self.c.table("recon_vendor_aliases").select("*").eq("active", True).order("vendor_key"))

    def list_invoices(self, cycle_id: str) -> list[dict[str, Any]]:
        return self._all(
            lambda: self.c.table("recon_invoices").select("*").eq("cycle_id", cycle_id).order("file_id").order("block_index")
        )

    def get_invoice(self, invoice_id: str) -> dict[str, Any] | None:
        res = self.c.table("recon_invoices").select("*").eq("id", invoice_id).limit(1).execute()
        return res.data[0] if res.data else None

    def insert_invoices(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i in range(0, len(rows), 200):
            out.extend(self.c.table("recon_invoices").insert(rows[i : i + 200]).execute().data)
        return out

    def update_invoice(self, invoice_id: str, fields: dict[str, Any]) -> None:
        self.c.table("recon_invoices").update(fields).eq("id", invoice_id).execute()

    def delete_invoices_for_files(self, file_ids: list[str]) -> None:
        """Remove the invoice rows read from these files (their matches go with them: on delete cascade)."""
        for i in range(0, len(file_ids), 100):
            self.c.table("recon_invoices").delete().in_("file_id", file_ids[i : i + 100]).execute()

    # -- matching -------------------------------------------------------------------------------
    def list_matches(self, cycle_id: str) -> list[dict[str, Any]]:
        return self._all(lambda: self.c.table("recon_matches").select("*").eq("cycle_id", cycle_id).order("id"))

    def insert_matches(self, rows: list[dict[str, Any]]) -> None:
        for i in range(0, len(rows), 200):
            self.c.table("recon_matches").insert(rows[i : i + 200]).execute()

    def delete_system_matches(self, cycle_id: str) -> None:
        """Remove the links the system made (created_by is null); a person's links stay."""
        self.c.table("recon_matches").delete().eq("cycle_id", cycle_id).is_("created_by", "null").execute()

    def update_transaction(self, transaction_id: str, fields: dict[str, Any]) -> None:
        self.c.table("recon_transactions").update(fields).eq("id", transaction_id).execute()

    def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        res = self.c.table("recon_transactions").select("*").eq("id", transaction_id).limit(1).execute()
        return res.data[0] if res.data else None

    def update_transactions(self, rows: list[dict[str, Any]]) -> None:
        """Write many lines in few calls. Every row carries `id`, the not-null columns of the line
        (`cycle_id`, `ser_no`, `txn_date`, `description`, `amount_paise`) and the columns to change; an upsert
        on `id` changes only the columns sent, so everything else on the line stays as it is."""
        for i in range(0, len(rows), 200):
            self.c.table("recon_transactions").upsert(rows[i : i + 200], on_conflict="id", returning="minimal").execute()

    def delete_matches(self, match_ids: list[str]) -> None:
        for i in range(0, len(match_ids), 100):
            self.c.table("recon_matches").delete().in_("id", match_ids[i : i + 100]).execute()

    # -- Amazon report --------------------------------------------------------------------------
    def insert_amazon_rows(self, rows: list[dict[str, Any]]) -> None:
        for i in range(0, len(rows), 200):
            self.c.table("recon_amazon_rows").insert(rows[i : i + 200]).execute()

    def list_amazon_rows(self, cycle_id: str) -> list[dict[str, Any]]:
        return self._all(
            lambda: self.c.table("recon_amazon_rows").select("*").eq("cycle_id", cycle_id).order("payment_date").order("id")
        )

    # -- audit ----------------------------------------------------------------------------------
    def add_event(self, cycle_id: str, actor: str, action: str, payload: dict[str, Any]) -> None:
        self.c.table("recon_events").insert(
            {"cycle_id": cycle_id, "actor": actor, "action": action, "payload": payload}
        ).execute()

    def last_event_at(self, cycle_id: str, action: str) -> str | None:
        """When the latest audit row with this action was written, or None if there is none."""
        res = (
            self.c.table("recon_events").select("created_at").eq("cycle_id", cycle_id).eq("action", action)
            .order("created_at", desc=True).limit(1).execute()
        )
        return res.data[0]["created_at"] if res.data else None

    def add_events(self, cycle_id: str, actor: str, events: list[tuple[str, dict[str, Any]]]) -> None:
        """Several audit rows in one call: (action, payload) pairs."""
        if events:
            self.c.table("recon_events").insert(
                [{"cycle_id": cycle_id, "actor": actor, "action": a, "payload": p} for a, p in events]
            ).execute()

    # -- helpers --------------------------------------------------------------------------------
    @staticmethod
    def _all(make_query) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            page = make_query().range(start, start + PAGE - 1).execute().data
            rows.extend(page)
            if len(page) < PAGE:
                return rows
            start += PAGE


@lru_cache
def _client(url: str, key: str) -> Client:
    return create_client(url, key)


def supabase_client(settings: Settings) -> Client:
    key = settings.supabase_service_role_key.get_secret_value()
    if not settings.supabase_url or not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage is not configured on the server",
        )
    return _client(settings.supabase_url, key)


def get_repo(settings: Settings = Depends(get_settings)) -> SupabaseRepo:
    return SupabaseRepo(supabase_client(settings))
