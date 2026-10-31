from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.auth import CurrentUser, get_current_user
from app.db import SupabaseRepo, get_repo
from app.schemas import VendorCreate, VendorOut
from app.services.gates import ServiceError
from app.services.vendors import add_vendor

router = APIRouter(tags=["vendors"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Repo = Annotated[SupabaseRepo, Depends(get_repo)]


@router.post("/vendors", response_model=VendorOut)
def create_vendor(body: VendorCreate, user: User, repo: Repo) -> VendorOut:
    """Adds a vendor to the shared vendor list (or returns the one with that name). Matching must be run again
    for statement lines to pick it up."""
    try:
        row = add_vendor(repo, body.name, body.statement_text, user.email)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    return VendorOut(key=row["vendor_key"], name=row["display_name"])
