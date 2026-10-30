from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool

from app.api.cycles import load_cycle
from app.auth import CurrentUser, get_current_user
from app.db import SupabaseRepo, get_repo
from app.schemas import ExportSummaryOut
from app.services.export import build_export, export_summary
from app.services.gates import ServiceError

router = APIRouter(tags=["export"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Repo = Annotated[SupabaseRepo, Depends(get_repo)]

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/cycles/{cycle_id}/export-summary", response_model=ExportSummaryOut)
async def get_export_summary(cycle_id: UUID, user: User, repo: Repo) -> dict[str, Any]:
    """What the Export step shows: counts by status, the totals check against the statement, lines still
    needing review, and whether the reconciliation was edited after its last export. 409 before matching."""
    cycle = await run_in_threadpool(load_cycle, repo, cycle_id)
    try:
        return await run_in_threadpool(export_summary, repo, cycle)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, exc.message) from None


@router.get("/cycles/{cycle_id}/export.xlsx")
async def download_export(cycle_id: UUID, user: User, repo: Repo) -> Response:
    """The Excel workbook for the current state (Summary, the month sheet, Invoices not used). Allowed any
    number of times; it sets the reconciliation to `exported`. 409 before matching."""
    cycle = await run_in_threadpool(load_cycle, repo, cycle_id)
    try:
        content, file_name = await run_in_threadpool(build_export, repo, cycle, user.email)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    return Response(
        content=content,
        media_type=XLSX,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}"},
    )
