from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.cycles import load_cycle
from app.auth import CurrentUser, get_current_user
from app.db import SupabaseRepo, get_repo
from app.schemas import MatchSummaryOut
from app.services.gates import ServiceError, note_edit
from app.services.run_matching import match_summary, run_matching, start_matching

router = APIRouter(tags=["matching"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Repo = Annotated[SupabaseRepo, Depends(get_repo)]


@router.post("/cycles/{cycle_id}/match", status_code=status.HTTP_202_ACCEPTED, response_model=MatchSummaryOut)
def run_match(cycle_id: UUID, user: User, repo: Repo, background: BackgroundTasks) -> dict[str, Any]:
    """Starts matching every statement line in the background (rules 1 to 10); poll
    `GET .../match-summary` for progress. Refused (409) until the statement is confirmed. A person's links
    and edits are kept."""
    cycle = load_cycle(repo, cycle_id)
    try:
        start_matching(repo, cycle)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    note_edit(repo, cycle, user.email)  # a new run on an exported reconciliation is an edit
    background.add_task(run_matching, repo, cycle, user.email)
    return match_summary(repo, str(cycle_id), load_cycle(repo, cycle_id))


@router.get("/cycles/{cycle_id}/match-summary", response_model=MatchSummaryOut)
def get_match_summary(cycle_id: UUID, user: User, repo: Repo) -> dict[str, Any]:
    """Lines and amounts by status (all zero before matching has run), and the matching run if there is one."""
    return match_summary(repo, str(cycle_id), load_cycle(repo, cycle_id))
