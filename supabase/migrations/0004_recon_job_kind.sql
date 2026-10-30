-- 0004_recon_job_kind.sql
-- Reconcile: says which background job the job columns of recon_cycles belong to.
--
-- Statement reading, invoice reading and matching share job_status / job_progress / job_message on
-- recon_cycles. Until now the screens told the matching run from the others by its message starting with
-- "Matching". job_kind replaces that: the backend writes it together with the other three job columns.
--
-- Touches ONLY the recon_cycles table (one new nullable column and its check). Nothing else in the shared
-- project is read or changed. Idempotent: safe to run more than once.
--
-- Run order: 0001, 0002, 0003, 0004.
-- IMPORTANT: run this BEFORE you rebuild or deploy the API with the matching code (the new API writes
-- job_kind on every job update and would fail on a database without the column).

alter table recon_cycles add column if not exists job_kind text;

alter table recon_cycles drop constraint if exists recon_cycles_job_kind_check;
alter table recon_cycles
  add constraint recon_cycles_job_kind_check check (job_kind in ('statement', 'invoices', 'matching'));

-- Rows written before this column existed: recognise a matching run once, by its message (the last time the
-- message is used for this). Other old job rows stay null, which the API treats as "not a matching run".
update recon_cycles
   set job_kind = 'matching'
 where job_kind is null
   and job_status is not null
   and job_message like 'Matching%';

-- ---------------------------------------------------------------------------
-- VERIFICATION
-- ---------------------------------------------------------------------------
--   select column_name, data_type, is_nullable
--     from information_schema.columns
--    where table_schema = 'public' and table_name = 'recon_cycles' and column_name = 'job_kind';
--   expect: one row: job_kind | text | YES
--
--   select conname from pg_constraint where conname = 'recon_cycles_job_kind_check';
--   expect: one row
--
--   select job_kind, job_status, count(*) from recon_cycles group by 1, 2 order by 1, 2;
--   expect: no error; job_kind is null, statement, invoices or matching only
--
--   Run the file a second time: it must finish without an error and change nothing.

-- ---------------------------------------------------------------------------
-- ROLLBACK (only if asked, and only after the API is back on code that does not write job_kind)
-- ---------------------------------------------------------------------------
--   alter table recon_cycles drop constraint if exists recon_cycles_job_kind_check;
--   alter table recon_cycles drop column if exists job_kind;
