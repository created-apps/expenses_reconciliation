"""Static checks on the migration files the user runs by hand (nothing here touches a database)."""

import re
from pathlib import Path

import pytest

from app.services.jobs import KINDS

CANDIDATES = [Path(__file__).resolve().parents[2] / "supabase" / "migrations", Path("/supabase/migrations")]
MIGRATIONS = next((p for p in CANDIDATES if p.exists()), None)

pytestmark = pytest.mark.skipif(MIGRATIONS is None, reason="supabase/migrations not mounted")


def sql(name: str) -> str:
    return (MIGRATIONS / name).read_text(encoding="utf-8")


def code(text: str) -> str:
    """The SQL without comments."""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("--"))


def test_0004_adds_the_job_kind_column_with_a_check_for_exactly_the_kinds_the_code_writes():
    body = code(sql("0004_recon_job_kind.sql"))
    assert "add column if not exists job_kind text" in body
    assert "drop constraint if exists recon_cycles_job_kind_check" in body
    listed = set(re.findall(r"'([a-z]+)'", re.search(r"check \(job_kind in \(([^)]*)\)\)", body).group(1)))
    assert listed == set(KINDS)  # the database accepts every kind the API writes, and no other


def test_0004_is_idempotent_and_touches_only_recon_objects():
    body = code(sql("0004_recon_job_kind.sql")).lower()
    for statement in re.split(r";\s*\n", body):
        statement = statement.strip()
        if not statement:
            continue
        assert "recon_cycles" in statement, statement  # every statement is about our table
        if statement.startswith("alter table recon_cycles add column"):
            assert "if not exists" in statement
        if statement.startswith("alter table recon_cycles drop"):
            assert "if exists" in statement
    for other in ("payment_requests", "payment_webhook_events", "auth.", "storage."):
        assert other not in body


def test_0004_backfills_only_a_matching_run_and_has_a_verification_and_a_rollback():
    text = sql("0004_recon_job_kind.sql")
    body = code(text).lower()
    assert "set job_kind = 'matching'" in body and "job_kind is null" in body and "like 'matching%'" in body
    assert "VERIFICATION" in text and "ROLLBACK" in text and "drop column if exists job_kind" in text


def test_0005_seeds_only_vendor_rows_idempotently_with_a_verification_and_a_rollback():
    text = sql("0005_recon_vendor_aliases_oct.sql")
    body = code(text).lower()
    assert body.count("insert into recon_vendor_aliases") == 1 and "on conflict (vendor_key) do update" in body
    assert "delete " not in body and "drop " not in body and "alter " not in body
    assert "VERIFICATION" in text and "ROLLBACK" in text


def test_every_migration_is_numbered_in_order_and_only_touches_recon_or_the_bucket():
    names = sorted(p.name for p in MIGRATIONS.glob("*.sql"))
    assert [n[:4] for n in names] == ["0001", "0002", "0003", "0004", "0005"]
    for name in names:
        body = code(sql(name)).lower()
        assert "payment_requests" not in body and "payment_webhook_events" not in body, name
