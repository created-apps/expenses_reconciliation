from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.cycles import load_cycle
from app.auth import CurrentUser, get_current_user
from app.db import SupabaseRepo, get_repo
from app.schemas import StatementOut
from app.services.statement import StatementError, confirm_statement, run_parse, start_parse, statement_view
from app.storage import SupabaseStorage, get_storage

router = APIRouter(prefix="/cycles/{cycle_id}/statement", tags=["statement"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Repo = Annotated[SupabaseRepo, Depends(get_repo)]
Storage = Annotated[SupabaseStorage, Depends(get_storage)]


@router.post("/parse", status_code=status.HTTP_202_ACCEPTED, response_model=StatementOut)
def parse_statement_endpoint(
    cycle_id: UUID, user: User, repo: Repo, storage: Storage, background: BackgroundTasks
) -> dict[str, Any]:
    """Starts reading the statement in the background; poll `GET .../statement` for progress."""
    cycle = load_cycle(repo, cycle_id)
    try:
        file = start_parse(repo, cycle)
    except StatementError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    background.add_task(run_parse, repo=repo, storage=storage, cycle_id=cycle["id"], file=file, actor=user.email)
    return statement_view(repo, load_cycle(repo, cycle_id))


@router.get("", response_model=StatementOut)
def get_statement(cycle_id: UUID, user: User, repo: Repo) -> dict[str, Any]:
    return statement_view(repo, load_cycle(repo, cycle_id))


@router.post("/confirm", response_model=StatementOut)
def confirm_statement_endpoint(cycle_id: UUID, user: User, repo: Repo) -> dict[str, Any]:
    cycle = load_cycle(repo, cycle_id)
    try:
        confirm_statement(repo, cycle, user.email)
    except StatementError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    return statement_view(repo, load_cycle(repo, cycle_id))
