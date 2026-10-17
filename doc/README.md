# doc/

Documentation for the credit-card expense reconciliation app. Read the files in this order:

1. `project_context.md`: what we are building, facts verified on real data, matching rules, constraints and the decision log. **This file is authoritative.**
2. `architecture.md`: stack, repository layout, `recon_*` tables, API and environment variables.
3. `flow.md`: the user flow, the cycle status machine, and the processing flows.
4. `design.md`: design tokens and screens, based on the v0 export in `design_reference/`.
5. `implementation_plan.md`: the slices. Each one ends with manual tests the user runs before the next slice starts.
6. `memory.md`: approved progress, written by the dev chat after each slice approval.
7. `runbook.md`: how to deploy (Railway, Vercel, Supabase), add a user, rotate keys, and what to do when a statement does not reconcile.

The `design_reference/` folder holds the v0 (Vercel) UI export: `page.tsx` is the visual source of truth, and `design.md` explains how to port it.

The `reference/` folder holds evidence from the June 2026 prototype run:

- `parse_stmt.py`, `extract_inv.py`, `match.py`: prototype scripts that produced the June result. **Reference only.** Rebuild them cleanly in `backend/app/engine/`.
- `june_2026_expected_results.csv`: the reviewed result for all 127 June statement lines. Slice 9 must reproduce its statuses and files. It contains the client's transaction data, so keep the repository private.
