from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend settings, read from environment variables or backend/.env.

    Every value has a safe default so the app can start without a .env file;
    features that need a value (Supabase, Anthropic) check it when they are used.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    supabase_url: str = ""
    supabase_service_role_key: SecretStr = SecretStr("")
    # Token verification: set the JWKS URL (asymmetric signing keys) or the legacy shared secret.
    supabase_jwks_url: str = ""
    supabase_jwt_secret: SecretStr = SecretStr("")

    allowed_emails: str = ""

    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = ""

    storage_bucket: str = "recon-files"
    cors_origins: str = "http://localhost:5173"

    # Upload limits (MB). A ZIP is also limited by its unpacked size and number of entries.
    max_file_mb: int = 50
    max_request_mb: int = 400
    max_zip_total_mb: int = 300
    max_zip_entries: int = 1000
    signed_url_seconds: int = 300

    @property
    def cors_origin_list(self) -> list[str]:
        # An origin has no path: a trailing slash (a common typo when pasting the Vercel URL) is dropped.
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
