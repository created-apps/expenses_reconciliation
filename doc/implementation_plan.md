# Implementation Plan: built and verified slice by slice

**Read first:** `project_context.md` (facts, rules, constraints), `architecture.md` (stack, tables, API), `flow.md` (flows), `design.md` (screens).

## How we work

1. The dev chat builds **one slice**, then posts:
   - (a) what changed;
   - (b) any migration SQL to run;
   - (c) the slice's manual test cases, copied from this file.
2. **The user runs all SQL** in the Supabase SQL editor. The dev chat only writes the migration files in `supabase/migrations/`.

   Every migration must:
   - be idempotent (`create table if not exists`, `on conflict do nothing`, and so on);
   - touch only `recon_*` objects and the `recon-files` bucket;
   - come with a **verification query** and a **rollback snippet**.
3. **The user runs the manual tests.** The next slice starts only after the user writes "Slice N verified". If a test fails, the fix stays in the same slice.
4. **No guessing.** If a test cannot be run (a missing file or access), the dev chat says so and asks.

## Test files used

Keep these in `backend/tests/fixtures_private/` (git-ignored) and on the tester's computer:

| Name | What |
|---|---|
| `CC_June_2026.pdf` | ICICI statement, 12 pages, period 21 May–28 Jun 2026 |
| `June2026_CC_invoice_1.zip` | 126 files (114 PDF, 12 PNG) |
| `june_2026_expected_results.csv` | Expected status and files per line (in `doc/reference/`) |
| `reconciliation_from_20260901_to_20260930_….csv` | Amazon Business CSV, September (133 rows) |
| `Tax invoice documents_from_2026-09-01_to_2026-09-30.zip` | Amazon bulk invoices, September (43 PDFs) |
| `september_2026_statement_lines_TEST_ONLY.csv` (in `doc/reference/`) | 25 September lines (14–28 Sep) typed from the statement screenshot. **Test data only**: it is not a bank document, and it is used only by `pytest` (slice 9) to test Amazon CSV mode. No September PDF exists, and none will be created |

The expected-results CSV comes from a reviewed prototype run. The tests compare **status and file names**. The notes can be worded differently.

---

## Slice 0: Repository skeleton (no SQL)

**Goal:** both apps run locally; the configuration is in place.

**Build:**

- Repo layout as in `architecture.md` §3. Copy `doc/` into the repo as is.
- **Backend:**
  - FastAPI app with `GET /api/health` returning `{"status":"ok","version":"0.1.0"}`.
  - Settings loaded from `.env` (`backend/.env.example` lists every variable in `architecture.md` §6).
  - CORS from `CORS_ORIGINS`.
  - A `Dockerfile` (python:3.12-slim with `poppler-utils`).
- **Frontend:**
  - Vite + React + TypeScript + Tailwind + shadcn/ui.
  - React Router with placeholder pages: `/login`, `/`, `/cycles/new`, `/cycles/:id`.
  - `.env.example`.
- **Root:**
  - `README.md` with local run commands.
  - `.gitignore` covering `.env*` (except examples), `fixtures_private/`, `node_modules`, `__pycache__`.

**Manual tests:**

| # | Steps | Expected |
|---|---|---|
| 0.1 | `cd backend`, install, run `uvicorn app.main:app --reload`; open `http://localhost:8000/api/health` | `{"status":"ok","version":"0.1.0"}` |
| 0.2 | `cd frontend`, `npm install`, `npm run dev`; open the shown URL | App loads; visiting `/login`, `/`, `/cycles/new` shows each placeholder title; no console errors |
| 0.3 | `docker build -t recon-api backend` then `docker run -p 8000:8000 recon-api`, and repeat 0.1 | Same health response; `docker run recon-api pdftotext -v` prints a poppler version |
| 0.4 | Run `git status` after creating `backend/.env` | `.env` is **not** listed (ignored) |

---

## Slice 1: Database and storage (SQL slice)

**Goal:** all `recon_*` tables, the private bucket and the vendor seed data exist. Existing tables are untouched.

**Migration files** (the user runs them in this order):

1. `0001_recon_core.sql`:
   - All tables in `architecture.md` §4, with the columns listed there, foreign keys (`on delete cascade` from `recon_cycles`), unique constraints, a CHECK on `recon_transactions.status` (the 8 values), and indexes on `cycle_id`.
   - `enable row level security` on every table, with **no policies**.
   - An `updated_at` trigger function named `recon_set_updated_at`.
2. `0002_recon_storage.sql`: insert bucket `recon-files` (`public = false`) into `storage.buckets` (`on conflict do nothing`). No storage policies; the backend uses the service role.
3. `0003_recon_seed_vendor_aliases.sql`: seed rows from `project_context.md` §5.2, with **both** `statement_pattern` (first table) and `invoice_pattern` (second table) per vendor.
   - `match_mode`:
     - `subset` for amazon (before 3, after 0) and indigo (before 3, after 1);
     - `none` for food/restaurants;
     - `single` for the rest (before 7, after 7).
   - Upsert on `vendor_key`.

**Manual tests (SQL editor):**

| # | Steps | Expected |
|---|---|---|
| 1.1 | **Before** running anything: `select count(*) from payment_requests;` and `select count(*) from payment_webhook_events;`. Write the numbers down | Two counts noted |
| 1.2 | Run 0001, 0002, 0003 in order | "Success. No rows returned" for each |
| 1.3 | `select table_name from information_schema.tables where table_schema='public' and table_name like 'recon_%' order by 1;` | Exactly: `recon_amazon_rows`, `recon_cycles`, `recon_events`, `recon_files`, `recon_invoices`, `recon_matches`, `recon_transactions`, `recon_vendor_aliases` |
| 1.4 | `select relname, relrowsecurity from pg_class where relname like 'recon_%' and relkind='r';` | All 8 rows show `true` |
| 1.5 | `select id, public from storage.buckets where id='recon-files';` | One row, `public = false` |
| 1.6 | `select vendor_key, match_mode from recon_vendor_aliases order by 1;` | Includes `amazon/subset`, `indigo/subset`, `macfos/single`, `dtdc/single`, `fathom/single`; food rows are `none` |
| 1.7 | Run all three files **again** | No errors; row count in 1.6 unchanged (idempotent) |
| 1.8 | Repeat the counts from 1.1 | Same numbers as before; existing tables untouched |
| 1.9 | Try a CHECK constraint: `insert into recon_cycles(label) values ('t') returning id;` then insert a transaction with `status='Wrong'` for that cycle | The transaction insert fails with a check-constraint error. Then `delete from recon_cycles where label='t';` |

**Rollback snippet** (kept in each file as a comment): drop the `recon_*` tables and function, and delete the bucket row. Only use it if asked.

---

## Slice 2: Login and app shell (no SQL)

**Goal:** only allowed users can sign in and call the API.

**Build:**

- **Frontend:**
  - Supabase email/password login.
  - The session is stored by supabase-js.
  - A protected-route wrapper.
  - A header with the user's email and **Sign out**.
- **Backend:**
  - `auth.py` verifies the Supabase JWT and checks the email against `ALLOWED_EMAILS`.
  - `GET /api/me` returns `{email}`.
  - 401 when there is no or a bad token; 403 when the email is not allowed.
- **Supabase:** public sign-ups **cannot** be turned off, because teammates use this shared project for other apps. The backend allow-list (`ALLOWED_EMAILS`, empty = nobody allowed) is therefore the only gate. The user creates the allowed users in Supabase Auth by hand, plus one non-allowed test user for test 2.4 (`recon-blocked-test@example.com`).
- **Token verification:** the project uses JWT signing keys, so the backend verifies tokens against the JWKS endpoint (`SUPABASE_JWKS_URL`, asymmetric algorithms ES256/RS256 only). `SUPABASE_JWT_SECRET` is not used.

**Manual tests:**

| # | Steps | Expected |
|---|---|---|
| 2.1 | Open `/` while logged out | Redirected to `/login` |
| 2.2 | Sign in with an allowed user | Lands on `/`; header shows the email |
| 2.3 | Wrong password | Inline error message; stays on the login page |
| 2.4 | Sign in with a real Supabase user **not** in `ALLOWED_EMAILS` | Message "Your account is not allowed to use this app"; data pages not shown |
| 2.5 | `curl http://localhost:8000/api/me` (no token) | HTTP 401 |
| 2.6 | Copy the access token (dev tools → Application → Local Storage → `sb-…-auth-token` → `access_token`); `curl -H "Authorization: Bearer <token>" …/api/me` | `{"email":"<your email>"}` |
| 2.7 | Click **Sign out**, then press browser Back | Back on `/login`; protected pages not shown |

---

## Slice 3: Import the v0 design (no SQL)

**Goal:** every screen from `design.md` exists with **mock data**, so the later slices only wire in real data.

**Source:** the v0 export in `doc/design_reference/` (mainly `page.tsx`) and `design.md`, which lists the tokens, what v0 delivered, what is missing, and which v0 behaviours to fix.

**Build:**

- Recreate the look of `page.tsx` as proper components in `frontend/src/components/`: AppShell (sidebar and small-screen top bar), PageHeader, Button variants, StatusBadge, CycleStatusBadge, Stepper, StatTile, StatusFilterTiles, FilterChips, UploadCard, FileRow, TransactionSheet, InvoiceSheet, Banner, JobProgress, TableSkeleton, EmptyState, KbdHint.
- No Next.js: no `metadata`, no `@vercel/analytics`, no `next.config`.
- Use the theme from `globals.css` with the dark-mode blocks removed, and load Inter.
- Wire the routes from `design.md` §3.
- Build the screens and states v0 did not deliver (`design.md` §5) and apply the fixes in §6.
- Use the mock data from `design.md` §8 (paise numbers, correct June values).
- Add `lib/format.ts`:
  - `formatINR(paise)` → `₹1,05,980.00` (en-IN grouping); credits as `−₹52,990.00`;
  - `formatDate(iso)` → `dd/mm/yyyy`.

**Manual tests:**

| # | Steps | Expected |
|---|---|---|
| 3.1 | Click through every screen and step with mock data | Matches the v0 design; no console errors; no Next.js imports remain (`grep -r "next/" frontend/src` returns nothing) |
| 3.2 | Look at mock amounts 10598000 and −5299000 paise | Shown as `₹1,05,980.00` and `−₹52,990.00` |
| 3.3 | Results screen: click the **Review** chip | Only Review rows shown; the chip looks active |
| 3.4 | Open a row drawer; press **Esc** | Drawer closes |
| 3.5 | Resize the window to tablet width (~900px) and then to 700px | Tables scroll horizontally; the drawer is full width; below `md` a top bar with a menu replaces the sidebar |
| 3.6 | Put `doc/design_reference/page.tsx` running in v0 (or its screenshots) next to the new app | Same colours, sizes, spacing and copy on home, upload, statement, invoices, results and export |
| 3.7 | Open the mock statement mismatch state, the Amazon report panel, the Unused invoices tab, Login, the loading skeleton and the job progress bar | Each exists and follows the same style (`design.md` §5) |
| 3.8 | Open the drawer for the ₹2,557.44 mock line | 8 attached invoices, each showing its own amount; Attached total ₹2,557.44; Difference ₹0.00 in green |
| 3.9 | Results with mock data: the first view | Review is selected (it has rows); an **All** option exists and shows all 10 mock lines |
| 3.10 | Run `npm run build` | Builds with type-checking on and no errors |

---

## Slice 4: Cycles and file upload (no SQL)

**Goal:** create a cycle and upload files to Storage, with ZIP expansion and duplicate detection.

**Build:**

- Endpoints:
  - `POST/GET /api/cycles`, `GET/DELETE /api/cycles/{id}`;
  - `POST/GET /api/cycles/{id}/files`;
  - `GET /api/files/{id}/url`.
- **Ingest** (`services/ingest.py`):
  - SHA-256 hash.
  - ZIP expansion: skip folders, `__MACOSX` and dot-files.
  - Allowed types: PDF, PNG, JPG/JPEG, CSV, ZIP.
  - A per-cycle duplicate-by-hash check.
  - Storage path `cycles/{cycle_id}/{file_id}/{original_name}`.
- **Statement-copy detection:** a file uploaded as an invoice whose PDF text contains both `CREDIT CARD STATEMENT` and `STATEMENT SUMMARY` gets `kind=ignored` and the note "copy of the statement".
- The upload screen and the Reconciliations list use the real API.

**Manual tests:**

| # | Steps | Expected |
|---|---|---|
| 4.1 | **New reconciliation** → upload `CC_June_2026.pdf` as the statement | One file listed, status *Uploaded* |
| 4.2 | Upload `June2026_CC_invoice_1.zip` as invoices | 126 files listed from the ZIP (plus the ZIP itself shown as the container); no errors |
| 4.3 | Check the file list (Invoices step) | `ACFrOg….pdf` shows as *Ignored – copy of the statement*. The two byte-identical copies `140626_Amazon_525.pdf` and `MH2727WI016880_GC001_10-Jun-2026.pdf` show as *Duplicate* (the first file of each pair stays *Uploaded*). All others *Uploaded* |
| 4.4 | Upload `CC_June_2026.pdf` again as the statement | Rejected or flagged as *Duplicate*; still one statement |
| 4.5 | Upload a `.docx` or `.txt` file | Rejected with "File type not supported" |
| 4.6 | SQL: `select kind, status, count(*) from recon_files group by 1,2 order by 1,2;` | statement/uploaded 1 · zip/processed 1 · invoice/uploaded 123 · invoice/duplicate 2 · ignored/duplicate 1 (the ZIP's statement copy is byte-identical to the statement PDF, so it is also a hash duplicate; it is still labelled *ignored*). The ZIP's other 123 + 2 files are its `invoice` rows |
| 4.7 | Supabase → Storage → `recon-files` → `cycles/<id>/…` | Files present; bucket private (a public URL does not open) |
| 4.8 | Click a file name in the app | Opens via a signed URL; the PDF or image displays |
| 4.9 | Home page | The new cycle appears with status *Draft* |
| 4.10 | Delete a **test** cycle (create a second one for this) | It disappears from the list; its rows are gone from `recon_files` (cascade) and its storage folder is removed |

---

## Slice 5: Statement parsing and check (no SQL)

**Goal:** the statement is read into lines, checked against its own summary, and confirmed by a person.

**Build:**

- `engine/statement_icici.py`, following `project_context.md` §5.1. **Reuse the proven logic** in `doc/reference/parse_stmt.py`, rewritten cleanly.
  - Read the statement date, the period and the four summary figures.
  - Find `date + serial` anywhere in a line.
  - Join continuation lines.
  - Track the card number.
  - Store all money as paise.
- **pytest:** `test_statement.py` asserts the June numbers below.
- Endpoints: `POST …/statement/parse` (background job with progress), `GET …/statement`, `POST …/statement/confirm`.
- Wire the Statement step screen.
- A statement that was read but not confirmed can be replaced (its lines are deleted and the cycle returns to `draft`). The Invoices step opens only after the statement is confirmed.

**Manual tests:**

| # | Steps | Expected |
|---|---|---|
| 5.1 | Open the June cycle → Statement step → **Read statement** | Progress shows, then the result |
| 5.2 | Summary tiles | Lines **127** · Debits **₹13,16,107.04 = ₹13,16,107.04 ✓** · Credits **₹5,91,066.42 = ₹5,91,066.42 ✓** · Cards **4002, 2492** |
| 5.3 | Header | Period **21/05/2026 – 28/06/2026**; statement date **28/06/2026** |
| 5.4 | Find SerNo **13488732741** | 27/05/2026 · `OPENAI *CHATGPT SUBSCR OPENAI.COM US` · ₹1,694.07 (proves sidebar text and wrapped lines are handled) |
| 5.5 | Find SerNo **13576983923** | 11/06/2026 · SGST-CI@9% · ₹117.00 · card **2492** |
| 5.6 | Find SerNo **13463193979** | SUPABASE SINGAPORE SG* · foreign **$86.12** · ₹8,695.94 (currency on the next line handled) |
| 5.7 | Find SerNo **13592897886** | ASSPL Bangalore IN · ₹52,990.00 · **credit** |
| 5.8 | SQL: `select count(*), count(distinct ser_no) from recon_transactions where cycle_id='<id>';` | `127, 127` |
| 5.9 | **Confirm statement** | Cycle status becomes *Statement confirmed*; the confirm time and user are shown |
| 5.10 | Negative test: in a test cycle, upload any other PDF (e.g. an invoice) as the statement and read it | Red banner; totals not found or not matching; **Confirm** disabled; no crash |
| 5.11 | `cd backend && pytest tests/test_statement.py` | All pass |

---

## Slice 6: Invoice extraction from PDFs (no SQL)

**Goal:** every PDF invoice becomes one or more invoice rows with the vendor, number, dates and total.

**Build:**

- `engine/invoices/*`, following `project_context.md` §5.3. **Reuse** `doc/reference/extract_inv.py`, cleanly.
  - **Amazon:** split per page block containing `Order Number`; take `Order Date`, `Invoice Number`, `Invoice Date` and the last `TOTAL:` row; detect credit notes.
  - **Macfos:** the `Total ₹` line and the invoice date.
  - **IndiGo:** `Grand Total`, `Date :`, `PNR :`.
  - **DTDC:** `Invoice Date`, `Total invoice Value`.
  - **Generic:** all money amounts, USD amounts, dates (numeric, `04-Jun-2026`, `June 20, 2026`) and the invoice number.
- **Validation** → `needs_check` when it fails.
- **Duplicates:** same vendor + invoice number + total → `duplicate_of`.
- PDFs without a text layer → treated like images (slice 7).
- `POST …/invoices/extract` runs as a background job. Images are skipped in this slice and left `pending`.
- Wire the Invoices step table, with filter chips.
- **Server-side gate:** `POST …/invoices/extract` returns **409** unless the cycle's statement is confirmed (the same check, `require_confirmed_statement`, is used by `POST …/match` when it is built in Slice 9). The `/cycles/:id/invoices` route redirects to the Statement step when the statement is not confirmed.
- **Statement totals check** (carried from Slice 5): debits must equal Purchases/Charges **+ Cash Advances**, both read from the PDF; the sum is stored in `recon_cycles.summary_purchases_paise` (no new column). June is unaffected (cash advances ₹0.00).
- **Cycle label** (carried from Slice 5): if the label is empty after a successful statement read, it is set from the statement date ("June 2026").
- `PATCH /api/invoices/{id}` corrects an invoice (it becomes *Manual*; re-reading keeps it) and `POST /api/invoices/{id}/not-invoice` sets a wrong upload aside as *Ignored*.

**Manual tests:**

| # | Steps | Expected |
|---|---|---|
| 6.0 | Open `/cycles/<draft-id>/invoices` by URL for a cycle whose statement is not confirmed. Then call `POST /api/cycles/<draft-id>/invoices/extract` (for example from `http://localhost:8000/api/docs`, signed in with *Authorize*, or with curl and your token) | The page redirects to the Statement step and the Invoices tab is locked. The extract call returns **409** "Confirm the statement first" |
| 6.1 | Invoices step → **Read invoices** | Progress over 123 files; finishes (111 PDFs + 12 images; the 2 duplicate files and the ignored statement copy are not read) |
| 6.2 | Counters | PDF invoices **112** (from 111 PDF files) · Images pending **12** · Duplicates **2** (file-level, from upload) · Ignored **1** · invoice-level duplicates **0** |
| 6.3 | SQL: `select count(*) from recon_invoices where cycle_id='<id>' and vendor_key='amazon' and source='pdf_text';` | **62** (61 Amazon PDF files; `280626_Amazon_1263.pdf` holds 2 invoices) |
| 6.4 | Open `280626_Amazon_1263.pdf` rows | Two invoices: **MAA4-1138 ₹349.00** and **MAA4-982422 ₹914.00**, both order 408-8124784-9796354 |
| 6.5 | Open `130626_Amazon_928.27.pdf` | Order 408-4454576-4641947 · invoice IN-9370 · 13/06/2026 · ₹928.27 |
| 6.6 | Open `190626_Macfos_715.pdf` | Total **₹611.00**, date 19/06/2026 (not 715; file names are not trusted) |
| 6.7 | Open `TaxInvoiceMH1262706AY53125.pdf` | IndiGo · ₹8,333.00 · 04/06/2026 · PNR YGDDKH |
| 6.8 | Open `DTDC_215.pdf` | DTDC · ₹215.01 |
| 6.9 | Open `Fathom $36.pdf` | Fathom · USD 36.00 · 20/06/2026 |
| 6.10 | Duplicates filter | Shows the 2 file-level duplicates from upload: one of each identical pair (`140626_Amazon_525.pdf` / `140626_Amazon_525(1).pdf` and `MH2727WI016880_GC001_10-Jun-2026.pdf` / `DTDC_488.pdf`; which name is kept depends on upload order). The invoice-level rule (same vendor + invoice no. + total → `duplicate_of`) stays in the code for re-downloaded copies with different bytes; June has 0 of these, so cover it with a unit test |
| 6.11 | Edit an invoice's total in the drawer, save, reload | The new value persists; source shows *Manual*; a `recon_events` row is written |
| 6.12 | `pytest tests/test_invoices.py` | All pass |

---

## Slice 7: Image invoices via AI vision (no SQL)

**Goal:** images (and PDFs without a text layer) are read by the vision model into the same fields. A person can correct them.

**Build:**

- `engine/invoices/vision.py`:
  - A prompt that returns strict JSON: `vendor`, `invoice_no`, `order_id`, `invoice_date`, `order_date`, `currency`, `total`.
  - A schema check; on failure, retry once, then `needs_check`.
  - The client is injected (model name from `ANTHROPIC_MODEL`).
- PDFs without text: render page 1 with `pdftoppm` and send it as an image.
- Results always show the source **Image-AI**.
- The model's answer is requested in the strict JSON format and checked again in the engine (types, real dates, amount). The vendor name it reads is resolved to a vendor with the same invoice patterns used for PDF text. The AI never decides a match.
- If `ANTHROPIC_API_KEY` or `ANTHROPIC_MODEL` is empty, images stay `pending` (no error). If the AI can't be used (wrong key, unreachable, refusal) the image becomes `needs_check` with the reason and the job still finishes.
- **No vendor name on the image → left for a person.** The vendor is never guessed and never taken from the file name. If the image prints none (June: 3 DTDC booking screenshots and the thinkrobotics order page), the vendor stays empty, the row is *Needs check* with the reason, and a person opens the file and chooses the vendor in the drawer.
- Reading again does **not** pay twice: files a person corrected, and images the AI already read (even if they still need a person), keep their rows. Only an image the AI could not read at all (wrong key, unreachable, unusable answer) is tried again.
- Token use per image is stored on the invoice (`extra.ai`) and in the `invoices_extracted` event, so the real cost can be checked.

**Manual tests (the expected values were read from the June images):**

| # | File | Expected |
|---|---|---|
| 7.1 | Run **Read invoices** again | 12 images processed; *pending* count 0 |
| 7.2 | `010626_DTDC_769.png` | ₹769.00 · 01/06/2026 · F33356894. **The image prints no vendor name**, so the row shows *Needs check* ("The image does not show a vendor name. Open the file and choose the vendor"); choose **DTDC** in the drawer and Save → *OK*, source *Manual* |
| 7.3 | `080626_DTDC_480.png` | DTDC · ₹480.00 · 08/06/2026 · V1005162495 (this one shows "DTDCShipAssure", so the vendor is read) |
| 7.4 | `DTDC_1124.png` / `DTDC_240.png` / `DTDC_510.png` / `DTDC_522.png` / `DTDC_623.png` | ₹1,124 10/06 · ₹240 12/06 · ₹510 12/06 · ₹522 16/06 · ₹623 11/06. `DTDC_510`, `DTDC_522` and `DTDC_623` read DTDC; `DTDC_1124` and `DTDC_240` print no vendor name: *Needs check*, choose **DTDC** by hand |
| 7.5 | `140626_Amazon_173.63.png` | Amazon · order 408-4442972-1434750 · WBL7-21429 · order date 14/06/2026 · ₹173.63 |
| 7.6 | `140626_Amazon_99.png` | Amazon · order 408-2168147-1083564 · IN-11218383 · **order 14/06, invoice 22/06/2026** · ₹99.00 |
| 7.7 | `CLOUD.png` / `Google_5000.png` | Google · ₹1,000.00 · 08/06/2026 / Google · ₹5,000.00 · 16/06/2026 |
| 7.8 | `080626_thinkrobotics_124.99.png` | order TR60380 · 08/06/2026 · ₹124.99. The page prints no shop name: *Needs check*, choose **thinkrobotics** by hand |
| 7.9 | Correct a wrong field (if any) in the drawer; for each *Needs check* image click **Open file**, choose the vendor, Save | Saved; source becomes *Manual*; status *OK*. After reading again, the Needs check chip holds only the Mailchimp receipt, and the AI is not called again for these images |
| 7.10 | Temporarily set a wrong `ANTHROPIC_API_KEY` and re-read one image | That image shows *Needs check* with an error message; the job does not crash |
| 7.11 | `docker compose run --rm tests pytest` | All pass (the live-AI tests are skipped) |
| 7.12 | Optional live check of the model itself: `docker compose run --rm -e RUN_LIVE_VISION=1 tests pytest tests/test_vision_live.py -s -v` (one paid call per image; add `-k DTDC_769` to try one image first) | The model's readings of the 12 images match 7.2–7.8, and the tokens used are printed |

---

## Slice 8: Amazon reconciliation CSV (no SQL)

**Goal:** the optional Amazon Business CSV is parsed and grouped into card charges.

**Build:**

- `engine/amazon_csv.py`:
  - Parse the 37-column CSV; `Payment Identifier` `="4002"` → `4002`.
  - Amounts to paise; dates `dd/mm/yyyy`.
  - Store rows in `recon_amazon_rows`.
  - Grouping: card-paid rows only (`Order payment method` ≠ `Gift Certificate/Card`), by `Payment Reference ID`, summing `Net total`.
- An **Amazon report** panel in the Invoices step lists the groups (payment date, card, reference, orders count, amount) and the gift-balance orders. `GET /api/cycles/{id}/amazon-report` feeds it.
- The report is read **when it is uploaded**: a CSV that isn't an Amazon Business report (missing columns, or a value that can't be read) is refused with the reason and nothing is stored. A new report replaces the old one together with its rows; the same file again is a duplicate.
- **Orders** counts distinct Order IDs in a group (a group has several rows per order). Rows with no payment method (not paid or not shipped, quantity 0, no reference) are in neither list; the panel says how many. Groups and gift orders are listed oldest payment first.

**Manual tests** (upload the September CSV into a **test** cycle):

| # | Steps | Expected |
|---|---|---|
| 8.1 | Upload the CSV as *Amazon report* → panel | **133** rows read (and "40 rows with no payment … are left out") |
| 8.2 | Card groups shown (Visa, 4002), oldest payment first | 09/09 ₹27,519.34 · 10/09 ₹1,920.00 · 11/09 ₹8,182.91 · 22/09 **₹717.00** · 22/09 **₹11,713.46** · 22/09 **₹12,713.14** · 23/09 ₹3,537.71 · 27/09 **₹4,542.46** · 29/09 ₹2,008.00 · 30/09 ₹0.00 (10 groups; the four in bold are the ones that matched exactly in the prototype) |
| 8.3 | Gift-balance list | 5 orders: ₹158 (09/09), ₹650 (17/09), ₹158 (22/09), ₹159 (23/09), ₹255 (30/09) |
| 8.4 | `pytest tests/test_amazon_csv.py` | All pass |
| 8.5 | Upload any other CSV (for example a bank export) as *Amazon report* | Refused with "This doesn't look like an Amazon Business reconciliation report. Missing columns: …"; nothing is stored |
| 8.6 | Upload the September CSV again, then a different valid report | The same file shows as a duplicate and the panel is unchanged; a different valid report replaces the old one and its groups |

---

## Slice 9: Matching engine (no SQL)

**Goal:** the June result is reproduced exactly. The rules are `project_context.md` §8, all of them.

**Build:**

- `engine/matcher.py`, rules 1–10 in order. **Reuse** `doc/reference/match.py` and extend it with rule 8 (near-miss) and CSV mode.
- `services/run_matching.py` deletes system matches (`created_by is null`), keeps manual ones, and writes statuses, notes and suggestions.
- `POST …/match` (**from Slice 10 it works in the background and returns 202**; before that it ran inside the request; **409 until the statement is confirmed**, like reading invoices) and `GET …/match-summary` (lines and signed amounts by status). The Invoices step's **Run matching** button calls it, shows "Matching finished: 65 matched, 5 to review" and opens Results, which for now shows the eight counts (the line-by-line screen is Slice 10).
- A run keeps what a person decided: links with `created_by` set stay, lines with `updated_by` set are left exactly as they are, and their invoices are not offered to other lines. Credit-note invoices never match a debit; invoices with no vendor never match automatically.
- **CSV mode** is used for an Amazon debit only when its date is inside the Amazon report's payment-date range, with **no invoice-only fallback** inside it.
- **pytest:** `test_matcher.py` loads the June fixtures and compares each line's **status and files** with `june_2026_expected_results.csv`. The June test sets the vendors of the four vendor-less images by hand and relies on Mailchimp's candidate amount. `test_matcher_rules.py` tests each rule on small cases; `test_matcher_september.py` is test 9.6.
- `backend/scripts/compare_expected.py <cycle id>` (read-only) compares a real cycle in the database with the expected CSV, line by line.

**Manual tests (June cycle):**

| # | Check | Expected |
|---|---|---|
| 9.0 | June cycle (statement confirmed, invoices read, the vendors of the 4 vendor-less images chosen in the drawer: `010626_DTDC_769`, `DTDC_1124`, `DTDC_240` → DTDC; `080626_thinkrobotics_124.99` → thinkrobotics) | Ready to match |
| 9.1 | Invoices step → **Run matching** | (Since Slice 10 the Results step opens first with a progress bar, and the toast appears when the run finishes.) Toast "Matching finished: 65 matched, 5 to review", and the Results step shows: Matched **65** · Review **5** · Missing invoice **20** · No invoice **6** · Reversed **8** · Credit – manual **4** · Payment **1** · Bank charge **18** (total 127), with the amounts of `project_context.md` §6 |
| 9.2 | 13/06 ASSPL **₹2,557.44** | Matched to **8** files: `130626_Amazon_187.16(2)`, `_198`, `_220`, `_238`, `_499`, `_928.27`, `_98.01`, `130626_amazon_189(1)` |
| 9.3 | 14/06 ASSPL ₹5,078.63 / ₹1,018.00 / ₹7,193.19 | {228, 4028(1), 649(2), 173.63.png} · {249, 309, 460} · {525(1), 585.19(3), 5984(2), 99.png} |
| 9.4 | 09/06 ₹6,624 · 11/06 ₹726 · 19/06 ₹2,205.20 · 24/06 ₹7,623.88 · 25/06 ₹702 | {585, 6039} · {157, 201, 368} · {151, 165, 309, 473(2), 473, 634.20} · {139, 1599, 301.90, 314, 5269.98} · {149, 199, 354} |
| 9.5 | IndiGo 03/06 ₹16,734 · 04/06 ₹17,261 · 07/06 ₹13,079 · 07/06 ₹15,846 | AT38326 + AY53125 · AY75969 + AJ54054 · AZ69244 + AG47449 · **Review** suggesting AU17753 + AZ48672 (₹735 more) |
| 9.6 | *CSV mode (pytest, no app upload):* `pytest tests/test_matcher.py -k september` loads `september_2026_statement_lines_TEST_ONLY.csv`, the September Amazon CSV and the September bulk invoice ZIP | Each Amazon debit finds its CSV group: ₹717.00, ₹11,713.46, ₹12,713.14 and ₹4,542.46. Because the bulk ZIP lacks some invoices, all four are **Missing invoice**, with the attached invoices and the missing order IDs listed: ₹717 → attached IN-468 (₹484), missing 404-2278140-2557951 · ₹11,713.46 → 4 invoices attached (₹3,861.46), missing 407-0648176-5773946, 407-1162474-9663537, 407-5543022-9991556, 407-8748703-0233950 · ₹12,713.14 → 7 invoices attached (₹10,612.02), missing 407-1432135-3264328, 407-6016348-1857969 · ₹4,542.46 → none attached, missing 407-1181179-3994762, 407-5639317-8731563. 23/09 ₹3,892.06 has no CSV group of that amount → **Missing invoice** |
| 9.7 | 18/06 MACFOS ₹611.00 | Matched to `190626_Macfos_715.pdf` |
| 9.8 | DTDC 07/06 ₹215 and 12/06 ₹770 | Matched to `DTDC_215.pdf` and `DTDC_770.pdf`; note says within ₹1 (paise rounding) |
| 9.9 | 21/06 FATHOM ₹3,544.37 ($36) · 21/05 FATHOM ₹3,635.09 | `Fathom $36.pdf` · Missing invoice (before the invoice set) |
| 9.10 | 17/06 VERCEL ₹1,972.89 · 21/06 VERCEL ₹1,969.11 | `Vercel_20USD.pdf` · Missing invoice |
| 9.11 | 06/06 SCRIPTIT ₹896.69 ×2 | First Matched `ScriptIt.pdf`; second **Review**, "possible duplicate charge" |
| 9.12 | 20/06 ASSPL ₹52,539 · 12/06 ASSPL ₹53,139 | Review suggesting `200626_Amazon_52390.pdf` (₹149 less) · Review "equals same-day Amazon credits ₹52,990 + ₹149" |
| 9.13 | 05/06 GENSPARK ₹1,733.27 | Review suggesting `Genspark_$17.49.pdf` |
| 9.14 | Reversals | 30/05 SWIGGY GINIE ₹2,008 pair · 13/06 ASSPL ₹400.82 + 17/06 CR · 20/06 CREATED ₹4,72,000 pair and ₹200 pair → all **Reversed** (8 lines) |
| 9.15 | 10/06 CLICK TO PAY ₹60,472 CR · 11/06 Late Payment Fee | Payment · Bank charge |
| 9.16 | Unused invoices tab | Includes all `280626_Amazon_*`, `290626_*`, `300626_*` (after the statement date), `240626_Amazon_175.pdf`, `040626_Sembly_USD29.pdf`, `created invc.pdf`, `CREATED-25947.pdf`, `Fathom Video$20.pdf`, `Anthropic.pdf`, `300626_Macfos_801.pdf` |
| 9.17 | Run matching twice | Identical results (deterministic) |
| 9.18 | `pytest tests/test_matcher.py` | Pass; all 127 lines agree with the expected CSV on status and files |
| 9.19 | `docker compose run --rm tests python scripts/compare_expected.py <cycle id>` (read-only, on the matched June cycle) | "All 127 lines agree with june_2026_expected_results.csv (status and files)." |
| 9.20 | Call `POST /api/cycles/<draft id>/match` on a cycle whose statement is not confirmed | **409** "Confirm the statement first"; nothing is written |
| 9.21 | `docker compose run --rm tests pytest tests/test_matcher_rules.py tests/test_api_matching.py` | Pass (every rule, the 409 gate, credit notes never matching, a person's links and edits surviving a re-run) |

> **Until Slice 10** there is no line-by-line screen. Tests 9.2 to 9.16 are checked with `compare_expected.py` (all 127 lines at once) and with these queries in the Supabase SQL editor (use the cycle id from the address bar):
>
> ```sql
> -- every line with its status and the files linked to it (suggestions included)
> select t.txn_date, t.ser_no, t.description,
>        (case when t.is_credit then -t.amount_paise else t.amount_paise end) / 100.0 as amount_inr,
>        t.status, coalesce(string_agg(f.original_name, ', ' order by f.original_name), '') as files, t.notes
> from recon_transactions t
> left join recon_matches m on m.transaction_id = t.id
> left join recon_invoices i on i.id = m.invoice_id
> left join recon_files f on f.id = i.file_id
> where t.cycle_id = '<id>'
> group by t.id order by t.txn_date, t.sort_order;
>
> -- 9.16: invoices no line used or was offered
> select f.original_name, i.vendor_key, i.invoice_date, i.total_minor / 100.0 as total
> from recon_invoices i join recon_files f on f.id = i.file_id
> where i.cycle_id = '<id>' and i.duplicate_of is null
>   and not exists (select 1 from recon_matches m where m.invoice_id = i.id)
> order by f.original_name;
> ```

> **Note:** when comparing file names with `june_2026_expected_results.csv`, treat byte-identical pairs as the same file: `140626_Amazon_525.pdf` = `140626_Amazon_525(1).pdf`, `DTDC_488.pdf` = `MH2727WI016880_GC001_10-Jun-2026.pdf`.

---

## Slice 10: Results and review (no SQL)

**Goal:** the user can resolve lines, and their decisions survive re-runs.

**Build:**

- **First, matching becomes a background job** (the Slice 9 timing record: a real run was estimated at about 18 s). `POST …/match` now returns **202** at once and works in the background, like reading invoices: progress is kept on the cycle row (`job_status`, `job_progress`, `job_message`; every message of this job starts with "Matching") and `GET …/match-summary` returns it as `job` (`running` / `done` / `failed`, a run that has not moved for 3 minutes shows as failed). It reads in parallel and writes in bulk (the new links, and all the lines in one call instead of 127), and a failure is recorded on the cycle and releases the lock. The Invoices step's **Run matching** starts it and opens Results, which shows the progress bar and then the toast "Matching finished: 65 matched, 5 to review".
- `GET …/transactions` with filters `status`, `vendor`, `card`, `q`; `POST /api/transactions/{id}/resolve` (`attach_invoice_ids`, `detach_invoice_ids`, `status`, `note`, and `preview: true` to see the line as it would be without saving); `GET …/unused-invoices` (`q`, `vendor`).
- Wire the Results screen (tiles, search, vendor and card filters, j/k/Enter), the row drawer (attached, suggested, find invoice, sum vs charge) and the **Invoices not used** tab. The attached sum, the difference and the foreign-currency comparison are worked out by the server (`engine/results.py`), never in the browser: the drawer asks for a preview after every staged change.
- Every action is written to `recon_events`: `suggestion_accepted`, `invoices_attached`, `invoices_detached`, `status_changed`, `note_saved` (and `matching_run` for each run).
- A person's change marks the line (`updated_by`), so a new run leaves it exactly as it is and does not offer its invoices to other lines. Rules for a change: a status can be set by hand only to Matched, Review, Missing invoice or No invoice; Matched needs at least one invoice attached; an invoice already used by another line, or reserved by another line's suggestion, cannot be attached; saving invoices whose sum differs from the charge needs a note written by a person; leaving Review drops the line's remaining suggestions (they stop reserving their invoices); a credit note cannot be attached to a charge (refused with a message; it can be attached to a credit line); an exported reconciliation is editable since Slice 11 (the first edit moves it back to matched; see Slice 11).
- The Results mock (`src/mock-screens/Results.tsx`, `MockStateBar.tsx`, `useMockJob.ts`, the mock lines and unused invoices) is deleted.

**Manual tests:**

| # | Steps | Expected |
|---|---|---|
| 10.0 | Invoices step → **Run matching** | The Results step opens at once with a progress bar and messages that start with "Matching" (for example "Matching 127 lines against 124 invoices…"), then the toast "Matching finished: 65 matched, 5 to review" and the tiles of 9.1. The page never freezes |
| 10.1 | Click the **Review** chip | 5 rows |
| 10.2 | Open 20/06 ₹52,539 → **Accept suggestion** | Status becomes Matched in the drawer; it shows sum ₹52,390 and difference **₹149.00** in amber; a note is required before saving a non-zero difference (Save without a note is refused; with a note it saves, the drawer closes and the row is Matched) |
| 10.3 | Open 19/06 MACFOS ₹715.01 (Missing) → **Mark No invoice** with note "asked vendor" | Status No invoice; note shown in the table |
| 10.4 | Find invoice: search unused by vendor *Amazon*, amount 175 (type `amazon 175`) | `240626_Amazon_175.pdf` appears; attach it to any test line; the running sum updates |
| 10.5 | **Re-run matching** | Lines changed in 10.2–10.4 keep the user's decision; other lines unchanged |
| 10.6 | Search box: type `52539` and then `Vistaprint` | Finds the line by amount, and the Vistaprint lines by description |
| 10.7 (moved to Slice 12, test 12.7) | Upload a new invoice file to the cycle, read invoices, re-run matching | The new invoice can match a Missing line; earlier manual decisions are kept |
| 10.8 | SQL: `select action, count(*) from recon_events where cycle_id='<id>' group by 1;` | Rows for each action done above (`suggestion_accepted`, `status_changed`, `note_saved`, `invoices_attached`, `matching_run`) |
| 10.9 | **Invoices not used** tab | The files of test 9.16, each with a reason; an invoice that a Review suggestion holds (`200626_Amazon_52390.pdf` before 10.2) is **not** listed; after 10.2 it is attached and still not listed; after detaching it from a line it is listed again |
| 10.10 | Open 21/06 FATHOM ₹3,544.37 | Attached `Fathom $36.pdf` ($36.00); the drawer says Matched with difference ₹0.00 (the USD invoice equals the line's $36.00) |
| 10.11 | `docker compose run --rm tests pytest tests/test_api_results.py tests/test_results_engine.py tests/test_api_matching.py` | Pass |
| 10.12 (moved to Slice 12, test 12.8) | SQL after a fresh run on a cycle with no hand edits: `select min(updated_at), max(updated_at) from recon_transactions where cycle_id='<id>';` | The span is about one second or less (all lines are written in one call; the Slice 9 estimate for 127 separate writes was about 15 s) |

---

## Slice 10b: Amazon follow-ups (no SQL)

**Goal:** the person can see exactly which Amazon invoices to fetch, an Amazon invoice never silently turns into a "missing order", the unused list says why an invoice was not used, and a file set aside by mistake can be brought back. (Approved by the planning chat after the Slice 11 approval; narrowed to the four items below.)

**Build:**

- **Amazon invoices to fetch.** `GET /api/cycles/{id}/amazon-to-fetch` and a tab **Amazon invoices to fetch** on the Results step (shown only when a report is uploaded): every order of the report's payment groups that pay a charge of this statement and has **no invoice** by Order ID, with Order ID, payment date, the order's amount in the report, and the charge (date, amount, description, SerNo), plus **Copy all IDs**, the total, and a line about the whole report (card-paid orders, with and without an invoice, partly invoiced, gift orders). The group of each charge is chosen by the matcher's own functions (`candidate_groups`, `pick_equal_group`, `pick_near_group`) walking the lines in the matcher's order, from what is saved, so the list always agrees with the "orders without an invoice" in the lines' notes. Needs matching to have run; lines a person changed, credits, reversals, fees and payments are not looked at. An order that has an invoice covering only **part** of it is counted but not listed. **No Excel change.**
- **Amazon invoice with no readable Order ID** is `needs_check` with the reason "Amazon order ID not found. Open the file and type it (like 407-1234567-1234567)" (or "…is not in the usual format…" for a misread one). One rule (`field_problems` in `engine/invoices/validate.py`) is used when an invoice is read (PDF text or AI) and when a person corrects one. The fetch list shows how many Amazon invoices are in this state, so an uploaded invoice is never silently taken for a missing order.
- **Reasons on the "Invoices not used" tab** (and so in the Excel's reason column): Amazon invoices dated after the last Amazon debit on the statement say "Dated after the last Amazon charge on this statement (dd/mm)"; with a report, an invoice found by Order ID says "Paid by gift balance", "Paid on another card" (a card that is not on the statement) or "Paid on dd/mm (after this statement)". The "same amount" reason now compares the **dollar** amount for USD invoices and says what happened to that charge: "A charge of $20.00 exists on 28/05/2026, 29 days from the invoice date (invoices are matched within 7 days)", "... is matched to another invoice", or "... but was not matched to this invoice".
- **Restore** a file set aside with "Not an invoice": `POST /api/files/{id}/restore` and a **Restore this file** button in the file's drawer. The file is an invoice file again (nothing is read yet); **Read invoices** reads it. Only a file a person set aside can be restored: a copy of the statement stays set aside. Written to `recon_events` (`invoice_restored`); on an exported reconciliation it is an edit.

**Not built (on the After-MVP list):** an order-by-order section in the review drawer; the Order IDs in the Amazon panel on the Invoices step; the invoice-only shortfall note ("the Amazon invoices that day add up to ₹X, ₹Y of this charge has no invoice"); listing partly invoiced orders.

**Manual tests:**

| # | Steps | Expected |
|---|---|---|
| 10b.1 | `docker compose run --rm tests pytest tests/test_amazon_fetch_engine.py tests/test_amazon_fetch_september.py tests/test_api_amazon_fetch.py tests/test_order_id_rule.py tests/test_restore.py tests/test_results_engine.py` | Pass. September: 60 card-paid orders, 36 with an invoice, 24 without, 2 partly invoiced, 5 gift orders with an invoice; the four typed charges list 9 orders |
| 10b.2 | `docker compose run --rm tests pytest tests/test_matcher.py` | Pass: all 127 June lines still agree with the expected CSV |
| 10b.3 | June, Results → **Invoices not used** | 22 rows. The 11 Amazon invoices dated 28/06 say "Dated after the last Amazon charge on this statement (27/06)"; `240626_Amazon_175.pdf` says "No charge of this amount found"; `Fathom Video$20.pdf` says "A charge of $20.00 exists on 28/05/2026, 29 days from the invoice date (invoices are matched within 7 days)"; the invoices dated 29/06 to 01/07 say "Dated after the statement date"; Sembly and Chempure say "No statement line for this vendor". There is no Amazon tab (June has no report) |
| 10b.4 | Invoices step → open `240626_Amazon_175.pdf`, clear **Order ID**, Save; then type `408-8436674-1697936` back and Save | After the first Save the row is **Needs check** and the drawer says "Amazon order ID not found. Open the file and type it (like 407-1234567-1234567)"; after the second it is OK again |
| 10b.5 | Invoices step → open `Anthropic.pdf` → **Not an invoice**; filter **Ignored**, open it → **Restore this file**; click **Read invoices** | The row shows Ignored, then "Not read yet" after Restore, then OK with its values again (your earlier corrections are kept). A copy of the statement in the Ignored list has no Restore button |
| 10b.6 | Export again | The "Invoices not used" sheet shows the same reasons as the tab; nothing else changed |
| 10b.7 | *The Amazon tab, in the app:* needs a statement whose Amazon charges match the report's payment groups. We have no such pair (June has no report; September has no statement PDF), so this is checked by pytest (10b.1) and, in the app, on the first real month with a report (Slice 12 acceptance if one exists) | The tab lists the orders without an invoice, with **Copy all IDs** |

---
## Slice 11: Excel export (no SQL)

**Goal:** the workbook is in the client's format, built from the current state.

**Build:**

- `engine/excel.py` following `project_context.md` §7 (pure; `openpyxl` is a new dependency). Money stays integer paise until it is written as a number (`Decimal`, never a float).
- `GET …/export.xlsx` (downloads the workbook for the current state, allowed any number of times, sets `exported`; 409 before matching) and `GET …/export-summary` (what the Export step shows: counts, the totals check, lines still needing review, last export and whether it was edited since).
- Export step screen with the totals check and the remaining-review warning. The file is named `CC Expense <Month YYYY>.xlsx` and the month sheet `<Month YYYY>`, both from the statement date.
- The **File Name** column lists every invoice linked to the line, suggestions included (a Review line shows the invoices it suggests), sorted by name, as in `june_2026_expected_results.csv`.
- **An exported reconciliation stays editable** (`flow.md` §2 and §8 stand; decided at the Slice 10 approval). The first edit after an export (a resolve, attach, detach, note, or a corrected invoice) moves the cycle back to `matched` and the screens show an "edited since export" note; downloading the Excel again sets `exported`. This replaces the refusals of an exported cycle added in Slices 6, 9 and 10.
- **Compare the exported "Invoices not used" sheet with `CC_Expense_June_2026.xlsx`** (a Review suggestion reserves its invoices) and report any difference.

**Manual tests:**

| # | Steps | Expected |
|---|---|---|
| 11.1 | Download Excel; open it in Excel or Google Sheets | 3 sheets: `Summary`, `June 2026`, `Invoices not used` |
| 11.2 | `June 2026` sheet | Headers exactly `Date, Transaction ID, Description, Amount, File Name, Status, Notes`; 127 rows; dates `d/m/yyyy`; amounts are numbers (`₹` format), credits negative |
| 11.3 | Row for SerNo 13598184078 | File Name lists the 8 Amazon files separated by `, ` |
| 11.4 | `Summary` check block | Debits **₹13,16,107.04** vs statement ₹13,16,107.04 → difference **₹0.00**; credits ₹5,91,066.42 → **₹0.00** |
| 11.5 | Change a status in the app, export again | The new file reflects the change; the Summary counts update (formulas) |
| 11.6 | Transaction ID column | Shows the full 11 digits, e.g. `13598184078` (not `1.36E+10`) |
| 11.7 | `Invoices not used` | Lists the unused invoices from test 9.16 with reasons (22 rows for June; a Review suggestion keeps its invoices out) |
| 11.8 | Export, then change one line in the app (for example set a Missing line to No invoice with a note) | A banner "Edited since the last export" shows on every step and on the Export step, the stepper stays reachable, and the cycle is no longer "Exported" on the home list |
| 11.9 | Download Excel again | The banner goes, the cycle is Exported again, and the new file shows the change |
| 11.10 | Export step on a matched cycle | Counters Matched / Review / Missing invoice / Other, debits and credits against the statement with the difference in green (₹0.00), the amber notice "N lines still need review. You can export anyway." and the three sheet names |
| 11.11 | `docker compose run --rm tests pytest tests/test_excel_engine.py tests/test_api_export.py tests/test_export_fixtures.py` | Pass (the third runs on the real June files) |
| 11.12 | `docker compose run --rm tests python scripts/compare_unused_sheet.py <cycle id> /app/tests/fixtures_private/CC_Expense_June_2026.xlsx` (read-only) | Lists the files only in the app and only in the reference workbook, each with a reason. Differences are reported to the user, not "fixed" (carry-forward from Slice 9) |

---

## Slice 12: Deploy and acceptance on a new month (SQL: migration 0004 only, run in the pre-work)

**Pre-work (done before "start Slice 12", at the Slice 11 approval):** `supabase/migrations/0004_recon_job_kind.sql` adds `recon_cycles.job_kind` and the API writes it with every job update (the "Matching" message prefix is no longer used); the dev packages (`pytest`, `httpx` as a listed dependency) are out of the runtime image (the `test` stage of `backend/Dockerfile` adds `.[dev]`; `httpx` stays because Supabase needs it). **Run 0004 before the new API is rebuilt or deployed.** The user sets every environment variable themself in Railway/Render and Vercel; no secret value is ever sent in chat.

**Goal:** the app is live and proven on a month it has never seen.

**Build:**

- **Backend on Railway** (chosen by the user): `backend/railway.toml` (Dockerfile build from the `backend` root directory, health check `/api/health`, one replica because the background jobs run in the API process). The Dockerfile's last stage is `runtime`, which is what Railway ships. The user sets the environment variables in Railway.
- **Frontend on Vercel**: `frontend/vercel.json` (Vite build, `dist`, a rewrite so a page reloaded on `/cycles/<id>/results` still opens, basic security headers). The user sets the `VITE_*` variables in Vercel; a production build without `VITE_API_BASE_URL` now says so instead of calling localhost.
- `CORS_ORIGINS` set to the Vercel URL (a trailing slash is ignored).
- Supabase Auth: the Vercel URL **added** to the redirect list (the Site URL is left alone: the project is shared).
- `doc/runbook.md`: how to deploy, add a user to `ALLOWED_EMAILS`, rotate keys, and what to do if a statement does not reconcile.
- Static checks in `tests/test_deploy_files.py`: `railway.toml` points at the Dockerfile and a real health route, the last stage is `runtime` without test packages, the container listens on `$PORT`, every setting the code reads is in `.env.example`, no secret value is in a deploy file.
- **The developer deploys nothing**: the accounts, the git push and every environment value are the user's.

**Manual tests:**

| # | Steps | Expected |
|---|---|---|
| 12.1 | Open `https://<api>/api/health`, then the Vercel URL and sign in | The API shows `{"status":"ok","version":"0.1.0"}`; sign-in works and the home list loads |
| 12.2 | Repeat 4.1–4.3, 5.2, 9.1 and 11.4 on production with the June files | Same numbers as locally |
| 12.3 | Browser dev tools → Network, and search the built JavaScript for `service_role`, `sk-ant` and `sb_secret` | No service-role key or Anthropic key appears anywhere in frontend requests or in the bundle |
| 12.4 | **Accuracy spot-check on June** (production): open 20 Matched lines picked at random, including at least 5 Amazon multi-invoice lines; open each attached invoice | The user confirms every one is correct. Record the result in `project_context.md` §11 |
| 12.5 | Time a full June run on production, from creating the cycle to downloading the Excel | Recorded; the target is under 30 minutes of the user's time, excluding collecting the invoices |
| 12.6 | `docker compose run --rm tests pytest` on the code that was deployed | All tests pass, including the September CSV-mode test 9.6 and `test_deploy_files.py` |
| 12.7 | *(moved from 10.7)* On a fresh June cycle remove **one non-image** invoice (a PDF) from the invoice files before uploading, read invoices and run matching, so its line becomes **Missing invoice**; resolve one other line by hand; then upload the removed invoice, read invoices and run matching again | The line that was Missing invoice becomes **Matched** to the uploaded invoice; the line resolved by hand keeps the user's decision |
| 12.8 | *(moved from 10.12)* Time matching on a fresh cycle with no hand edits: click Run matching and note how long until the toast; then `select min(updated_at), max(updated_at) from recon_transactions where cycle_id='<id>';` | Both numbers recorded in `project_context.md` §11; the write span is about one second or less (the Slice 9 estimate for 127 separate writes was about 15 s) |
| 12.9 | CORS: from PowerShell `curl.exe -i -H "Origin: https://evil.example" https://<api>/api/health`, then the same with `-H "Origin: https://<name>.vercel.app"` | The first answer has no `access-control-allow-origin` header; the second has it set to the Vercel origin |
| 12.10 | On the Vercel URL open a reconciliation's Results page and press F5; also open a made-up address such as `/nothing` | The Results page reloads (no 404 from Vercel); the made-up address shows the app's own "not found" page |
| 12.11 | Add a user as in `doc/runbook.md` section 4 (a test address), sign in with it, then remove it from `ALLOWED_EMAILS` | The test user signs in after being added and is refused ("Your account is not allowed to use this app") after being removed |

> **Known limit:** acceptance uses June (and September in tests), the same data the rules were built on. That proves the build is correct, but not how well the rules work on a month they have never seen. When the client's next statement arrives as a PDF, run it end to end and record the counts. That run is the first real accuracy measurement.

---

## After the MVP (not planned yet)

Possible next steps:

- Email ingestion of invoices.
- Saved vendor rules editable in the UI.
- A second bank format.
- Photo statements.
- Accounting-software export.
- Order-by-order section in the review drawer for an Amazon charge (a tick or a cross per order with its invoice file and amount: "N of M orders have an invoice · ₹X missing").
- The Order IDs of each payment group in the Amazon report panel on the Invoices step.
- Invoice-only shortfall note for an Amazon charge with partial invoices and no report ("the Amazon invoices that day add up to ₹X; ₹Y of this charge has no invoice"). Without the report the app cannot name the missing orders.
- Listing partly invoiced Amazon orders (an invoice that covers only part of an order) in the "to fetch" list and naming them in the line's note.- Dismiss a Review suggestion without choosing another status (today leaving Review drops its suggestions, and there is no "dismiss" action).
- Amazon Business API, if Amazon opens it for India.
- Remove a single uploaded file (today the whole reconciliation can be deleted; in Slice 6, "Not an invoice" covers wrong uploads).
