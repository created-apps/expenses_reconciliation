"""Auth tests. Tokens are signed with a throwaway EC key and a fake JWKS client is injected,
so nothing here talks to Supabase."""

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from jwt import PyJWKClientConnectionError, PyJWKClientError

from app import auth
from app.config import Settings, get_settings
from app.main import app

SUPABASE_URL = "https://abc.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
ALLOWED = "harsh@create-ed.in"

_private = ec.generate_private_key(ec.SECP256R1())
_other_private = ec.generate_private_key(ec.SECP256R1())


class FakeJwkClient:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def get_signing_key_from_jwt(self, token: str):
        if self.error:
            raise self.error
        return SimpleNamespace(key=_private.public_key())


def make_token(*, email: str | None = ALLOWED, key=_private, alg="ES256", **overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": "11111111-2222-3333-4444-555555555555",
        "aud": "authenticated",
        "iss": ISSUER,
        "iat": now,
        "exp": now + 3600,
        "role": "authenticated",
    }
    if email is not None:
        claims["email"] = email
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": "test-key"})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(monkeypatch):
    settings = Settings(
        supabase_url=SUPABASE_URL,
        supabase_jwks_url=f"{ISSUER}/.well-known/jwks.json",
        allowed_emails=f"{ALLOWED}, Second.User@create-ed.in",
        _env_file=None,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(auth, "get_jwk_client", lambda url: FakeJwkClient())
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_no_token_is_401(client):
    response = client.get("/api/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_garbage_token_is_401(client):
    assert client.get("/api/me", headers=bearer("not-a-jwt")).status_code == 401


def test_allowed_user_gets_email(client):
    response = client.get("/api/me", headers=bearer(make_token()))
    assert response.status_code == 200
    assert response.json() == {"email": ALLOWED}


def test_email_match_ignores_case_and_allow_list_spacing(client):
    response = client.get("/api/me", headers=bearer(make_token(email="SECOND.user@Create-ED.in")))
    assert response.status_code == 200
    assert response.json() == {"email": "second.user@create-ed.in"}


def test_valid_token_but_email_not_allowed_is_403(client):
    response = client.get("/api/me", headers=bearer(make_token(email="recon-blocked-test@example.com")))
    assert response.status_code == 403
    assert response.json()["detail"] == "Your account is not allowed to use this app"


def test_token_without_email_is_403(client):
    assert client.get("/api/me", headers=bearer(make_token(email=None))).status_code == 403


def test_expired_token_is_401(client):
    token = make_token(exp=int(time.time()) - 120)  # well outside the 30 s clock-skew allowance
    assert client.get("/api/me", headers=bearer(token)).status_code == 401


def test_token_issued_a_moment_in_the_future_is_accepted(client):
    # Server clock a few seconds behind Supabase: iat looks like it is in the future.
    now = int(time.time())
    token = make_token(iat=now + 5)
    assert client.get("/api/me", headers=bearer(token)).status_code == 200


def test_token_issued_far_in_the_future_is_401(client):
    token = make_token(iat=int(time.time()) + 3600)
    assert client.get("/api/me", headers=bearer(token)).status_code == 401


def test_rejection_reason_is_logged_without_the_token(client, caplog):
    token = make_token(aud="something-else")
    with caplog.at_level("WARNING", logger="app.auth"):
        assert client.get("/api/me", headers=bearer(token)).status_code == 401
    assert "InvalidAudienceError" in caplog.text
    assert token not in caplog.text


def test_wrong_audience_is_401(client):
    assert client.get("/api/me", headers=bearer(make_token(aud="something-else"))).status_code == 401


def test_wrong_issuer_is_401(client):
    token = make_token(iss="https://other.supabase.co/auth/v1")
    assert client.get("/api/me", headers=bearer(token)).status_code == 401


def test_token_signed_with_another_key_is_401(client):
    assert client.get("/api/me", headers=bearer(make_token(key=_other_private))).status_code == 401


def test_hs256_token_is_rejected(client):
    token = jwt.encode(
        {"sub": "x", "aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 60, "email": ALLOWED},
        "a-shared-secret-that-is-long-enough-for-hs256",
        algorithm="HS256",
        headers={"kid": "test-key"},
    )
    assert client.get("/api/me", headers=bearer(token)).status_code == 401


def test_unknown_key_id_is_401(client, monkeypatch):
    monkeypatch.setattr(auth, "get_jwk_client", lambda url: FakeJwkClient(PyJWKClientError("no such key")))
    assert client.get("/api/me", headers=bearer(make_token())).status_code == 401


def test_jwks_unreachable_is_503(client, monkeypatch):
    monkeypatch.setattr(auth, "get_jwk_client", lambda url: FakeJwkClient(PyJWKClientConnectionError("down")))
    assert client.get("/api/me", headers=bearer(make_token())).status_code == 503


def test_empty_allow_list_allows_nobody(monkeypatch):
    settings = Settings(supabase_url=SUPABASE_URL, supabase_jwks_url="x", allowed_emails="", _env_file=None)
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(auth, "get_jwk_client", lambda url: FakeJwkClient())
    try:
        assert TestClient(app).get("/api/me", headers=bearer(make_token())).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_auth_not_configured_is_503():
    settings = Settings(supabase_url="", supabase_jwks_url="", allowed_emails=ALLOWED, _env_file=None)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        assert TestClient(app).get("/api/me", headers=bearer(make_token())).status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_health_needs_no_token():
    assert TestClient(app).get("/api/health").status_code == 200
