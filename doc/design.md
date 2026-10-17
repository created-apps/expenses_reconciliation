# Design

The UI was designed in **v0 (Vercel)** on 13 Oct 2026. The export is kept, unchanged, in `doc/design_reference/`:

| File | What it is |
|---|---|
| `page.tsx` | **All screens** in one Next.js client component (state-switched, no routing). This is the visual source of truth |
| `mocks.ts` | v0's mock data. **Do not reuse.** Shapes and some values are wrong (see §8) |
| `globals.css` | Tailwind v4 + shadcn theme variables |
| `button.tsx`, `components.json` | shadcn `base-nova` style, Button on `@base-ui/react` |
| `package.v0.json` | v0 dependencies (Next 16, React 19, Tailwind 4, shadcn 4, `@base-ui/react`, lucide-react) |

**Rule for the dev chat:** reproduce the **look** of `page.tsx` exactly: colours, sizes, spacing, layout and copy. **Rebuild the structure** cleanly as described here: real components, React Router, typed props, no Next.js. Where v0 left something out, build it in the same visual language using the tokens in §2. Do not invent a new style.

---

## 1. Users and principles (unchanged)

- **Users:** 2–5 non-technical accounts and admin staff, used once a month for 30–60 minutes, on desktop or laptop. Tablet must not break.
- **The one question the UI answers:** "Which lines still need me, and why?" Review and Missing invoice always come first. Evidence (the invoice file) is one click away.
- **Tone:** calm, professional, Excel-literate. No gradients, glass effects, glows, emoji, illustrations or marketing copy.

## 2. Design tokens (taken from the v0 export)

Use these exact values. They are Tailwind classes as used in `page.tsx`.

| Token | Value |
|---|---|
| Page background | `#FAFAF9` (`bg-[#fafaf9]`) |
| Surface | white, `border border-stone-200` (#E7E5E4), `rounded-md` |
| Row divider | `border-stone-100` |
| Table header | `bg-stone-50`, `text-[11px] font-medium uppercase tracking-wide text-stone-500`, cell padding `px-4 py-3` |
| Table body | `text-[12px]` (home table `text-[13px]`), row hover `bg-stone-50`, row height about 40px |
| Primary text / secondary / muted | `text-stone-900` / `text-stone-600` / `text-stone-500`; disabled and empty `text-stone-400` |
| Accent | teal `#0F766E` (`bg-[#0f766e]`), hover `#0D625C`; links `text-teal-700`; active nav `bg-teal-50 text-teal-800` |
| Focus (inputs) | `focus:border-teal-600 focus:ring-2 focus:ring-teal-100` |
| Page title | `text-[22px] font-semibold tracking-[-0.02em]`; description `text-[13px] text-stone-500 mt-1`; header `border-b pb-5` |
| Section title | `text-[14px] font-semibold` |
| Stat tile | label `text-[11px] uppercase tracking-wide text-stone-500`; value `text-[16px] font-semibold tabular-nums`; check line `text-[11px] text-emerald-700` |
| Primary button | `h-9 px-3.5 rounded-md bg-[#0f766e] text-[13px] font-medium text-white shadow-sm`, disabled `opacity-40` |
| Secondary button | `h-9 px-3 rounded-md border border-stone-200 bg-white text-[13px] font-medium text-stone-700 hover:bg-stone-50` |
| Inputs | `h-8`/`h-9`, `rounded`, `border-stone-200`, `text-[12px]` |
| Filter chips (Invoices) | `rounded-full px-3 py-1.5 text-[12px]`; active `bg-stone-900 text-white`; inactive `bg-stone-100 text-stone-600` |
| Numbers | Always `tabular-nums`; amounts right-aligned; credits `text-red-700` with `−` |
| Sidebar | `w-[220px]`, white, `border-r`, app name "Reconcile" `text-[15px] font-semibold` |
| Content | `max-w-[1240px] mx-auto`, padding `px-5 py-6` / `md:px-10 md:py-8` |
| Drawer | Right side, `w-[560px]` (full width at 900px or below), overlay `bg-stone-900/10`, `shadow-xl`, `p-6` |
| Font | **Inter.** v0 did not load it; add `@fontsource-variable/inter` and set it as the `--font-sans` |
| Theme | **Light only.** Remove the `.dark` and `prefers-color-scheme: dark` blocks from `globals.css` (the screens use fixed stone/white classes, so dark mode would half-apply) |

### Status badges

Pill style: `rounded-full px-2 py-0.5 text-[11px] font-medium`.

| Status | Background / text |
|---|---|
| Matched | `#E2EFDA` / `#166534` |
| Review | `#FFF2CC` / `#92400E` |
| Missing invoice | `#FCE4D6` / `#9A3412` |
| No invoice | `stone-100` / `stone-700` |
| Reversed, Payment, Bank charge | `stone-100` / `stone-600` |
| Credit – manual | `#E4EAF4` / `#365277` |

**Cycle status badges:**

| Cycle state | Label | Style |
|---|---|---|
| `draft` | Draft | stone |
| `statement_parsed` | Statement check | amber (Review style) |
| `statement_confirmed`, `invoices_extracted` | Invoices | slate blue (Credit style) |
| `matched` | Matched | green |
| `exported` | Exported | green |

## 3. Layout and navigation

- **App shell:** sidebar (Reconcile, nav item "Reconciliations"; user email and "Sign out" pinned at the bottom) plus the content area.
- **Below `md`:** v0 hides the sidebar and gives no replacement. **Add a top bar** (app name, menu button opening the same nav as a sheet).
- **Routing** (React Router, replacing v0's `useState<Screen>`):

| Route | Screen |
|---|---|
| `/login` | Login |
| `/` | Reconciliations |
| `/cycles/new` | New reconciliation |
| `/cycles/:id/statement` | Step 1 |
| `/cycles/:id/invoices` | Step 2 |
| `/cycles/:id/results` | Step 3 (tab query `?tab=unused`) |
| `/cycles/:id/export` | Step 4 |

- **Detail header** (all four steps):
  - "← All reconciliations" link, then a page header with the title (e.g. "June 2026") and the subtitle "Statement 21/05/2026 – 28/06/2026 · ICICI · cards 4002, 2492".
  - Then the **Stepper**: 4 steps; done = filled teal circle with a check; current = teal outline; future = stone. Connecting lines are teal when passed. Clicking is allowed only for reached steps.

## 4. Screens: what v0 delivered

| Screen | In v0 export | Port notes |
|---|---|---|
| Reconciliations (home) | Yes | Table: Month, Statement period, Status, Progress (text plus a thin 64px bar), Open items (amber and bold when > 0), Last updated, chevron. Make the bar width the real `matched/total`, not a fixed `w-1/2` |
| New reconciliation | Yes | Three stacked upload cards (max-w 760px): title + "Required · one PDF" hint, helper text, dashed drop zone "Drop files here or browse", file rows (icon, name, size, remove). Footer Cancel / Continue. **Add** per-file status (Uploading, Uploaded, Duplicate, Not supported) and the disabled-Continue rule |
| Step 1 Statement | Yes | 4 stat tiles in one row; "Statement lines · 127 lines" table card; "Confirm statement" button at the bottom right. "Download PDF" opens the statement via signed URL |
| Step 2 Invoices | Partly | Summary sentence ("126 files · 126 invoices · 3 need a check · 2 duplicates · 1 ignored", "need a check" in amber), "Run matching" at top right, filter chips, table, drawer with preview box and a 2-column field grid, buttons "Not an invoice" / "Save" |
| Step 3 Results | Yes (main) | Header row with keyboard hints (`j` `k` move, `Enter` open, `Esc` close); 8 status filter tiles (grid of 8 on desktop, 2 columns on small screens); toolbar (search, Vendor, Card, Re-run matching); fixed-layout table; empty state "Nothing needs review." / "This filter is clear for now." |
| Transaction drawer | Partly | Header (description, date · ID, large amount); **Why**; **Attached invoices** with Charge / Attached tiles and a Difference row (green ₹0.00, otherwise amber); **Find an invoice** search with result rows and an "Attach" link; Status select and Note; Save; audit line |
| Step 4 Export | Yes | "Ready to export" card: 4 counters (Matched, Review, Missing invoice, Other); two totals lines (debits and credits against the statement) with the difference in green; amber notice "5 lines still need review. You can export anyway."; an amber "Edited since the last export" notice (also shown on every step) after an edit; list of the three sheets; "Download Excel" |

## 5. Screens and states v0 did not deliver

Build these in the same style. Use the §2 tokens only.

1. **Login** (`/login`):
   - Centred white card (`max-w-[380px]`, `border border-stone-200 rounded-md p-6`) on the page background.
   - "Reconcile" `text-[15px] font-semibold`, then "Sign in" `text-[22px]`.
   - Email and password inputs (`h-9`), a full-width Primary "Sign in".
   - Error as `text-[12px] text-red-700` under the form.
   - No sign-up link. Under the card: "Accounts are created by your administrator." (`text-[12px] text-stone-500`).
2. **Statement mismatch state:**
   - A red banner above the tiles: `border border-red-200 bg-red-50 text-red-800 text-[12px] p-3 rounded-md` with `AlertTriangle`: "Debits don't match the statement by ₹1,811.07. The statement can't be confirmed."
   - The failing tile's check line becomes red with `X`.
   - "Confirm statement" is disabled.
3. **Amazon report panel** (Step 2, under the summary line):
   - A collapsible card "Amazon Business report · 10 payment groups".
   - Table: Payment date, Reference, Orders, Amount.
   - A second small list: "Paid by gift balance (not on the card): 5 orders".
   - When no CSV was uploaded, one line: "No Amazon report uploaded. Amazon charges are matched on invoice totals only."
4. **Suggested invoices** (transaction drawer, between Why and Attached; only for Review lines):
   - Rows like the "Find an invoice" results.
   - A **Primary** "Accept suggestion" button.
   - Text: "Closest invoice is ₹149.00 less."
5. **Attached invoices, done properly:**
   - One row per invoice with **its own amount**. (v0 shows the charge amount on every row; this is wrong.)
   - The Attached tile shows the **sum** of invoices.
   - The Difference row is charge − sum.
   - Each row has a remove (`X`) action.
   - Saving a non-zero difference requires a note written by a person: the note box starts with the system's own reason, and leaving that untouched does not count (unless a person already saved it).
6. **Unused invoices tab** (Step 3):
   - Two tabs above the filter tiles: "Statement lines" | "Unused invoices (24)", text style `text-[13px]` with a teal underline for the active tab.
   - Table: File, Vendor, Date, Amount, Reason.
7. **Loading:**
   - Skeleton rows (`bg-stone-100 animate-pulse`, 5 rows) inside the table card.
   - Stat tiles show grey bars.
8. **Background job:**
   - A bar under the stepper: `h-1.5 rounded-full bg-stone-100` with a teal fill, and the message `text-[12px] text-stone-600` ("Reading invoices 48 of 126…").
   - Content below at `opacity-50 pointer-events-none`.
9. **Error banner:** same as the mismatch banner, plus a Secondary "Retry" button on the right.
10. **Toasts:** use shadcn `sonner`, bottom right, plain text ("Saved", "Matching finished: 65 matched, 5 to review").
11. **Read actions and pre-read states:**
    - Statement step before reading: an empty table card with one line ("The statement hasn't been read yet.") and a Primary **Read statement** button. After a mismatch, the same button reads "Read again" next to a Secondary "Replace statement".
    - Invoices step before reading: summary line "126 files uploaded · not read yet" and a Primary **Read invoices** button in place of "Run matching".
12. **Add files to an existing reconciliation:**
    - A Secondary **Add files** button in the Invoices step header. It opens a sheet with the same Invoices and Amazon Business report upload cards as the New reconciliation screen.
    - After adding, a notice: "3 new files. Read invoices and run matching again to include them."
13. **Delete reconciliation:**
    - Row "…" menu on the home table: "Delete".
    - A confirm dialog: "Delete June 2026 and its uploaded files? This can't be undone." with buttons Cancel and Delete (`bg-red-700`).
    - Hidden for exported cycles.

## 6. Fixes to v0 behaviour (do not port these)

- **Status tiles:** Review and Missing invoice always get amber classes, which clash with the active (teal) style. Keep amber when inactive; when active, use the teal active style plus an amber left border (`border-l-2 border-l-amber-400`).
- **Results filter:** it starts on "Review". Default to **Review if any exist, otherwise Missing invoice, otherwise All**. Add an **All** tile/option. v0 has no way to see every line.
- **Esc listener:** remove the module-level `window.addEventListener('keydown', …)` at the bottom of `page.tsx`. Esc handling belongs to the drawer (shadcn `Sheet` handles it).
- **Drawer:** use shadcn `Sheet` (side right) for focus trap and accessibility instead of the hand-made `Drawer`.
- **Layout and metadata:** `layout.tsx` uses Next `metadata` and `@vercel/analytics/next`. Drop both; set the title in `index.html` ("Reconcile").
- **Mock data:** amounts are strings. Use paise numbers and `formatINR` (§7).
- **Configuration:** `next.config.mjs` has `ignoreBuildErrors: true`. Do not carry this over; the Vite build must type-check.

## 7. Formatting helpers

- `formatINR(paise, {credit})` → `₹1,05,980.00`; credits `−₹52,990.00` (`Intl.NumberFormat('en-IN', {minimumFractionDigits:2})`).
- Foreign amount: `$122.25` as secondary text under the description.
- `formatDate` → `dd/mm/yyyy`.
- Summary amounts in status tiles are rounded to whole rupees (`₹5,41,727`). Tables and drawers always show paise.

## 8. Mock data (use these; replaces v0 `mocks.ts`)

Types are as in the API (`architecture.md` §5). Reuse the 10 transaction rows from v0 `mocks.ts`, with these corrections:

- Amounts become paise numbers.
- `id` becomes `serNo` (and add a uuid `id`).
- `files` becomes `invoices: InvoiceRef[]`, with **each invoice's own total**.
- `foreign` becomes `{amount, currency}`.

**Correct June figures for the status tiles** (from the real June run):

| Status | Count | Amount |
|---|---|---|
| Matched | 65 | ₹5,41,726.64 |
| Review | 5 | ₹1,24,153.96 |
| Missing invoice | 20 | ₹76,593.63 |
| No invoice | 6 | ₹20,437.00 |
| Reversed | 8 | ₹0.00 (net) |
| Credit – manual | 4 | −₹55,985.60 |
| Payment | 1 | −₹60,472.00 |
| Bank charge | 18 | ₹78,586.99 |

**Correct invoice mocks** (v0's were invented; these are real June invoices):

| File | Vendor | Invoice no. | Date | Amount | Source |
|---|---|---|---|---|---|
| 200626_Amazon_52390.pdf | Amazon | DEL5-1028774 | 20/06/2026 | ₹52,390.00 | PDF |
| 190626_Macfos_715.pdf | Robu (Macfos) | INV2627/105815 | 19/06/2026 | **₹611.00** | PDF |
| Supabase_.pdf | Supabase | (from invoice) | 20/06/2026 | $122.25 | PDF |
| 130626_Amazon_928.27.pdf | Amazon | IN-9370 | 13/06/2026 | ₹928.27 | PDF |
| 140626_Amazon_173.63.png | Amazon | WBL7-21429 | 14/06/2026 | ₹173.63 | Image (AI) |
| TaxInvoiceDL1262706AU17753.pdf | IndiGo | PNR EBU8WT | 07/06/2026 | ₹8,268.00 | PDF |

The 8 attached invoices for SerNo 13598184078 (₹2,557.44) total exactly ₹2,557.44: 187.16 + 198 + 220 + 238 + 499 + 928.27 + 98.01 + 189.

## 9. Accessibility

- Contrast 4.5:1.
- Visible focus rings (teal).
- Status is always shown as text, never by colour alone.
- Keyboard: `j`/`k`/`Enter` on Results (ignored while typing in an input); `Esc` closes sheets.
- Amounts right-aligned with `tabular-nums`.
