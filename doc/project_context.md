# Project Context: Credit-Card Expense Reconciliation

Read this file first, before every coding session. It records what has been **verified** on real data. If anything here conflicts with an older document (the Technical Design .docx, v0.1–v0.4), this file wins.

---

## 1. What we are building (one paragraph)

A web app for the client's accounts team. Once a month they upload three things:

1. The bank's credit-card statement (ICICI PDF).
2. All the invoices for that month (PDFs and images, usually as a ZIP).
3. Optionally, Amazon Business's reconciliation report (CSV).

The app then:

- reads every statement line;
- reads every invoice;
- matches each card charge to the invoice(s) behind it, including Amazon charges that cover many invoices;
- flags anything uncertain for a person to review;
- exports the Excel file the client already uses, with the invoice file name filled in against each line.

## 2. The problem it solves

Today, staff work through the month by hand:

- They type the statement from banking-app photos into Excel.
- They download invoices from each vendor.
- They work out which invoice belongs to which charge.

Amazon is the hard part. One card charge can cover up to 10 separate invoices (June: one ₹2,557.44 charge = 8 invoices), and nothing on the statement says which ones.

## 3. Scope

**In scope (MVP):**

- **Upload:**
  - ICICI statement PDF.
  - Invoice files (PDF, PNG, JPG, or ZIPs of these).
  - Optional Amazon Business reconciliation CSV.
- **Statement:**
  - Parse the statement automatically.
  - Check that the parsed lines reproduce the statement's own summary totals.
  - A person confirms the statement before matching starts.
- **Invoices:**
  - Extract invoice data: PDF text directly, images via a vision model.
  - A person can correct any extracted value.
- **Matching:**
  - Rule-based matching (section 8).
  - Reversals detected automatically.
  - Bank charges classified automatically.
- **Review screen:** attach or detach invoices, mark "no invoice", add notes.
- **Excel export** in the client's format (section 7).
- **Login** for the client's team (no public sign-up).

**Out of scope:** keep these out; do not build them unless the plan is updated.

- Fetching invoices from Amazon or any vendor website. There is no Amazon API for India, and scraping is ruled out (section 9).
- Refund, credit-note and cancellation handling. Credits are only listed. The one exception is automatic reversal pairing (section 8, rule 3).
- Email ingestion, accounting-software export, GST/ITC reports, multi-company or multi-tenant use.
- Statements from other banks. ICICI only; other parsers can be added later.
- Reading the statement from photos. This is optional, only if the bank PDF is ever unavailable.

## 4. People and confirmed decisions

| Decision | Status |
|---|---|
| Purchases are made on an **Amazon Business** account | Confirmed by team owner |
| AI reading of **invoice images** is approved | Confirmed by team owner |
| Refunds and cancellations stay **manual** | Confirmed by team owner |
| The bank can supply the statement as **PDF**, so PDF is the primary input | Confirmed by team owner |
| Banking app and statement show the **same INR amount** for foreign charges | Confirmed by team owner |
| Statement arrives **monthly**; the date can change (user said 29th; June statement is dated 28 Jun) | Confirmed. The app reads the period from the PDF, so no fixed date is assumed |
| Tech stack: Python/FastAPI, React, Supabase | From the technical design; treat as approved unless told otherwise |

## 5. Facts about the input data (verified on June 2026 files)

### 5.1 Statement: ICICI Bank credit-card PDF

| Item | June 2026 value |
|---|---|
| Statement date | 28 Jun 2026 |
| Statement period | "Statement period : May 21, 2026 to June 28, 2026" (printed on page 1) |
| Pages | 12. Transactions are on the first pages; the rest is bank boilerplate with **example tables containing amounts** (must be ignored) |
| Text layer | Yes. `pdftotext -layout` works; no OCR needed |
| Lines | **127** (card 4002: 121 lines, card 2492: 6 lines) |
| Summary | Previous balance ₹10,49,491.99 · Purchases/Charges **₹13,16,107.04** · Cash advances ₹0.00 · Payments/Credits **₹5,91,066.42** · Total due ₹17,74,532.61 |

**Line format:**

```
Date  SerNo  TransactionDetails  RewardPoints  [Intl.amount]  Amount(₹)  [CR]
```

Example lines:

```
21/05/2026  13463193979  SUPABASE SINGAPORE SG*  167  86.12 USD  8,695.94
12/06/2026  13592897886  ASSPL Bangalore IN      -1059           52,990.00 CR
```

**Parsing gotchas that are proven, not theoretical:**

1. **Page-1 sidebar text sits on the same line** as some transactions, e.g. `"Get 2.5% cashback and   27/05/2026 13488732741 OPENAI ..."`. Find the `date + serial` pattern anywhere in the line, not only at the start. Missing this drops lines: the first parser lost 2 lines (₹1,811.07).
2. **Descriptions wrap** onto the next line (`OPENAI *CHATGPT SUBSCR OPENAI.COM` / `US`).
3. **The currency code can wrap** onto the next line (`86.12` / `USD`).
4. **Card sections**: a line like `4035XXXXXXXX4002` precedes that card's transactions. Record the last 4 digits per line.
5. **Credits** end with ` CR` and have negative reward points.
6. **Serial numbers are unique.** Use them as the transaction key.
7. **Validation rule:** the sum of debits must equal Purchases/Charges **+ Cash Advances** (both printed on page 1), and the sum of credits must equal Payments/Credits, both **to the paisa**. If either fails, the statement is not accepted. (June: Cash Advances ₹0.00, so the rule reads as before.)
8. The statement says: *"Mark-up fee and corresponding GST levied is included in the transaction amount displayed."* So the INR amount of a foreign line already includes the bank fee.
9. Separate fee lines exist: `DCC Fee`, `SGST-CI@9%`, `CGST-CI@9%`, `Late Payment Fee`, `Interest Charges`.

### 5.2 Statement descriptor → vendor (seen in June)

| Descriptor contains | Vendor | Notes |
|---|---|---|
| `ASSPL`, `AMAZONIN` | Amazon | Many invoices per charge |
| `MACFOS LIMITED` | Robu (Macfos) | |
| `WWW DTDC IN` | DTDC | |
| `INDIGO AIRLINE` | IndiGo | 2 invoices per charge (one per sector), same PNR |
| `MAKEMYTRIP` | MakeMyTrip | Booking confirmation ("Paid INR 94,146") |
| `TRIPIFY` | Tripify | |
| `VISTAPRINT` | Vistaprint | |
| `FATHOM`, `VERCEL`, `SUPABASE`, `ZAPIER`, `RAILWAY`, `ANTHROPIC`, `CALENDLY`, `Phantombuster`, `SCRIPTIT`, `GENSPARK` | SaaS | Invoices in USD; match on the USD amount |
| `GOOGLE CLOUD`, `GOOGLE CLOUDS` | Google | Payment receipts (images) |
| `Mailchimp`, `PERISKOPE`, `WIX`, `MICROSOFT`, `OPENAI`, `WWW AIRTEL` | Other online | INR on statement |
| `AQTRONICS`, `SHOTT AMUSEMENT`, `ATLANTIS ROBOTICS`, `RoboCraze` | Other | `ATLANTIS ROBOTICS` = thinkrobotics order page |
| `CREATED ANDHERI WEST` | Client's own entity | June: charged and reversed same day |
| `SWIGGY`, restaurants | Food | Usually no invoice |

This table is seed data for the `recon_vendor_aliases` table and must be editable in the app later.

**Vendor detection on invoices uses the invoice's text only, never its file name.** Some vendors issue invoices under a different legal name, so each vendor also has an invoice-text pattern. Checked on all 113 June invoice PDFs: text-only detection gives the same vendor as the prototype for every file.

| Vendor | Invoice text contains |
|---|---|
| Amazon | `Amazon Seller Services`, `ASSPL-Amazon`, `Amazon Wholesale`, `amazon.in` |
| Robu (Macfos) | `MACFOS` |
| DTDC | `DTDC` |
| IndiGo | `InterGlobe Aviation` |
| Vistaprint | `Cimpress` |
| MakeMyTrip | `MakeMyTrip` (hotel booking, e.g. Lemon Tree) |
| Tripify | `Tripify` |
| Shott | `Shott Amusement` (the files are named `CREATED-*.pdf`) |
| Periskope | `Hashlabs Holdings` (no mention of Periskope in the invoice text) |
| Chempure | `Chempure` |
| SaaS (Fathom, Vercel, Supabase, Zapier, Railway, Anthropic, Genspark, ScriptIt, Sembly) | their own names |
| Mailchimp | `Mailchimp` / `Intuit` |
| Airtel | `Airtel` |
| AqTronics | `AqTronics` |

A copy of the statement uploaded among invoices is recognised by `CREDIT CARD STATEMENT`.

### 5.3 Invoices (June ZIP: 126 files)

- **Types:** 114 PDFs (all with a text layer) and 12 PNG images (7 DTDC booking screenshots, 2 Amazon invoices, 2 Google receipts, 1 thinkrobotics order page).
- **Amazon tax invoices** (62 PDFs → 63 invoices; 65 including the two images):
  - Fields are `Order Number`, `Order Date`, `Invoice Number`, `Invoice Date`, and the last `TOTAL:` row (the invoice total).
  - **One PDF can contain several invoices.** Split on pages containing `Order Number`.
  - Several invoices can share one order (different sellers).
  - **Order date can differ from invoice date** (e.g. ordered 14.06, invoiced 22.06). Matching uses the **order date**.
- **Robu/Macfos:**
  - Use the invoice's own `Total ₹ X` line, not the line items.
  - The invoice date is printed on the line below the "Invoice Date:" label.
- **DTDC:**
  - PDF invoices can carry paise (₹215.01 for a ₹215 charge).
  - Screenshots show "Booking Date" and "Amount".
- **IndiGo:** `Grand Total` row, `Date : 04-Jun-2026`, `PNR : YGDDKH`.
- **USD receipts** (Stripe-style): "Date of issue June 20, 2026", amounts in `$`.
- **File names are written by staff and are unreliable.** Never derive amounts or dates from file names.
  - `190626_Macfos_715.pdf` is really a **₹611** invoice.
  - `280226_Amazon_489.pdf` is dated 28 Jun.
  - One file in the ZIP (`ACFrOg…pdf`) is a copy of the statement, not an invoice.
- **Duplicates happen:**
  - The same Amazon invoice was uploaded twice under two names.
  - The same DTDC invoice was uploaded twice.
  - De-duplicate by file hash and by (vendor, invoice number, total).
- **Some invoices belong to the next statement** (dated after the statement date) or to charges on another card. List them as unused; never force them onto a line.

### 5.4 Amazon Business reconciliation CSV (September sample; optional input)

- **37 columns.** Key columns:
  - `Order ID`
  - `Order Date`
  - `Order payment method` (`Visa` or `Gift Certificate/Card`)
  - `Payment Reference ID`
  - `Payment Date`
  - `Payment Identifier` (last 4 digits, written as `="4002"`)
  - `Shipment Quantity`
  - `Net total`
- **Grouping by `Payment Reference ID`** and summing `Net total` reproduces each Amazon card charge exactly. September: ₹717.00, ₹11,713.46, ₹12,713.14 and ₹4,542.46 all matched to the paisa.
- **Exclude gift-balance rows.** Rows with payment method `Gift Certificate/Card` are not card charges.
- `Charge Identifier` is empty for India. Do not rely on it.
- **No refund rows.**
- **How many invoices the bulk ZIP leaves out (measured on the September files):** the report has **60 card-paid orders** (10 payment groups); **36** have an invoice file by Order ID and **24 do not (40%, ₹38,572.91 of ₹72,854.02)**; of the 36, 2 are only **partly invoiced** (the invoice covers less than the order). The 43 PDFs in the ZIP give 43 invoices for 41 orders: the 36 card orders and all **5 gift-balance orders**, which were never on the card.
- Rows with `Shipment Quantity` 0 have no Net total (not shipped).
- **Test data:** September has no statement PDF (only a screenshot). Its 25 visible lines are typed into `doc/reference/september_2026_statement_lines_TEST_ONLY.csv`, which is used only in automated tests. **Never create a PDF that imitates a bank statement.** Use real bank PDFs only.
- **June: the CSV was not supplied.** Amazon matching worked from invoices alone (section 8). The CSV removes ambiguity when amounts collide, so the app supports both modes.

### 5.5 Client output format

The client's Excel (`CC Expense September 2026.xlsx`) has one sheet with columns:

**`Date | Transaction ID | Description | Amount | File Name`**

- `File Name` holds invoice file names, comma-separated when there are several.
- The client's own file stores amounts as text with inconsistent signs. **We output numbers**, with credits negative.

## 6. Reference results (prototype run on June 2026)

A prototype (scripts in `doc/reference/`) produced the result in `doc/reference/june_2026_expected_results.csv`. The finished app must reproduce it (see the implementation plan for exact test cases).

| Status | Lines |
|---|---|
| Matched | 65 |
| Review | 5 |
| Missing invoice | 20 |
| No invoice | 6 |
| Reversed | 8 |
| Credit – manual | 4 |
| Payment | 1 |
| Bank charge | 18 |
| **Total** | **127** |

The prototype was not one clean pipeline. Know these gaps when rebuilding:

- `extract_inv.py` guessed vendors from file names first. The app must use invoice text (see §5.2). This was verified to give the same June result.
- `invoices_all.json`, which `match.py` reads, was assembled in extra steps not saved as scripts:
  - the 12 image invoices were read by hand and added (their values are in `implementation_plan.md` tests 7.2–7.8);
  - Amazon **order dates** were added (only 3 June invoices have an order date different from the invoice date: `200626_Amazon_999.pdf` 20.06 vs 21.06, `280626_Amazon_123(1).pdf` 28.06 vs 30.06, `140626_Amazon_99.png` 14.06 vs 22.06; the last one must match the 14/06 ₹7,193.19 charge, which only works on order date);
  - `CREATED-*.pdf` were set to Shott and `created invc.pdf` to Chempure.
- Five `Review` notes in the expected CSV came from the near-miss rules being applied by hand. Rule 8 now specifies them.

The prototype scripts are **evidence of what works**, not production code. Rebuild them cleanly inside `backend/app/engine/` and keep the behaviour.

## 7. Output Excel (export)

**Sheet order:**

1. `Summary`
2. `<Month YYYY>` (e.g. `June 2026`)
3. `Invoices not used`

**Main sheet columns:**

| Col | Header | Content |
|---|---|---|
| A | Date | Transaction date, real date, format `d/m/yyyy` |
| B | Transaction ID | Statement serial number, number format `0` |
| C | Description | Statement description; foreign lines append `  [86.12 USD]` (round amounts are written short, as in the expected results: `[36 USD]`, `[133.5 USD]`) |
| D | Amount | INR as charged, number format `₹#,##0.00;-₹#,##0.00` (written with the symbol quoted, `"₹"#,##0.00;-"₹"#,##0.00`, which shows the same), credits negative |
| E | File Name | Linked invoice file names (attached and, for a Review line, suggested), sorted by name, `, `-separated |
| F | Status | One of the 8 statuses |
| G | Notes | Reason or explanation |

Columns A–E must stay exactly as the client's format.

**`Summary` sheet:**

- Count and amount per status, using `COUNTIF`/`SUMIF` formulas.
- A check block: sheet debits vs statement Purchases/Charges, and sheet credits vs Payments/Credits, with the difference (must be 0).

**`Invoices not used` sheet:** file, vendor, date, amount, reason.

**Font:** Arial 10.

## 8. Matching rules (the contract)

All money is compared in **integer paise** (INR) or **cents** (USD). Rules run in this order; a line takes the first rule that applies.

1. **Bank charge:**
   - Applies when the description starts with `DCC Fee`, `SGST-CI`, `CGST-CI`, `Late Payment Fee` or `Interest Charges`.
   - Status: `Bank charge`.
2. **Payment:**
   - Applies when the description contains `PAYMENT RECEIVED`.
   - Status: `Payment`.
3. **Reversal:**
   - Applies to a credit and a debit with the same merchant key (first 18 characters of the upper-cased, space-normalised description), the same amount, and dates within 7 days.
   - Status: `Reversed` on both lines; the notes cross-reference the serial numbers.
4. **Other credits:**
   - Status: `Credit – manual`.
5. **Amazon** (descriptor `ASSPL` or `AMAZONIN`):
   - **CSV mode** (CSV uploaded):
     - Use only card-paid rows whose last 4 digits match the line's card.
     - Group the rows by `Payment Reference ID`.
     - A group matches a debit when its amount is equal and `Payment Date` is within 3 days of the transaction date.
     - Attach every invoice whose `Order ID` is in that group.
     - If the attached invoice totals do not add up to the charge: status `Missing invoice`, listing the order IDs without an invoice.
   - **Invoice-only mode** (no CSV):
     - Candidate invoices are unused Amazon invoices (not credit notes, not duplicates) whose **order date** is between transaction date −3 days and the transaction date.
     - Process debits in date order. Pass 1 tries a single invoice of the exact amount; pass 2 tries subsets (up to 12 invoices) summing exactly.
     - If several subsets fit, prefer one that keeps all invoices of an order together, then the smallest total date distance.
     - If a tie remains: status `Review`, suggesting the first option.
   - **Mode choice:** a debit uses CSV mode when a CSV was uploaded **and** the debit's date falls within the CSV's payment-date range. Otherwise it uses invoice-only mode.
   - **No fallback inside CSV mode.** If no CSV group equals the charge, try the near-miss rules against the CSV groups (rule 8c: a group within 5% → `Review` with that group's invoices suggested); otherwise `Missing invoice`. September: ₹3,892.06 vs the nearest group ₹3,537.71 (9% apart) → `Missing invoice`.
6. **IndiGo:**
   - Same subset method as Amazon invoice-only mode.
   - Use the invoice date between transaction date −3 and +1 days.
   - Prefer combinations from a single PNR.
7. **All other vendors:**
   - Find the vendor from the alias table.
   - Build candidate pairs (line, unused invoice of that vendor) where:
     - (a) the INR amount is exact, or
     - (b) the line has a foreign amount equal to the invoice's USD amount, or
     - (c) the INR amount is within ₹1 (rank lower: paise rounding).
   - An invoice matches when its **invoice date or its order date** (including a date printed as "Booking Date") is within 7 days of the charge, if the invoice has any date. The date gap used for ranking is the smaller of the two. *(Clarified 2026-10-15 at the Slice 9 approval: the prototype used every date in the document; the June Tripify air invoice, dated 30 Jun for a 07 Jun booking, needs this.)*
   - Assign pairs globally, sorted by (rank, date gap), each invoice at most once.
8. **Near-miss → Review** (with suggestion and a note):
   - (a) The only unused invoice of that vendor within 7 days is in USD, and the line shows INR only. June: Genspark ₹1,733.27 vs $17.49.
   - (b) An Amazon debit equals the sum of Amazon credits on the same day. June: ₹53,139 = ₹52,990 + ₹149.
   - (c) An unused invoice, or subset of invoices, of the same vendor within the date window differs from the charge by ≤ 5%. June: Amazon ₹52,539 vs invoice ₹52,390; IndiGo ₹15,846 vs PNR EBU8WT invoices ₹16,581.
   - (d) Two identical debits (same description, amount and date) but only one matching invoice. The second gets "possible duplicate charge". June: ScriptIt ₹896.69 ×2.
   - **A Review suggestion reserves its invoices:** they are not offered to any other line, and they do not appear under "Invoices not used". *(Added 2026-10-15 at the Slice 9 approval; the prototype did not reserve them.)*
9. **No vendor recognised:**
   - Status: `No invoice` (food, restaurants, unknown merchants).
10. **Otherwise:**
    - Status: `Missing invoice`.
    - If the line is dated before the earliest invoice date in the upload, the note says the charge predates the invoice set.

**The AI model only extracts invoice fields. It never decides a match.**

## 9. Hard constraints

- **Amazon:**
  - No official Amazon API for invoices or reconciliation is available for India: the Reconciliation and Document APIs are documented for US/EU/JP only.
  - Do not build any login automation or scraping of Amazon or vendor sites. It would breach Amazon's Conditions of Use and risk the client's account.
- **Database:**
  - It is a shared Supabase project. The existing tables (`payment_requests` and `payment_webhook_events`, exact names confirmed by the user on 2026-10-13) **must not be touched**.
  - All our tables use the prefix **`recon_`**.
  - The storage bucket is **`recon-files`**.
- **SQL is never executed by the dev chat.**
  - Write migration files in `supabase/migrations/`, numbered `NNNN_description.sql`, idempotent where possible.
  - Hand the SQL to the user, who runs it in the Supabase SQL editor.
  - Each migration ships with a verification query and a rollback snippet.
- **Secrets:**
  - The service-role key and Anthropic key stay in backend environment variables only.
  - The frontend gets only the Supabase URL and anon key (for login).
- **Real client files** (statements, invoices) are never committed. Test fixtures live in a git-ignored folder (`backend/tests/fixtures_private/`).
- **Money is stored as integer paise.** Never use floats in the database.

## 10. Working agreement for the dev chat

- Build **one slice at a time**, following `implementation_plan.md`.
- After each slice:
  - list what changed;
  - give any SQL to run;
  - repeat the slice's manual test cases.
- Then **stop and wait** until the user confirms the tests pass. Do not start the next slice early.
- Do not invent:
  - vendor formats, columns or rules not in this folder;
  - test results.

  If something is unknown, say so and ask.
- If a test fails, fix it within the same slice.
- Keep `doc/` up to date when a decision changes, and add a dated line to section 11.

## 11. Decision log

| Date | Decision |
|---|---|
| 2026-10-07 | Amazon matching uses the Business Analytics export, not an API (no India API). |
| 2026-10-07 | Stack: FastAPI + React + Supabase; deploy API on Railway/Render, frontend on Vercel. |
| 2026-10-07 | Refunds and cancellations stay manual; credits are listed only. |
| 2026-10-07 | Amazon Business account confirmed; AI reading of invoice images approved. |
| 2026-10-13 | Statement input is the ICICI PDF (text layer); photo statements are optional. The statement period is read from the PDF, not entered manually. |
| 2026-10-13 | June prototype matched 65 of 127 lines. Amazon worked without the CSV (unique subsets for every matched charge). The CSV stays optional but recommended. |
| 2026-10-13 | Reversal pairs (charge plus same-amount credit within 7 days) are detected automatically. |
| 2026-10-13 | Tables prefixed `recon_` to avoid clashing with existing tables in the shared Supabase project. |
| 2026-10-13 | UI designed in v0. The export is kept in `doc/design_reference/`; `design.md` is rewritten around it. Missing screens are specified in `design.md` §5. Frontend uses React 19, Tailwind v4 and shadcn `base-nova`, light theme only. |
| 2026-10-13 | Answers to the dev chat's first-read questions: build in the repo root `expenses_reconciliation`; Python ≥3.11 locally (3.12 in Docker); PDF tests run in Docker unless poppler is installed locally; vendor detection from invoice text only, with per-vendor invoice patterns; Amazon order date with invoice-date fallback; partial unique index for duplicate files; `pending` extraction status and `recon_files.note`; a statement mismatch keeps the cycle at `statement_parsed`; CSV mode has no invoice-only fallback; September test lines are card 4002; foreign amounts may contain commas; JWT verification supports JWKS and legacy secret. |
| 2026-10-13 | No July data and no September PDF. Acceptance runs on June (end to end) and on September (CSV mode, as an automated test from typed-in lines). The first real unseen-month test happens when the next statement PDF arrives. |
| 2026-10-13 | Toolchain: the backend declares `requires-python >=3.11` (local dev on 3.11 is fine); the Docker image uses 3.12. poppler is not installed locally: everything that needs it (PDF tests, pytest suites from Slice 5) runs in Docker via `docker compose run --rm tests`. |
| 2026-10-13 | Existing tables in the shared Supabase project are named `payment_requests` and `payment_webhook_events` (earlier docs said `payments_requests`). Still never touched; `recon_` prefix unchanged. |
| 2026-10-14 | Uploads (Slice 4): files with identical content (SHA-256) in a cycle are recorded as `duplicate` and stored once, including ZIP members. A statement copy among the invoices is `ignored` with the note "copy of the statement", found by its text or by matching the statement's hash. **Found on the real June ZIP:** two pairs of byte-identical files (`140626_Amazon_525(1).pdf` / `…525.pdf`, `DTDC_488.pdf` / `MH2727WI016880_GC001_10-Jun-2026.pdf`) and a statement copy byte-identical to the statement PDF. So after upload June has 123 uploaded + 2 duplicate + 1 ignored invoice files (not 125 + 1). **Slice 6 expectations that assume 113 PDF files / 2 invoice-level duplicates (6.2, 6.3, 6.10) must be revisited by the planning chat.** |
| 2026-10-14 | Duplicates in the June ZIP are **file-level (byte-identical, same SHA-256)**, found at upload and recorded as `duplicate`; they are not read again. Verified by the planning chat: `140626_Amazon_525.pdf` ≡ `140626_Amazon_525(1).pdf`, `MH2727WI016880_GC001_10-Jun-2026.pdf` ≡ `DTDC_488.pdf`, and the `ACFrOg…` file ≡ the statement PDF. Updated Slice 6 counts: read 123 files (111 PDFs + 12 images); 112 PDF invoices from 111 PDF files; 62 Amazon PDF invoices from 61 files; file-level duplicates 2; ignored 1; invoice-level duplicates 0 (the invoice-level rule stays for re-downloaded copies with different bytes). Slice 9 compares byte-identical pairs as the same file. |
| 2026-10-14 | Auth: tokens are verified against the Supabase JWKS endpoint (signing keys), not a shared secret. Public sign-ups cannot be disabled (shared Supabase project), so `ALLOWED_EMAILS` in the backend is the only gate and an empty list allows nobody. Initial allow-list: `harsh@create-ed.in`. Sign-out is local-scope only so the user's sessions in other apps on the same project are not revoked. |
| 2026-10-14 | Statement step (Slice 5): the statement can be replaced until it is **confirmed** (not only while the cycle is a draft), because a mismatch screen offers "Replace statement" (design.md §5.2, flow.md). Replacing a statement that was already read deletes the lines read from the old one and returns the cycle to `draft`. Lines are saved only when every `date + serial` line could be read and serials are unique; a totals mismatch is saved (so it can be shown) but cannot be confirmed. The Invoices step opens only after the statement is confirmed. |
| 2026-10-15 | Slice 6 (planning-chat carry-forwards, now built): invoice reading and matching are refused with **409 until the statement is confirmed** (server-side, one shared check); the statement totals check is debits = Purchases/Charges **+ Cash Advances** (the sum is stored in `summary_purchases_paise`, no new column); an empty cycle label is set from the statement date ("June 2026"), and a label made that way is cleared when the statement is replaced. |
| 2026-10-15 | Slice 6 invoice reading: vendor comes from the invoice text; the vendor whose invoice pattern appears **first** in the text wins, except Amazon, which is recognised by its footer (`ASSPL-Amazon` / `Amazon Seller Services` with `Order Number`). Images and PDFs without a text layer get one `pending` row each until Slice 7. An invoice is `needs_check` when the vendor, the total or any date is missing (the reasons are kept). Re-reading replaces every row except those a person corrected (`source = manual`). Invoice-level duplicates = same vendor + number + total + currency as an earlier invoice. "Not an invoice" sets the file aside as `ignored`. Invoice amounts are kept in the invoice's own currency (paise or cents); `amounts_minor` lists every amount shown, for vendors matched on "an amount equals the charge". June result: 112 invoices from 111 PDF files, 1 needs a check (the Mailchimp receipt has no total line). |
| 2026-10-15 | Slice 7 (AI vision): images and PDFs without a text layer are read by Claude through the official Anthropic SDK; the key and the exact model ID come from `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` and nothing is hard-coded. The model only extracts seven fields (vendor, invoice no., order id, invoice date, order date, currency, total) in a strict JSON format; the engine re-checks them, resolves the vendor name with the invoice patterns, retries once on an unusable answer, and otherwise marks `needs_check` with the reason. With no key or model set, images stay `pending`. A re-read does not repeat AI calls for images already read fine or corrected by a person. Tests never call the real model (the test environment strips the key); a separate opt-in live test checks it on the 12 June images. |
| 2026-10-15 | Slice 7 decision (user): an image that prints **no vendor name** is **not** given a vendor from its file name or by the AI's guess. It stays `needs_check` ("The image does not show a vendor name. Open the file and choose the vendor") and a person chooses the vendor in the drawer. Found on June: 4 of the 12 images (`010626_DTDC_769`, `DTDC_1124`, `DTDC_240`, `080626_thinkrobotics_124.99`) print no vendor, so they need that one click before Slice 9 can match them (the other 8 name their vendor). The plan's expected vendor for these four came from the file names, which §5.2 does not allow. A re-read does not send an image to the AI again once the AI has answered (only failures are retried). Real cost of the 12 June images on `claude-sonnet-5-5`: 20,002 input and 915 output tokens, about $0.05. |
| 2026-10-15 | Known limit (Slice 7): a scanned PDF (no text layer) is read from **page 1 only**: that page is rendered to a PNG and sent to the model. A multi-page scan therefore gives at most one invoice (the first page), and later pages are not read; the person sees the one row and can add what is missing by hand. June has no scanned PDFs (all 111 PDFs have a text layer), so nothing is lost there. Revisit if a scanned multi-page invoice appears. |
| 2026-10-15 | Secrets in logs (Slice 7, checked): the Anthropic key is never logged. The AI client logs only the kind of failure and its HTTP status (for example `AuthenticationError (status 401)`), never the SDK's error text; people see a fixed friendly message instead. `backend/.env` is git-ignored, absent from the Docker image (`.dockerignore`), and its key value appears in no file git would add. |
| 2026-10-15 | Slice 8 (Amazon Business CSV): the report is read **at upload** and its rows are saved with the file in `recon_amazon_rows`; a CSV that is not an Amazon Business report, or has a value that can't be read, is refused with the reason (nothing stored). Verified on the September sample: 133 rows, 10 card groups (Visa 4002) whose amounts match §5.4 to the paisa, 5 gift-balance orders (₹158, ₹650, ₹158, ₹159, ₹255), and 40 rows with no payment method (quantity 0, no reference) that belong to neither list. A group's **orders** are its distinct Order IDs (a group has several rows per order). An unshipped row (empty Net total) counts as ₹0.00, which is why one September group is ₹0.00. Negative Net totals (refunds) would be kept and reduce their group. Matching with these groups is Slice 9. |
| 2026-10-15 | Slice 9 (matching built; **§8 was not changed**). The June cycle reproduces `june_2026_expected_results.csv` on all 127 lines (status and files) and the §6 counts and amounts. Decisions taken while building, for the planning chat to confirm: (1) Rule 7's date test accepts an invoice when its invoice date **or its order date** is inside the vendor's window (the prototype accepted any date in the document); the generic reader now also reads a `Booking Date` label as the order date, which is what lets the Tripify air invoice (dated 30 Jun) match its 07 Jun charge, the one line that differed on the first run. (2) A suggestion (Review) **reserves** its invoices so no other line is offered them; the prototype did not. (3) The CSV payment-date range is the first and last Payment Date of any row in the report (gift-balance rows included). (4) Near-miss 5% is a percentage of the charge; for Amazon and IndiGo it considers sums of invoices (nearest first, then fewest), for other vendors single invoices. (5) Same-day credits (8b) means all Amazon credits dated that day. (6) Lines a person changed, and invoices a person attached, are left alone by a re-run. (7) An absurdly large exact-sum search (over 3 million steps for one charge) stops and gives a Review asking for a manual match, instead of hanging; a near-miss search that large simply finds no suggestion. (8) Matching runs inside the request (a few seconds) with the cycle's job columns as a lock that is always released; there is no progress bar. |
| 2026-10-15 | Slice 9 approval (planning chat): decisions (1) and (2) above are approved as **rule clarifications** and §8 now says so in rule 7 (invoice date or order date, incl. "Booking Date", within 7 days) and rule 8 (a Review suggestion reserves its invoices); `flow.md` updated to match. **Measured:** the engine takes 9 ms and a June run through the API with no network 0.03 s, but each Supabase call from the user's PC costs about 0.45 s and a run makes 13 sequential calls plus 127 line updates, so a real run is estimated at about 18 s (reads measured, writes assumed equal); the oversized-search guard stops one charge after about 0.5 s (exact sums) or 1 s (near miss). A run can therefore exceed 10 s, so **Slice 10 makes matching a background job with progress (like invoice reading) before the Results screen is built**, and cuts the per-line writes. |
| 2026-10-16 | Slice 10 (Results and review). Decisions taken while building, all open to change at the approval: (1) **matching is a background job** (the Slice 9 timing record): `POST …/match` returns 202, progress is kept on the cycle row and every message of this job starts with "Matching" (that is how the screens tell it from the reading jobs that share the columns; no new column, no SQL), the lines are written in one bulk call and the reads run in parallel; (2) the drawer's sum, difference and foreign-currency comparison are worked out in `engine/results.py` and the drawer asks the server for a **preview** after every staged change, so no money rule lives in the browser; (3) a status can be set by hand only to Matched, Review, Missing invoice or No invoice, and Matched needs an invoice attached; (4) an invoice used by another line, or reserved by another line's Review suggestion, cannot be attached; leaving Review drops the line's other suggestions so they stop reserving invoices; (5) a non-zero difference needs a note written by a person, enforced by the server as well as the drawer (the Slice 3 rule); (6) an exported reconciliation is not changed (the Slice 6 rule), although `flow.md` §2 draws an exported -> matched edit loop: to settle in Slice 11; (7) reasons for unused invoices are wording chosen in this slice (credit note; no vendor set; no total read; dated after the statement date; no statement line for the vendor; a charge of this amount exists but is matched to another invoice; no charge of this amount found); (8) a hand change marks the line (`updated_by`), so a new run leaves it exactly as it is. |
| 2026-10-16 | Slice 10 approval (planning chat): (a) **Exported reconciliations ARE editable** (`flow.md` §2 and §8 stand, which replaces item (6) of the line above): the first edit after an export moves the cycle back to `matched` with a visible "edited since export" note, and exporting again sets `exported`; built in Slice 11 together with the export endpoint (until then an exported cycle is refused). (b) A credit-note invoice (`is_credit_note`) **cannot be attached to a debit line**: the server refuses with "A credit note can't be attached to a charge. Attach it to a credit line instead" (preview and save), and the drawer does not offer credit notes for a charge. (c) A matching run left `running` by a dead worker shows as failed after 3 minutes (the limit shared with statement and invoice reading, `JOB_STALE_SECONDS` = 180) and a new run may then start; tested. (d) The "Matching" message-prefix check is to be replaced by a job kind field when that code is next touched; it needs a new column on `recon_cycles` (the job state is three plain columns, not JSON), so it needs a migration. (e) Tests 10.7 and 10.12 move to Slice 12's acceptance run (12.7 and 12.8). (f) "Dismiss a Review suggestion" is added to the After-MVP list. |
| 2026-10-16 | Slice 11 (Excel export). Decisions taken while building, open to change at the approval: (1) **exported reconciliations are editable** as decided at the Slice 10 approval: `note_edit` moves an `exported` cycle back to `matched` on the first edit (resolve, attach, detach, note, a corrected invoice, setting a file aside, new files, reading invoices, a new matching run) and writes `edited_after_export`; downloading again sets `exported`; no new column: "edited since export" is `matched` plus an `exported` event (`last_event_at`); the old refusals of an exported cycle are removed, while deleting an exported cycle is still refused. (2) The **File Name** column lists every linked invoice, suggestions included (a Review line shows its suggested invoices), sorted by name: this is what `june_2026_expected_results.csv` does, and the June export agrees with that CSV on all 127 lines (date, description, amount, status, files). (3) Foreign amounts in the description are written short as in that CSV (`[36 USD]`, `[133.5 USD]`, `[8.99 USD]`); the §7 example `[86.12 USD]` is unchanged. (4) The Amount format is written with the symbol quoted (`"₹"#,##0.00;-"₹"#,##0.00`) so every Excel reads it; it shows the same. (5) The month sheet and the file name come from the statement date (`June 2026`, `CC Expense June 2026.xlsx`), falling back to the cycle label. (6) The Summary check block compares the sheet's debits with Purchases/Charges plus Cash Advances and its credits with Payments/Credits, with `ROUND(...,2)` so sums of decimals cannot show a false difference; counts and amounts per status are `COUNTIF`/`SUMIF` formulas, so a viewer that does not calculate formulas shows them empty until opened in Excel or Google Sheets. (7) The unused sheet has one row per invoice (a PDF holding two unused invoices appears twice, with each amount), in the invoice''s own currency. (8) New dependency `openpyxl`. |
| 2026-10-16 | Slice 11 approval (planning chat): the "Invoices not used" difference against `CC_Expense_June_2026.xlsx` is explained and accepted: the app lists **one row per invoice** (`280626_Amazon_1263.pdf` holds 2 invoices, so the app has 22 rows against 21 in the reference), and the reference also lists the 2 duplicate files and the statement copy, which the app shows as Duplicates and Ignored on the Invoices step instead. |
| 2026-10-16 | Slice 12 pre-work (decided at the Slice 11 approval, built before "start Slice 12"): (1) **job kind column**: migration `0004_recon_job_kind.sql` adds `recon_cycles.job_kind` (`statement` / `invoices` / `matching`, nullable, with a check); every job write sets it together with the other job columns and the "Matching" message prefix is no longer used to tell jobs apart; old matching rows are backfilled by the migration, other old rows stay null and count as "not a matching run"; it must be run before the new API is rebuilt or deployed. (2) **Dev packages out of the runtime image**: `backend/Dockerfile` installs the runtime dependencies in `base` and `.[dev]` only in the `test` stage; `pytest` and its plugins are not in the `api` image; `httpx` stays because Supabase itself depends on it. (3) The user sets every environment variable themself in Railway/Render and Vercel; no secret value is ever sent in chat. (4) Tests 10.7 and 10.12 run inside the Slice 12 acceptance run (12.7, 12.8). |
| 2026-10-16 | Slice 12 (deploy), decisions taken while building: (1) the API goes to **Railway** (user's choice): `backend/railway.toml` builds `backend/Dockerfile` (Root Directory `backend`), health check `/api/health`, **one replica** because the background jobs run in the API process and only their lock is in the database; Railway ships the Dockerfile's last stage, so `runtime` must stay last (a test checks it). (2) The web app goes to Vercel: `frontend/vercel.json` (Vite build, a rewrite to `index.html` so reloading a deep link works, three basic security headers; no CSP yet). (3) `CORS_ORIGINS` ignores a trailing slash; a production frontend build without `VITE_API_BASE_URL` shows "The app is not configured" instead of calling localhost. (4) Supabase Auth: the Vercel URL is **added** to the Redirect URLs and the **Site URL is left alone** (shared project; sign-in is email and password only). (5) `doc/runbook.md` holds the deploy steps, the variable list, adding a user, rotating keys and the unreconciled-statement procedure. (6) The developer deploys nothing and never sees a secret: the user sets every value in Railway and Vercel. (7) New tests 12.9 (CORS), 12.10 (deep-link reload) and 12.11 (add and remove a user) join 12.7 and 12.8 in the acceptance run. |
| 2026-10-16 | Slice 10b (Amazon follow-ups, narrowed by the planning chat; no SQL). Decisions taken while building, open to change at the approval: (1) the **"Amazon invoices to fetch"** list is worked out on read from what is saved, choosing each charge's payment group with the matcher's own functions in the matcher's order, so it agrees with the notes matching wrote; it needs a report and a matching run; it lists orders with **no** invoice by Order ID (an order with an invoice that covers only part of it is counted, not listed); credits, reversals, fees, payments, near-miss groups and lines a person changed are not looked at. (2) An **Amazon invoice with no readable or misread Order ID is `needs_check`** (one rule for reading and for a person's correction), so an uploaded invoice is never silently counted as a missing order; the list shows how many there are. (3) New **unused-invoice reasons** (also in the Excel's reason column, which uses the same function; no other Excel change): "Dated after the last Amazon charge on this statement (dd/mm)", and with a report "Paid by gift balance", "Paid on another card", "Paid on dd/mm (after this statement)"; the same-amount reason now compares dollar amounts for USD invoices and says what happened to that charge. When the statement date and the last Amazon charge both apply, the statement date wins. (4) **Restore** brings back a file a person set aside; a statement copy cannot be restored; the restored file is read by the next "Read invoices". (5) Measured September figure replaces the earlier "about a third": **24 of 60 card-paid orders (40%) had no invoice, and 2 more only partly**; all 5 gift-balance orders had an invoice. (6) Why the June statement shows charges from 21 and 26 May as Missing invoice: the statement period is **21 May to 28 June**, but the invoice set started on 01/06; 11 of June's 20 Missing lines (₹42,801.80, 7 vendors) are dated 21 to 28 May. Download invoices and the Amazon report for the whole statement period. Not built, now on the After-MVP list: the order-by-order drawer section, Order IDs in the Amazon panel, the invoice-only shortfall note, listing partly invoiced orders. |

## 12. Open questions (do not guess; ask the user)

1. **Other banks or cards.** Will the client ever upload statements from another bank or card? (Only ICICI is supported.)
2. **Missing-invoice step.** How does the client obtain the invoices that Amazon's bulk download leaves out (September: 24 of 60 card-paid orders, 40%, plus 2 more only partly invoiced)? With the report uploaded, the Results step lists them (Slice 10b); without it the tool cannot name them.
3. **Pre-fee USD amount.** Does the accounts team want the pre-fee USD amount as an extra column? The default is the amount actually charged.
4. **Allowed users.** Initial list (2026-10-13): `harsh@create-ed.in` only. Kept open: more addresses are added later by editing the comma-separated `ALLOWED_EMAILS` backend env var (no code change).
5. ~~**Existing table names.**~~ Resolved 2026-10-13: `payment_requests` and `payment_webhook_events`.
