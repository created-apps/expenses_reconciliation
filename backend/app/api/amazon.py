from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.api.cycles import load_cycle
from app.auth import CurrentUser, get_current_user
from app.db import SupabaseRepo, get_repo
from app.schemas import AmazonFetchOut, AmazonReportOut
from app.services.amazon_fetch import amazon_to_fetch
from app.services.amazon_report import report_view

router = APIRouter(tags=["amazon"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Repo = Annotated[SupabaseRepo, Depends(get_repo)]


@router.get("/cycles/{cycle_id}/amazon-report", response_model=AmazonReportOut)
def get_amazon_report(cycle_id: UUID, user: User, repo: Repo) -> dict[str, Any]:
    """The uploaded Amazon Business report: card payment groups and gift-balance orders."""
    load_cycle(repo, cycle_id)
    return report_view(repo, str(cycle_id))

@router.get("/cycles/{cycle_id}/amazon-to-fetch", response_model=AmazonFetchOut)
async def get_amazon_to_fetch(cycle_id: UUID, user: User, repo: Repo) -> dict[str, Any]:
    """Amazon orders in the report's payment groups (one per statement charge) that have no invoice uploaded:
    Order ID, payment date, amount and the charge. Empty without a report; needs matching to have run."""
    cycle = await run_in_threadpool(load_cycle, repo, cycle_id)
    return await run_in_threadpool(amazon_to_fetch, repo, cycle)
