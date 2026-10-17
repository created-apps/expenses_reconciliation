from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.cycles import load_cycle
from app.auth import CurrentUser, get_current_user
from app.db import SupabaseRepo, get_repo
from app.schemas import InvoicePatch, InvoicesOut
from app.services.gates import ServiceError, note_edit
from app.services.invoices import (
    correct_invoice,
    invoices_view,
    mark_not_an_invoice,
    restore_file,
    run_extract,
    start_extract,
)
from app.services.vision_client import AnthropicVision, get_vision
from app.storage import SupabaseStorage, get_storage

router = APIRouter(tags=["invoices"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Repo = Annotated[SupabaseRepo, Depends(get_repo)]
Storage = Annotated[SupabaseStorage, Depends(get_storage)]
Vision = Annotated[AnthropicVision | None, Depends(get_vision)]


def _load_invoice(repo: SupabaseRepo, invoice_id: UUID) -> dict[str, Any]:
    invoice = repo.get_invoice(str(invoice_id))
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return invoice


@router.post("/cycles/{cycle_id}/invoices/extract", status_code=status.HTTP_202_ACCEPTED, response_model=InvoicesOut)
def extract_invoices_endpoint(
    cycle_id: UUID, user: User, repo: Repo, storage: Storage, vision: Vision, background: BackgroundTasks
) -> dict[str, Any]:
    """Starts reading the invoice files in the background; poll `GET .../invoices` for progress.
    Refused (409) until the statement is confirmed. Images are read by the AI when it is set up."""
    cycle = load_cycle(repo, cycle_id)
    try:
        start_extract(repo, cycle)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    note_edit(repo, cycle, user.email)  # reading again on an exported reconciliation is an edit
    background.add_task(run_extract, repo=repo, storage=storage, cycle_id=cycle["id"], actor=user.email, vision=vision)
    return invoices_view(repo, load_cycle(repo, cycle_id))


@router.get("/cycles/{cycle_id}/invoices", response_model=InvoicesOut)
def list_invoices(cycle_id: UUID, user: User, repo: Repo) -> dict[str, Any]:
    return invoices_view(repo, load_cycle(repo, cycle_id))


@router.patch("/invoices/{invoice_id}", response_model=InvoicesOut)
def patch_invoice(invoice_id: UUID, body: InvoicePatch, user: User, repo: Repo) -> dict[str, Any]:
    invoice = _load_invoice(repo, invoice_id)
    cycle = load_cycle(repo, UUID(invoice["cycle_id"]))
    try:
        correct_invoice(repo, cycle, invoice, body.model_dump(exclude_unset=True), user.email)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    return invoices_view(repo, load_cycle(repo, UUID(invoice["cycle_id"])))


@router.post("/files/{file_id}/restore", response_model=InvoicesOut)
def restore_set_aside_file(file_id: UUID, user: User, repo: Repo) -> dict[str, Any]:
    """Bring back a file that was set aside with "Not an invoice". Read invoices again to read it."""
    file = repo.get_file(str(file_id))
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    cycle = load_cycle(repo, UUID(file["cycle_id"]))
    try:
        restore_file(repo, cycle, file, user.email)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    return invoices_view(repo, load_cycle(repo, UUID(file["cycle_id"])))


@router.post("/invoices/{invoice_id}/not-invoice", response_model=InvoicesOut)
def not_an_invoice(invoice_id: UUID, user: User, repo: Repo) -> dict[str, Any]:
    invoice = _load_invoice(repo, invoice_id)
    cycle = load_cycle(repo, UUID(invoice["cycle_id"]))
    try:
        mark_not_an_invoice(repo, cycle, invoice, user.email)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    return invoices_view(repo, load_cycle(repo, UUID(invoice["cycle_id"])))
