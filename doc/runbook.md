# Runbook

How to deploy Reconcile, add a user, rotate keys, and what to do when a statement does not reconcile. Written for the owner of the Railway, Vercel and Supabase accounts.

**Rule for everything below: you type every secret value yourself, in the Railway, Vercel or Supabase dashboard. Never paste a key into chat, an issue, a commit or a screenshot.** The repository is private; keep it private (it holds the client's expected results under `doc/reference/`).

## 1. What runs where

| Piece | Where | Configured by |
|---|---|---|
| API (FastAPI + poppler) | Railway, Docker image built from `backend/Dockerfile` | `backend/railway.toml` and Railway Variables |
| Web app (React + Vite) | Vercel, built from `frontend/` | `frontend/vercel.json` and Vercel Environment Variables |
| Database, login, file storage | Supabase (shared project): tables `recon_*`, bucket `recon-files` | `supabase/migrations/0001` to `0004` |
| Reading images | Anthropic API, called only by the API | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |

The browser talks only to the API (and to Supabase for sign-in). The Supabase service-role key and the Anthropic key exist only in Railway.

**Never touch** the tables `payment_requests` and `payment_webhook_events` of the shared Supabase project.

## 2. Variables

Railway (API service). Set each in Railway > the service > Variables:

| Variable | Value |
|---|---|
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | the project's secret (service-role) key. **Secret** |
| `SUPABASE_JWKS_URL` | `https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json` |
| `ALLOWED_EMAILS` | comma-separated login emails, for example `harsh@create-ed.in`. An empty list allows nobody |
| `ANTHROPIC_API_KEY` | **Secret** |
| `ANTHROPIC_MODEL` | an exact model ID, for example `claude-sonnet-5-5` (no quotes, no spaces) |
| `CORS_ORIGINS` | the Vercel URL, origin only: `https://<name>.vercel.app` (no path; a trailing slash is ignored). Several origins: comma-separated |
| `STORAGE_BUCKET` | `recon-files` (the default; set only if different) |

Railway sets `PORT` itself. The upload limits (`MAX_FILE_MB`, `MAX_REQUEST_MB`, `MAX_ZIP_TOTAL_MB`, `MAX_ZIP_ENTRIES`, `SIGNED_URL_SECONDS`) have defaults; set them only to change them.

Vercel (project > Settings > Environment Variables, for Production). They are read **when the app is built**, so after changing one, redeploy:

| Variable | Value |
|---|---|
| `VITE_SUPABASE_URL` | the same Supabase URL |
| `VITE_SUPABASE_ANON_KEY` | the project's anon (publishable) key. Public by design: it is only used to sign in |
| `VITE_API_BASE_URL` | the Railway public URL, `https://<service>.up.railway.app` (no trailing slash) |

## 3. Deploy for the first time

Do these in order.

1. **Supabase, database.** In the SQL editor run `0001` to `0004` from `supabase/migrations/` if they have not run (each is safe to run twice). Each file ends with a verification query. Run `0004` **before** the API is deployed: the API writes `recon_cycles.job_kind`.
2. **Railway, API.**
   1. New Project > Deploy from GitHub repo > pick this repository.
   2. Service > Settings > Source > **Root Directory = `backend`**. Railway then reads `backend/railway.toml` (Dockerfile build, health check `/api/health`, one replica).
   3. Variables: add the Railway variables from section 2. Leave `CORS_ORIGINS` as `http://localhost:5173` for now.
   4. Settings > Networking > **Generate Domain**. Note the URL.
   5. Wait for the deployment to turn green. Open `https://<service>.up.railway.app/api/health`: it must show `{"status":"ok","version":"0.1.0"}`.
3. **Vercel, web app.**
   1. Add New > Project > import the same repository.
   2. **Root Directory = `frontend`**. Framework Preset: Vite (also set by `frontend/vercel.json`). Node.js version: 22.x.
   3. Add the three `VITE_*` variables from section 2 (the Railway URL from step 2.4 goes into `VITE_API_BASE_URL`).
   4. Deploy. Note the URL, for example `https://<name>.vercel.app`.
4. **Railway again.** Set `CORS_ORIGINS` to the Vercel URL. Railway redeploys by itself. Without this the browser blocks every call (the console shows a CORS error).
5. **Supabase, Auth.** Authentication > URL Configuration > **add** the Vercel URL to the Redirect URLs list. **Do not change the Site URL**: the project is shared with another app. The app signs in with email and password only, so this matters little, but keep the list complete.
6. **Smoke test.** Open the Vercel URL, sign in with an allowed email, and the home list loads. Then run the acceptance tests of Slice 12 (`doc/implementation_plan.md`).

Every `git push` to the connected branch redeploys both services. Railway keeps the old deployment until the new one passes its health check.

## 4. Add (or remove) a user

1. Supabase > Authentication > Users > **Add user** > Create new user: the email and a password the person will use (tick auto-confirm). Public sign-ups are open on the shared project, so anyone can create an account, but only the emails in `ALLOWED_EMAILS` get past the API.
2. Railway > Variables > `ALLOWED_EMAILS`: append the email (comma-separated, no spaces needed, case does not matter). Railway redeploys.
3. The person signs in. If they see "Your account is not allowed to use this app" the email is not in the list or has a typo. If they see "could not be verified" the account or the Supabase variables are wrong.

To remove someone: delete their email from `ALLOWED_EMAILS` (that alone stops access), then remove the user in Supabase if they should not exist at all.

## 5. Rotate keys

General order: **create the new key, put it in Railway/Vercel, wait for a healthy deployment, test, and only then revoke the old key.** If a key was ever exposed (pasted somewhere, committed, shown in a screenshot) rotate it at once and revoke the old one.

| Key | How | Test afterwards |
|---|---|---|
| Supabase service-role (secret) key | Supabase > Project Settings > API Keys: create a new secret key, set `SUPABASE_SERVICE_ROLE_KEY` in Railway, then delete the old key. If the project still uses the legacy `service_role` JWT key, do **not** regenerate it without checking: it is shared with the other app in this project | `/api/health`; open a reconciliation (the list loads) |
| Anthropic key | console.anthropic.com > API keys: create a new key, set `ANTHROPIC_API_KEY` in Railway, delete the old key | Invoices step > Read invoices on a cycle with an image: no message such as "The AI service did not accept the API key" |
| Supabase anon key | Only if it must change: set `VITE_SUPABASE_ANON_KEY` in Vercel and **redeploy** (it is baked in at build time) | Sign in |
| User token signing keys | Supabase manages them and the API reads the public keys from `SUPABASE_JWKS_URL`; nothing to change here | Sign in |

Check that a key is not in the code: no key value is ever in a committed file (`backend/.env` and `frontend/.env.local` are git-ignored). Test 12.3 searches the built JavaScript for `service_role`.

## 6. A statement does not reconcile

On the Statement step, **Confirm is disabled** and a banner shows the two totals and the difference: the lines the app read do not add up to the totals printed on the statement's first page (debits = Purchases/Charges + Cash Advances, credits = Payments/Credits). Nothing can be matched until this is resolved; do not try to work around it.

1. **Is it the right file?** The statement for this month, from net banking, as a PDF with selectable text (not a photo, not a printout scanned to PDF, not another card's statement). Replace it and read again.
2. **Read the difference.** The banner says whether the lines are short or over, and by how much.
   - A difference equal to one transaction's amount: the app missed that line. Look at the PDF for a line that is wrapped over several rows or has an unusual currency note.
   - A difference equal to cash advances or fees: report it; the totals rule may need a new term.
   - A very large difference: the wrong period or a partial file.
3. **Read again** once (a transient failure can leave a half-read job).
4. **Still different?** Send the PDF to the developer (it contains the client's financial data: through the agreed private channel only, never a public place) with the difference shown. The fix is in `backend/app/engine/statement_icici.py` and gets a test on that statement. The lines are never edited by hand in the app.

## 7. Everyday operations

- **Logs:** Railway > the service > Deployments > View logs. Errors from the data service show as `Upstream error ...`; the Anthropic key is never logged.
- **Roll back:** Railway > Deployments > pick the last good deployment > Redeploy. Vercel > Deployments > Promote to Production. Migrations are additive, so the previous code keeps working.
- **One API replica only.** The background jobs (reading the statement, reading invoices, matching) run inside the API process and keep their lock in the database. A job that stops moving for 3 minutes is shown as failed and can be started again.
- **Large uploads.** The June ZIP is about 12 MB. The API accepts up to `MAX_REQUEST_MB` (400); anything near that has not been tried on Railway.
- **AI cost.** June's 12 images cost about $0.05.
- **Where the data is.** Tables `recon_*` and the private bucket `recon-files` in Supabase. Deleting a reconciliation removes its rows and its files. An exported reconciliation cannot be deleted from the app.

## 8. When something is wrong

| Symptom | Likely cause and fix |
|---|---|
| Browser console: CORS error, every call fails | `CORS_ORIGINS` in Railway is not exactly the Vercel origin. Fix and wait for the redeploy |
| Page says "The app is not configured: VITE_API_BASE_URL is missing" | The Vercel variable was missing at build time. Set it and redeploy |
| Sign-in fails, or "Your session could not be verified" | Wrong `VITE_SUPABASE_*` values, or `SUPABASE_JWKS_URL` wrong or unreachable from Railway; also check the PC clock |
| "Your account is not allowed to use this app" (403) | The email is not in `ALLOWED_EMAILS` |
| 503 "Storage is not configured on the server" | `SUPABASE_URL` or `SUPABASE_SERVICE_ROLE_KEY` is missing or wrong in Railway |
| 502 "The data service returned an error" | Supabase refused a call: check the Railway logs; a migration (0001 to 0004) may not have been run |
| Images stay "Waiting for AI" | `ANTHROPIC_API_KEY` or `ANTHROPIC_MODEL` is empty in Railway |
| An invoice upload says reading PDFs needs poppler | The API is not running from the Dockerfile image (poppler is installed there) |
| Railway deployment fails its health check | Open the deployment logs: usually a Python error at start-up or a build failure |
