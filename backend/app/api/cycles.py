import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth import CurrentUser, get_current_user
from app.db import SupabaseRepo, get_repo
from app.schemas import CycleCreate, CycleDetail, CycleOut, FileCounts
from app.services.export import edited_since_export
from app.storage import SupabaseStorage, get_storage

log = logging.getLogger("app.cycles")
router = APIRouter(prefix="/cycles", tags=["cycles"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Repo = Annotated[SupabaseRepo, Depends(get_repo)]
Storage = Annotated[SupabaseStorage, Depends(get_storage)]


def _summary(repo: SupabaseRepo, cycle: dict[str, Any]) -> dict[str, Any]:
    counts = repo.line_counts(cycle["id"])
    has_lines = counts["total"] > 0
    return {
        **cycle,
        "total_lines": counts["total"] if has_lines else None,
        "matched_lines": counts["matched"] if has_lines else None,
        "open_items": counts["open"] if has_lines else None,
    }


def file_counts(files: list[dict[str, Any]]) -> FileCounts:
    live = [f for f in files if f["status"] != "duplicate"]
    return FileCounts(
        statement=sum(1 for f in live if f["kind"] == "statement"),
        invoices=sum(1 for f in live if f["kind"] == "invoice"),
        ignored=sum(1 for f in files if f["kind"] == "ignored"),
        duplicates=sum(1 for f in files if f["status"] == "duplicate"),
        amazon_reports=sum(1 for f in live if f["kind"] == "amazon_report"),
        zips=sum(1 for f in files if f["kind"] == "zip"),
        total=len(files),
    )


def load_cycle(repo: SupabaseRepo, cycle_id: UUID) -> dict[str, Any]:
    cycle = repo.get_cycle(str(cycle_id))
    if cycle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reconciliation not found")
    return cycle


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CycleOut)
def create_cycle(user: User, repo: Repo, body: CycleCreate | None = None) -> dict[str, Any]:
    label = (body.label or "").strip() if body else ""
    cycle = repo.create_cycle(label or None, user.email)
    return _summary(repo, cycle)


@router.get("", response_model=list[CycleOut])
def list_cycles(user: User, repo: Repo) -> list[dict[str, Any]]:
    return [_summary(repo, c) for c in repo.list_cycles()]


@router.get("/{cycle_id}", response_model=CycleDetail)
def get_cycle(cycle_id: UUID, user: User, repo: Repo) -> dict[str, Any]:
    cycle = load_cycle(repo, cycle_id)
    exported_at, edited = edited_since_export(repo, cycle)
    return {
        **_summary(repo, cycle),
        "files": file_counts(repo.list_files(cycle["id"])),
        "last_exported_at": exported_at,
        "edited_since_export": edited,
    }


@router.delete("/{cycle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cycle(cycle_id: UUID, user: User, repo: Repo, storage: Storage) -> Response:
    cycle = load_cycle(repo, cycle_id)
    if cycle["status"] == "exported":
        raise HTTPException(status.HTTP_409_CONFLICT, "An exported reconciliation can't be deleted")
    # Stored files go first: if that fails the cycle stays, and nothing is left orphaned in storage.
    paths = [f["storage_path"] for f in repo.list_files(cycle["id"]) if f.get("storage_path")]
    if paths:
        storage.remove(paths)
    # Then sweep the cycle's whole folder: an upload that reached storage but was recorded as
    # failed (connection dropped before the reply) has no database path to remove it by.
    swept = storage.purge_prefix(f"cycles/{cycle['id']}")
    repo.delete_cycle(cycle["id"])  # recon_files, transactions, ... go with it (cascade)
    log.info("Cycle %s deleted by %s (%d known files, %d more found in storage)", cycle["id"], user.email, len(paths), swept)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
