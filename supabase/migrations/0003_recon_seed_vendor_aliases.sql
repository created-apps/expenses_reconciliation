-- 0003_recon_seed_vendor_aliases.sql
-- Reconcile: seed data for recon_vendor_aliases, from doc/project_context.md section 5.2.
--
-- statement_pattern: regex on the statement description (how the vendor appears on the card statement).
-- invoice_pattern:   regex on the invoice TEXT (never the file name). NULL where the docs give none.
-- Patterns are applied case-insensitively by the engine.
--
-- match_mode: 'subset' = several invoices can add up to one charge (Amazon, IndiGo);
--             'single' = one invoice per charge; 'none' = no invoice expected.
-- Date window (days before / after the transaction date): Amazon 3/0, IndiGo 3/1, all others 7/7.
--
-- Touches ONLY recon_vendor_aliases. Idempotent: upserts on vendor_key, so running it again
-- RESETS these seeded rows to the values below (it overwrites later edits to the same vendor_key).
-- Run order: 0001, 0002, 0003.

insert into recon_vendor_aliases
  (vendor_key, display_name, statement_pattern, invoice_pattern, match_mode, date_before_days, date_after_days, active)
values
  -- Subset vendors
  ('amazon',        'Amazon',                 'ASSPL|AMAZONIN',    'Amazon Seller Services|ASSPL-Amazon|Amazon Wholesale|amazon\.in', 'subset', 3, 0, true),
  ('indigo',        'IndiGo',                 'INDIGO AIRLINE',    'InterGlobe Aviation',          'subset', 3, 1, true),

  -- Single-invoice vendors with their own invoice-text identifier in section 5.2
  ('macfos',        'Robu (Macfos)',          'MACFOS LIMITED',    'MACFOS',                       'single', 7, 7, true),
  ('dtdc',          'DTDC',                   'WWW DTDC IN',       'DTDC',                         'single', 7, 7, true),
  ('makemytrip',    'MakeMyTrip',             'MAKEMYTRIP',        'MakeMyTrip',                   'single', 7, 7, true),
  ('tripify',       'Tripify',                'TRIPIFY',           'Tripify',                      'single', 7, 7, true),
  ('vistaprint',    'Vistaprint',             'VISTAPRINT',        'Cimpress',                     'single', 7, 7, true),
  ('shott',         'Shott Amusement',        'SHOTT AMUSEMENT',   'Shott Amusement',              'single', 7, 7, true),
  ('periskope',     'Periskope',              'PERISKOPE',         'Hashlabs Holdings',            'single', 7, 7, true),
  ('mailchimp',     'Mailchimp',              'MAILCHIMP',         'Mailchimp|Intuit',             'single', 7, 7, true),
  ('airtel',        'Airtel',                 'WWW AIRTEL',        'Airtel',                       'single', 7, 7, true),
  ('aqtronics',     'AqTronics',              'AQTRONICS',         'AqTronics',                    'single', 7, 7, true),

  -- SaaS vendors: invoices carry their own name; invoices are in USD (match on the USD amount)
  ('fathom',        'Fathom',                 'FATHOM',            'Fathom',                       'single', 7, 7, true),
  ('vercel',        'Vercel',                 'VERCEL',            'Vercel',                       'single', 7, 7, true),
  ('supabase',      'Supabase',               'SUPABASE',          'Supabase',                     'single', 7, 7, true),
  ('zapier',        'Zapier',                 'ZAPIER',            'Zapier',                       'single', 7, 7, true),
  ('railway',       'Railway',                'RAILWAY',           'Railway',                      'single', 7, 7, true),
  ('anthropic',     'Anthropic',              'ANTHROPIC',         'Anthropic',                    'single', 7, 7, true),
  ('genspark',      'Genspark',               'GENSPARK',          'Genspark',                     'single', 7, 7, true),
  ('scriptit',      'ScriptIt',               'SCRIPTIT',          'ScriptIt',                     'single', 7, 7, true),
  ('sembly',        'Sembly',                 NULL,                'Sembly',                       'single', 7, 7, true),

  -- Vendors listed in section 5.2 whose invoice-text identifier the docs do not give:
  -- the invoice pattern below is the vendor's own name (ASSUMED; confirm in Slices 6-7 on real files).
  ('calendly',      'Calendly',               'CALENDLY',          'Calendly',                     'single', 7, 7, true),
  ('phantombuster', 'Phantombuster',          'PHANTOMBUSTER',     'Phantombuster',                'single', 7, 7, true),
  ('google',        'Google',                 'GOOGLE CLOUD',      'Google',                       'single', 7, 7, true),
  ('microsoft',     'Microsoft',              'MICROSOFT',         'Microsoft',                    'single', 7, 7, true),
  ('openai',        'OpenAI',                 'OPENAI',            'OpenAI',                       'single', 7, 7, true),
  ('wix',           'Wix',                    'WIX',               'Wix',                          'single', 7, 7, true),
  ('robocraze',     'RoboCraze',              'ROBOCRAZE',         'RoboCraze',                    'single', 7, 7, true),
  ('thinkrobotics', 'thinkrobotics',          'ATLANTIS ROBOTICS', 'thinkrobotics',                'single', 7, 7, true),

  -- Invoice-side only: section 5.2 lists the invoice identifier but no statement descriptor
  ('chempure',      'Chempure',               NULL,                'Chempure',                     'single', 7, 7, true),

  -- No invoice expected
  ('created',       'CREATED (own entity)',   'CREATED ANDHERI WEST', NULL,                        'none',   7, 7, true),
  ('food',          'Food and restaurants',   'SWIGGY',            NULL,                           'none',   7, 7, true)
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
--   select vendor_key, match_mode, date_before_days, date_after_days
--     from recon_vendor_aliases order by 1;
--   expect 32 rows including: amazon/subset 3/0, indigo/subset 3/1, macfos/single 7/7,
--   dtdc/single, fathom/single; created and food are 'none'.
--   select count(*) from recon_vendor_aliases;   -- 32, and still 32 after running this file again
--
--   Each statement pattern should hit the right sample (case-insensitive):
--   select vendor_key from recon_vendor_aliases
--    where 'WWW DTDC IN BANGALORE IN' ~* statement_pattern;   -- dtdc

-- ---------------------------------------------------------------------------
-- ROLLBACK (only if asked)
-- ---------------------------------------------------------------------------
--   delete from recon_vendor_aliases where vendor_key in (
--     'amazon','indigo','macfos','dtdc','makemytrip','tripify','vistaprint','shott','periskope',
--     'mailchimp','airtel','aqtronics','fathom','vercel','supabase','zapier','railway','anthropic',
--     'genspark','scriptit','sembly','calendly','phantombuster','google','microsoft','openai',
--     'wix','robocraze','thinkrobotics','chempure','created','food');
