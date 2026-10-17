# Reconcile

Credit-card expense reconciliation for the accounts team: an ICICI statement PDF plus a month of invoices in, a reconciled Excel out.

Start with `doc/README.md`. `doc/project_context.md` is the source of truth; `doc/memory.md` records approved progress.

```
doc/        documentation, prototype reference scripts, expected results
supabase/   SQL migrations (run by hand in the Supabase SQL editor)
backend/    FastAPI API and the pure-Python engine
frontend/   React + Vite app
```

## Requirements

- Python 3.11+ (local), Node 22+, Docker Desktop.
- poppler (`pdftotext`) is **not** needed locally. Anything that needs it runs in Docker (see below).

## Backend (local)

PowerShell, from the repo root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env        # then fill in values (optional for Slice 0)
uvicorn app.main:app --reload
```

Open <http://localhost:8000/api/health>. It returns `{"status":"ok","version":"0.1.0"}`. API docs: <http://localhost:8000/api/docs>.

Quick tests that don't need poppler: `pytest` (inside the activated venv). The tests that read the real June and September files are skipped here and run in Docker.

**Uploading invoices needs poppler** (the API reads each PDF's text to spot a copy of the statement), so from Slice 4 run the API in Docker rather than with `uvicorn`: stop any local `uvicorn` first (it holds port 8000), then `docker compose up --build api`. The API container reads `backend/.env` for the Supabase settings.

## Frontend (local)

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local  # then fill in values (optional for Slice 0)
npm run dev                         # http://localhost:5173
npm run build                       # type-checks, then builds
```

## Docker

```powershell
# Build and run the API image (no .env: only /api/health will work; use compose below for the real app)
docker build -t recon-api backend
docker run --rm -p 8000:8000 recon-api
docker run --rm recon-api pdftotext -v      # prints the poppler version

# Same thing through compose
docker compose up --build api

# Run the whole test suite inside the container (poppler available)
docker compose run --rm tests
docker compose run --rm tests pytest tests/test_statement.py -v
```

The `tests` service mounts `backend/` (so `backend/tests/fixtures_private/` is visible) and `doc/` read-only at `/doc`.

## Deploy

The API runs on Railway (`backend/railway.toml`, Dockerfile build, root directory `backend`) and the web app on Vercel (`frontend/vercel.json`, root directory `frontend`). Every environment variable is set by the owner in those dashboards. The steps, the variable list, adding a user, rotating keys and what to do when a statement does not reconcile are in `doc/runbook.md`.

## Real client files

Statements, invoices and Amazon reports go only in `backend/tests/fixtures_private/`. Everything in that folder except `.gitkeep` is git-ignored and excluded from Docker images. Never commit these files, and keep this repository private.

## Environment variables

Listed in `backend/.env.example` and `frontend/.env.example`. The Supabase service-role key and the Anthropic key live only in `backend/.env`. The frontend gets only the Supabase URL and anon key (for login).
