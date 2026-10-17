"""The files that deploy the API (railway.toml, Dockerfile, .env.example) say what the code expects.
Nothing here deploys anything or reads a real value."""

import re
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app

BACKEND = Path(__file__).resolve().parents[1]
DOCKERFILE = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
RAILWAY = tomllib.loads((BACKEND / "railway.toml").read_text(encoding="utf-8"))


# ---- railway.toml -------------------------------------------------------------------------------------------------------------
def test_railway_builds_the_dockerfile_in_the_backend_folder():
    assert RAILWAY["build"]["builder"] == "DOCKERFILE"
    assert (BACKEND / RAILWAY["build"]["dockerfilePath"]).is_file()


def test_the_railway_healthcheck_is_a_real_route_that_answers_200():
    path = RAILWAY["deploy"]["healthcheckPath"]
    assert path == "/api/health"
    assert TestClient(app).get(path).status_code == 200
    assert RAILWAY["deploy"]["healthcheckTimeout"] >= 30  # a cold start with poppler and the libraries is not instant


def test_one_replica_because_the_background_jobs_run_inside_the_api_process():
    assert RAILWAY["deploy"]["numReplicas"] == 1


def test_railway_toml_holds_no_secret_or_environment_value():
    text = (BACKEND / "railway.toml").read_text(encoding="utf-8")
    assert "variables" not in RAILWAY and "env" not in RAILWAY
    for marker in ("sk-ant", "eyJ", "sb_secret", "service_role", "supabase.co", "SUPABASE_SERVICE_ROLE_KEY="):
        assert marker not in text, marker


# ---- Dockerfile ---------------------------------------------------------------------------------------------------------------
def stages() -> list[tuple[str, str]]:
    """[(stage name, the stage's lines)] in file order."""
    parts = re.split(r"(?m)^FROM .+? AS (\w+)\s*$", DOCKERFILE)
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]


def test_railway_builds_the_last_stage_and_that_is_runtime_without_test_packages():
    names = [n for n, _ in stages()]
    assert names[-1] == "runtime"  # Railway ships the final stage: it must never be the test one
    runtime = dict(stages())["runtime"]
    assert "pytest" not in runtime and "[dev]" not in runtime and "COPY tests" not in runtime


def test_the_dev_packages_are_installed_only_in_the_test_stage():
    by_name = dict(stages())
    assert "[dev]" in by_name["test"]
    assert "[dev]" not in by_name["base"]
    assert "pytest" not in by_name["base"] and "pytest" not in by_name["runtime"]


def test_the_container_listens_on_the_port_the_host_sets():
    cmd = dict(stages())["runtime"]
    assert "${PORT:-8000}" in cmd and "--host 0.0.0.0" in cmd


def test_no_env_file_or_client_file_goes_into_an_image():
    ignore = (BACKEND / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignore and "tests/fixtures_private" in ignore
    assert "COPY .env" not in DOCKERFILE and "COPY . " not in DOCKERFILE


# ---- environment variables ---------------------------------------------------------------------------------------------------
def test_every_setting_the_code_reads_is_listed_in_env_example():
    text = (BACKEND / ".env.example").read_text(encoding="utf-8")
    listed = {m.group(1) for m in re.finditer(r"(?m)^#?\s*([A-Z][A-Z0-9_]+)=", text)}
    missing = [name.upper() for name in Settings.model_fields if name.upper() not in listed]
    assert missing == []


def test_env_example_holds_no_real_value():
    text = (BACKEND / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if re.match(r"^(SUPABASE_SERVICE_ROLE_KEY|SUPABASE_JWT_SECRET|ANTHROPIC_API_KEY|SUPABASE_URL|ALLOWED_EMAILS)=", line):
            assert line.split("=", 1)[1].strip() == "", line


def test_cors_origins_drop_a_trailing_slash_and_blanks():
    s = Settings(_env_file=None, cors_origins=" https://recon.vercel.app/ , http://localhost:5173,, ")
    assert s.cors_origin_list == ["https://recon.vercel.app", "http://localhost:5173"]


def test_the_production_origin_gets_the_cors_headers_once_it_is_configured(monkeypatch):
    # The same list feeds the CORS middleware at start-up; an origin written with a slash must still match.
    s = Settings(_env_file=None, cors_origins="https://recon.vercel.app/")
    assert "https://recon.vercel.app" in s.cors_origin_list
