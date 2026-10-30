from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth import CurrentUser, get_current_user

router = APIRouter()


@router.get("/me")
def me(user: Annotated[CurrentUser, Depends(get_current_user)]) -> dict[str, str]:
    return {"email": user.email}
