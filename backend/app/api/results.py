from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from app.api.cycles import load_cycle
from app.auth import CurrentUser, get_current_user
from app.db import SupabaseRepo, get_repo
from app.schemas import ResolveIn, TransactionOut, TransactionsOut, UnusedInvoicesOut
from app.services.gates import ServiceError
from app.services.results import resolve, transactions_view, unused_view

router = APIRouter(tags=["results"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Repo = Annotated[SupabaseRepo, Depends(get_repo)]


@router.get("/cycles/{cycle_id}/transactions", response_model=TransactionsOut)
async def list_transactions(
    cycle_id: UUID,
    user: User,
    repo: Repo,
    status: str | None = Query(default=None, description="One of the eight statuses"),
    vendor: str | None = Query(default=None, description="Vendor key"),
    card: str | None = Query(default=None, description="Last four digits of the card"),
    q: str | None = Query(default=None, max_length=100, description="Words to find in description, amount, note, file name"),
) -> dict[str, Any]:
    """The statement lines with their attached and suggested invoices and the sum against the charge."""
    cycle = await run_in_threadpool(load_cycle, repo, cycle_id)
    return await run_in_threadpool(lambda: transactions_view(repo, cycle, status=status, vendor=vendor, card=card, q=q))


@router.post("/transactions/{transaction_id}/resolve", response_model=TransactionOut)
async def resolve_transaction(transaction_id: UUID, body: ResolveIn, user: User, repo: Repo) -> dict[str, Any]:
    """Attach or detach invoices, set a status, write a note. `preview: true` changes nothing and returns the
    line as it would be. Refused (409) while matching runs or when the line has not been matched yet."""
    line = await run_in_threadpool(repo.get_transaction, str(transaction_id))
    if line is None:
        raise HTTPException(404, "Statement line not found")
    cycle = await run_in_threadpool(load_cycle, repo, UUID(line["cycle_id"]))
    try:
        return await run_in_threadpool(
            resolve, repo, cycle, str(transaction_id), body.model_dump(), user.email
        )
    except ServiceError as exc:
        raise HTTPException(exc.status_code, exc.message) from None


@router.get("/cycles/{cycle_id}/unused-invoices", response_model=UnusedInvoicesOut)
async def list_unused_invoices(
    cycle_id: UUID,
    user: User,
    repo: Repo,
    q: str | None = Query(default=None, max_length=100),
    vendor: str | None = Query(default=None),
) -> dict[str, Any]:
    """Read invoices no line uses (a Review suggestion reserves its invoices), each with the reason."""
    cycle = await run_in_threadpool(load_cycle, repo, cycle_id)
    return await run_in_threadpool(lambda: unused_view(repo, cycle, q=q, vendor=vendor))
