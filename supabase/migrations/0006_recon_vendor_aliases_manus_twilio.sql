-- 0006_recon_vendor_aliases_manus_twilio.sql
-- Reconcile: two more vendors for the vendor list (and for matching): Manus and Twilio.
--
-- statement_pattern: regex on the statement description. invoice_pattern: regex on the invoice TEXT (never the file
-- name). Both are applied case-insensitively. The patterns are the vendors' own names (assumed, not yet seen on a
-- real statement line or invoice): if a real descriptor or issuer name differs, change the row (see below) or add
-- the vendor by hand in the app.
--
-- Touches ONLY recon_vendor_aliases. Idempotent: upserts on vendor_key.
-- Run after 0005. Needs no change to the API's configuration; the vendor table is read on every run.

insert into recon_vendor_aliases
  (vendor_key, display_name, statement_pattern, invoice_pattern, match_mode, date_before_days, date_after_days, active)
values
  ('manus',  'Manus',  'MANUS',  'Manus',  'single', 7, 7, true),
  ('twilio', 'Twilio', 'TWILIO', 'Twilio', 'single', 7, 7, true)
on conflict (vendor_key) do update set
  display_name      = excluded.display_name,
  statement_pattern = excluded.statement_pattern,
  invoice_pattern   = excluded.invoice_pattern,
  match_mode        = excluded.match_mode,
  date_before_days  = excluded.date_before_days,
  date_after_days   = excluded.date_after_days,
  active            = excluded.active;

-- ---------------------------------------------------------------------------
-- VERIFICATION
-- ---------------------------------------------------------------------------
--   select vendor_key, display_name, statement_pattern, invoice_pattern from recon_vendor_aliases
--    where vendor_key in ('manus','twilio') order by 1;                                  -- 2 rows
--   select count(*) from recon_vendor_aliases;   -- 42 if no vendor was added by hand in the app (40 from 0003 + 0005, plus these 2), and unchanged after running this file again
--   select vendor_key from recon_vendor_aliases where 'TWILIO SENDGRID DENVER CO' ~* statement_pattern;  -- twilio

-- ---------------------------------------------------------------------------
-- ROLLBACK (only if asked)
-- ---------------------------------------------------------------------------
--   delete from recon_vendor_aliases where vendor_key in ('manus','twilio');
