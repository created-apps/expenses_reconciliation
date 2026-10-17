-- 0001_recon_core.sql
-- Reconcile: core tables, constraints, indexes, row-level security and the updated_at trigger.
--
-- Touches ONLY recon_* objects (and the function recon_set_updated_at).
-- It never reads, alters or drops any other table (for example payment_requests, payment_webhook_events).
-- Idempotent: safe to run more than once.
--
-- Conventions: money is integer paise (*_paise) or minor units (*_minor) plus a currency code.
-- Credit lines are stored with a positive amount and is_credit = true.
-- Every table has row-level security ENABLED and NO policies, so only the service role
-- (the backend) can read or write. Do not add policies.
--
-- Run order: 0001, 0002, 0003.

-- ---------------------------------------------------------------------------
-- updated_at trigger function
-- ---------------------------------------------------------------------------
create or replace function recon_set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- recon_cycles: one statement and its month of work
-- ---------------------------------------------------------------------------
create table if not exists recon_cycles (
  id                        uuid primary key default gen_random_uuid(),
  label                     text,
  status                    text not null default 'draft',
  statement_date            date,
  period_start              date,
  period_end                date,
  summary_previous_paise    bigint,
  summary_purchases_paise   bigint,
  summary_credits_paise     bigint,
  summary_total_due_paise   bigint,
  statement_confirmed_at    timestamptz,
  statement_confirmed_by    text,
  job_status                text,
  job_progress              integer,
  job_message               text,
  created_by                text,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  constraint recon_cycles_status_check check (status in (
    'draft', 'statement_parsed', 'statement_confirmed',
    'invoices_extracted', 'matched', 'exported', 'failed'
  ))
);

-- ---------------------------------------------------------------------------
-- recon_files: every uploaded or extracted file
-- ---------------------------------------------------------------------------
create table if not exists recon_files (
  id              uuid primary key default gen_random_uuid(),
  cycle_id        uuid not null references recon_cycles(id) on delete cascade,
  kind            text not null,
  original_name   text not null,
  storage_path    text,
  sha256          text,
  mime_type       text,
  size_bytes      bigint,
  parent_file_id  uuid references recon_files(id) on delete cascade,
  status          text not null default 'uploaded',
  note            text,
  error           text,
  created_at      timestamptz not null default now(),
  constraint recon_files_kind_check check (kind in (
    'statement', 'invoice', 'amazon_report', 'zip', 'ignored'
  )),
  constraint recon_files_status_check check (status in (
    'uploaded', 'processed', 'failed', 'duplicate'
  ))
);

-- Duplicates are recorded (status = 'duplicate') but never count as a second live file.
create unique index if not exists recon_files_cycle_sha256_live_uq
  on recon_files (cycle_id, sha256)
  where status <> 'duplicate';

create index if not exists recon_files_cycle_id_idx on recon_files (cycle_id);
create index if not exists recon_files_parent_file_id_idx on recon_files (parent_file_id);

-- ---------------------------------------------------------------------------
-- recon_transactions: statement lines
-- status is NULL until matching has run; once set it must be one of the 8 statuses.
-- ---------------------------------------------------------------------------
create table if not exists recon_transactions (
  id                    uuid primary key default gen_random_uuid(),
  cycle_id              uuid not null references recon_cycles(id) on delete cascade,
  ser_no                text not null,
  txn_date              date not null,
  card_last4            text,
  description           text not null,
  reward_points         integer,
  foreign_amount_minor  bigint,
  foreign_currency      text,
  amount_paise          bigint not null,
  is_credit             boolean not null default false,
  vendor_key            text,
  status                text,
  notes                 text,
  sort_order            integer,
  updated_by            text,
  updated_at            timestamptz not null default now(),
  constraint recon_transactions_cycle_ser_no_uq unique (cycle_id, ser_no),
  constraint recon_transactions_amount_check check (amount_paise >= 0),
  constraint recon_transactions_status_check check (status in (
    'Matched', 'Review', 'Missing invoice', 'No invoice',
    'Reversed', 'Credit – manual', 'Payment', 'Bank charge'
  ))
);

create index if not exists recon_transactions_cycle_id_idx on recon_transactions (cycle_id);
create index if not exists recon_transactions_cycle_status_idx on recon_transactions (cycle_id, status);

-- ---------------------------------------------------------------------------
-- recon_invoices: one row per invoice (a PDF may contain several)
-- ---------------------------------------------------------------------------
create table if not exists recon_invoices (
  id                 uuid primary key default gen_random_uuid(),
  cycle_id           uuid not null references recon_cycles(id) on delete cascade,
  file_id            uuid not null references recon_files(id) on delete cascade,
  block_index        integer not null default 0,
  vendor_key         text,
  invoice_no         text,
  order_id           text,
  invoice_date       date,
  order_date         date,
  currency           text not null default 'INR',
  total_minor        bigint,
  amounts_minor      bigint[] not null default '{}',
  extra              jsonb not null default '{}'::jsonb,
  is_credit_note     boolean not null default false,
  source             text,
  extraction_status  text not null default 'pending',
  duplicate_of       uuid references recon_invoices(id) on delete set null,
  updated_at         timestamptz not null default now(),
  constraint recon_invoices_file_block_uq unique (file_id, block_index),
  constraint recon_invoices_source_check check (source in ('pdf_text', 'vision', 'manual')),
  constraint recon_invoices_extraction_status_check check (extraction_status in (
    'pending', 'ok', 'needs_check', 'failed'
  ))
);

create index if not exists recon_invoices_cycle_id_idx on recon_invoices (cycle_id);
create index if not exists recon_invoices_file_id_idx on recon_invoices (file_id);

-- ---------------------------------------------------------------------------
-- recon_amazon_rows: parsed Amazon Business reconciliation CSV rows
-- ---------------------------------------------------------------------------
create table if not exists recon_amazon_rows (
  id               uuid primary key default gen_random_uuid(),
  cycle_id         uuid not null references recon_cycles(id) on delete cascade,
  file_id          uuid references recon_files(id) on delete cascade,
  order_id         text,
  order_date       date,
  payment_ref      text,
  payment_date     date,
  payment_method   text,
  card_last4       text,
  shipment_qty     integer,
  net_total_paise  bigint
);

create index if not exists recon_amazon_rows_cycle_id_idx on recon_amazon_rows (cycle_id);
create index if not exists recon_amazon_rows_file_id_idx on recon_amazon_rows (file_id);

-- ---------------------------------------------------------------------------
-- recon_matches: transaction <-> invoice links (many-to-many)
-- created_by is NULL for system matches; manual decisions carry the user's email.
-- ---------------------------------------------------------------------------
create table if not exists recon_matches (
  id              uuid primary key default gen_random_uuid(),
  cycle_id        uuid not null references recon_cycles(id) on delete cascade,
  transaction_id  uuid not null references recon_transactions(id) on delete cascade,
  invoice_id      uuid not null references recon_invoices(id) on delete cascade,
  rule            text,
  is_suggestion   boolean not null default false,
  created_by      text,
  created_at      timestamptz not null default now(),
  constraint recon_matches_transaction_invoice_uq unique (transaction_id, invoice_id)
);

create index if not exists recon_matches_cycle_id_idx on recon_matches (cycle_id);
create index if not exists recon_matches_invoice_id_idx on recon_matches (invoice_id);

-- ---------------------------------------------------------------------------
-- recon_vendor_aliases: how a vendor appears on the statement AND on its invoices.
-- Patterns are regular expressions, applied case-insensitively by the engine.
-- ---------------------------------------------------------------------------
create table if not exists recon_vendor_aliases (
  id                uuid primary key default gen_random_uuid(),
  vendor_key        text not null unique,
  display_name      text not null,
  statement_pattern text,
  invoice_pattern   text,
  match_mode        text not null default 'single',
  date_before_days  integer not null default 7,
  date_after_days   integer not null default 7,
  active            boolean not null default true,
  constraint recon_vendor_aliases_match_mode_check check (match_mode in ('single', 'subset', 'none'))
);

-- ---------------------------------------------------------------------------
-- recon_events: audit log of manual actions
-- ---------------------------------------------------------------------------
create table if not exists recon_events (
  id          uuid primary key default gen_random_uuid(),
  cycle_id    uuid not null references recon_cycles(id) on delete cascade,
  actor       text,
  action      text not null,
  payload     jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

create index if not exists recon_events_cycle_id_idx on recon_events (cycle_id);

-- ---------------------------------------------------------------------------
-- updated_at triggers (tables that have an updated_at column)
-- ---------------------------------------------------------------------------
drop trigger if exists recon_cycles_set_updated_at on recon_cycles;
create trigger recon_cycles_set_updated_at
  before update on recon_cycles
  for each row execute function recon_set_updated_at();

drop trigger if exists recon_transactions_set_updated_at on recon_transactions;
create trigger recon_transactions_set_updated_at
  before update on recon_transactions
  for each row execute function recon_set_updated_at();

drop trigger if exists recon_invoices_set_updated_at on recon_invoices;
create trigger recon_invoices_set_updated_at
  before update on recon_invoices
  for each row execute function recon_set_updated_at();

-- ---------------------------------------------------------------------------
-- Row-level security: enabled, NO policies (service role only)
-- ---------------------------------------------------------------------------
alter table recon_cycles          enable row level security;
alter table recon_files           enable row level security;
alter table recon_transactions    enable row level security;
alter table recon_invoices        enable row level security;
alter table recon_amazon_rows     enable row level security;
alter table recon_matches         enable row level security;
alter table recon_vendor_aliases  enable row level security;
alter table recon_events          enable row level security;

-- ---------------------------------------------------------------------------
-- VERIFICATION (run after the migration)
-- ---------------------------------------------------------------------------
-- 1) Exactly these 8 tables:
--      select table_name from information_schema.tables
--       where table_schema = 'public' and table_name like 'recon_%' order by 1;
--    expect: recon_amazon_rows, recon_cycles, recon_events, recon_files, recon_invoices,
--            recon_matches, recon_transactions, recon_vendor_aliases
-- 2) RLS on for all 8 (and no policies):
--      select relname, relrowsecurity from pg_class
--       where relname like 'recon_%' and relkind = 'r' order by 1;
--      select count(*) from pg_policies where tablename like 'recon_%';   -- expect 0
-- 3) Trigger function and triggers:
--      select proname from pg_proc where proname = 'recon_set_updated_at';  -- 1 row
--      select tgname from pg_trigger where tgname like 'recon_%_set_updated_at' order by 1; -- 3 rows

-- ---------------------------------------------------------------------------
-- ROLLBACK (only if asked; deletes all Reconcile data). recon_* objects only.
-- ---------------------------------------------------------------------------
-- drop table if exists recon_events cascade;
-- drop table if exists recon_matches cascade;
-- drop table if exists recon_amazon_rows cascade;
-- drop table if exists recon_invoices cascade;
-- drop table if exists recon_transactions cascade;
-- drop table if exists recon_files cascade;
-- drop table if exists recon_vendor_aliases cascade;
-- drop table if exists recon_cycles cascade;
-- drop function if exists recon_set_updated_at();
