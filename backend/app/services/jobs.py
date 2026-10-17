"""Which background job the cycle row's job columns belong to.

Statement reading, invoice reading and matching share three columns on `recon_cycles` (`job_status`,
`job_progress`, `job_message`). `job_kind` (migration 0004) says whose they are, so a screen never mistakes one
job's progress or failure for another's.
"""

from typing import Any

STATEMENT = "statement"
INVOICES = "invoices"
MATCHING = "matching"
KINDS = (STATEMENT, INVOICES, MATCHING)


def job_fields(kind: str | None, status: str | None, progress: int | None, message: str | None) -> dict[str, Any]:
    """The columns to write for a job (all four together, so the kind can never be left behind)."""
    return {"job_kind": kind, "job_status": status, "job_progress": progress, "job_message": message}


CLEARED = job_fields(None, None, None, None)
