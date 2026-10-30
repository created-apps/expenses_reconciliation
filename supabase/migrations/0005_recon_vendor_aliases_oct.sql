-- 0005_recon_vendor_aliases_oct.sql
-- Reconcile: vendors that appeared on the October 2026 statement but were not in the vendor table,
-- so their invoices came out as "No vendor set" and their lines as "No invoice".
--
-- statement_pattern: regex on the statement description. invoice_pattern: regex on the invoice TEXT (never the file
-- name). Both are applied case-insensitively. The invoice pattern is the issuer's own name as printed on the invoice.
--
-- Touches ONLY recon_vendor_aliases. Idempotent: upserts on vendor_key. The two rows that already existed
-- (sembly, phantombuster) are reset to the values below, the rest are new.
-- Run after 0003. Needs no change to the API's configuration; the vendor table is read on every run.

insert into recon_vendor_aliases
  (vendor_key, display_name, statement_pattern, invoice_pattern, match_mode, date_before_days, date_after_days, active)
values
  ('indianhobbycenter', 'IHC',            'INDIANHOBBYCENTER',          'THE HOBBY SHOP|indianhobbycenter', 'single', 7, 7, true),
  ('sembly',            'Sembly',         'SEMBLY',                     'Sembly',                           'single', 7, 7, true),
  ('krisp',             'Krisp',          'KRISP',                      'Krisp',                            'single', 7, 7, true),
  ('gamma',             'Gamma',          'GAMMA\.APP',                 'gamma\.app',                       'single', 7, 7, true),
  ('stealthwriter',     'Stealthwriter',  'PADDLE\.NET\* STEALTH',      'Stealthwriter',                    'single', 7, 7, true),
  ('promeal',           'Promeal Biotech','PROMEAL BIOTECH',            'Promeal',                          'single', 7, 7, true),
  ('retailmumbai',      'Retail Mumbai',  'RETAIL CC MUMBAI',           'IndoSurgicals',                    'single', 7, 7, true),
  ('phantombuster',     'PhantomBuster',  'PHANTOMBUSTER',              'Phantom ?Buster|The Phantom Company', 'single', 7, 7, true),
  ('netflix',           'Netflix',        'NETFLIX',                    'Netflix',                          'single', 7, 7, true),
  ('linkedin',          'LinkedIn',       'LINKEDIN',                   'LinkedIn',                         'single', 7, 7, true)
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
--   select count(*) from recon_vendor_aliases;   -- 40 (the 32 from 0003 + 8 new; sembly and phantombuster were already there), and still 40 after running this file again
--   select vendor_key, display_name, statement_pattern from recon_vendor_aliases
--    where vendor_key in ('indianhobbycenter','sembly','krisp','gamma','stealthwriter','promeal','retailmumbai',
--                         'phantombuster','netflix','linkedin') order by 1;      -- 10 rows
--   Each statement pattern should hit its sample (case-insensitive):
--   select vendor_key from recon_vendor_aliases where 'PADDLE.NET* STEALTH WR London GB*' ~* statement_pattern;  -- stealthwriter
--   select vendor_key from recon_vendor_aliases where 'IND*LINKEDIN (PGSI) WWW.LINKEDIN.' ~* statement_pattern;  -- linkedin

-- ---------------------------------------------------------------------------
-- ROLLBACK (only if asked)
-- ---------------------------------------------------------------------------
--   delete from recon_vendor_aliases where vendor_key in (
--     'indianhobbycenter','krisp','gamma','stealthwriter','promeal','retailmumbai','netflix','linkedin');
--   -- sembly and phantombuster: re-run 0003 to put them back as they were.
