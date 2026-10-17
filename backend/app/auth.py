"""Supabase JWT verification and the email allow-list.

Tokens are signed by the project's asymmetric signing keys and verified against the
project's JWKS (public keys) endpoint, so no secret is needed here. Because public
sign-ups stay enabled on the shared Supabase project, the allow-list is the only gate:
an empty ALLOWED_EMAILS allows nobody.
"""

import logging
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, PyJWKClientConnectionError
from pydantic import BaseModel

from app.config import Settings, get_settings

# Asymmetric algorithms only: a token claiming HS256 or "none" is rejected.
ALGORITHMS = ["ES256", "RS256"]
AUDIENCE = "authenticated"
# Clock skew allowed between this server and Supabase when checking exp / iat / nbf. A token is
# stamped with Supabase's clock, so a server clock a second behind would otherwise reject a
# token issued moments ago ("not yet valid").
LEEWAY_SECONDS = 30

logger = logging.getLogger("app.auth")

NOT_ALLOWED_MESSAGE = "Your account is not allowed to use this app"

bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    email: str
    user_id: str


@lru_cache
def get_jwk_client(jwks_url: str) -> PyJWKClient:
    # Caches the key set for an hour; an unknown key id triggers one refetch (key rotation).
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=3600, timeout=10)


def _unauthorized(detail: str = "Invalid or missing token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CurrentUser:
    """401 for no/bad token, 403 for a valid token whose email is not on the allow-list."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Not authenticated")

    if not settings.supabase_url or not settings.supabase_jwks_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on the server",
        )

    token = credentials.credentials
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1"
    try:
        signing_key = get_jwk_client(settings.supabase_jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=ALGORITHMS,
            audience=AUDIENCE,
            issuer=issuer,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "sub"]},
        )
    except PyJWKClientConnectionError:
        logger.warning("Token check failed: could not reach the JWKS endpoint")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach the authentication key service",
        ) from None
    except jwt.PyJWTError as exc:
        # The client only ever sees a generic 401; the real reason goes to the server log.
        # The token itself is never logged.
        logger.warning("Token rejected: %s: %s", type(exc).__name__, exc)
        raise _unauthorized() from None

    email = str(claims.get("email") or "").strip().lower()
    if not email or email not in settings.allowed_email_list:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NOT_ALLOWED_MESSAGE)

    return CurrentUser(email=email, user_id=str(claims["sub"]))
