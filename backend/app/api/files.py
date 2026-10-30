from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from storage3.exceptions import StorageApiError

from app.api.cycles import load_cycle
from app.auth import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.db import SupabaseRepo, get_repo
from app.schemas import FileOut, FileUrl, UploadResponse
from app.services.ingest import IngestError, Incoming, Limits, ingest_upload
from app.storage import SupabaseStorage, get_storage

router = APIRouter(tags=["files"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Repo = Annotated[SupabaseRepo, Depends(get_repo)]
Storage = Annotated[SupabaseStorage, Depends(get_storage)]
Config = Annotated[Settings, Depends(get_settings)]

MB = 1024 * 1024


def _file_out(row: dict[str, Any]) -> FileOut:
    return FileOut(**{k: row.get(k) for k in FileOut.model_fields if k != "has_copy"}, has_copy=bool(row.get("storage_path")))


@router.post("/cycles/{cycle_id}/files", response_model=UploadResponse)
async def upload_files(
    cycle_id: UUID,
    request: Request,
    user: User,
    repo: Repo,
    storage: Storage,
    settings: Config,
    kind: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
) -> UploadResponse:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_request_mb * MB:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"Upload is too large (max {settings.max_request_mb} MB)")

    cycle = await run_in_threadpool(load_cycle, repo, cycle_id)
    uploads = [Incoming(name=f.filename or "file", data=await f.read()) for f in files]
    limits = Limits(
        max_file_bytes=settings.max_file_mb * MB,
        max_zip_total_bytes=settings.max_zip_total_mb * MB,
        max_zip_entries=settings.max_zip_entries,
    )
    try:
        result = await run_in_threadpool(
            ingest_upload,
            repo=repo,
            storage=storage,
            cycle=cycle,
            kind=kind,
            uploads=uploads,
            actor=user.email,
            limits=limits,
        )
    except IngestError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    return UploadResponse(files=[_file_out(r) for r in result.files], rejected=result.rejected)  # type: ignore[arg-type]


@router.get("/cycles/{cycle_id}/files", response_model=list[FileOut])
def list_files(cycle_id: UUID, user: User, repo: Repo) -> list[FileOut]:
    cycle = load_cycle(repo, cycle_id)
    rows = repo.list_files(cycle["id"])
    # Containers (ZIPs) first, then their members, in the order they were added.
    rows.sort(key=lambda r: (r["created_at"], r["parent_file_id"] is not None, r["original_name"]))
    return [_file_out(r) for r in rows]


@router.get("/files/{file_id}/url", response_model=FileUrl)
def file_url(file_id: UUID, user: User, repo: Repo, storage: Storage, settings: Config) -> FileUrl:
    row = repo.get_file(str(file_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    if not row.get("storage_path"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No stored copy of this file (it is a duplicate or failed to store)")
    try:
        url = storage.signed_url(row["storage_path"], settings.signed_url_seconds)
    except StorageApiError as exc:
        if str(exc.status) == "404":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "The stored file could not be found") from None
        raise
    return FileUrl(url=url, expires_in=settings.signed_url_seconds, file_name=row["original_name"])
