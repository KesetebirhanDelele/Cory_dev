-- db/bootstrap.sql
-- Combined, idempotent bootstrap for Ticket B1.1 — Core Schema & Indexes
-- Creates schema, tables, FKs, unique indexes, grants, and RPCs.
-- Safe to run multiple times.

begin;

-- ========== Prereqs ==========
create schema if not exists dev_nexus;
create extension if not exists pgcrypto;

-- Enum used by message/event direction
do $$
begin
  if not exists (
    select 1
    from pg_type t
    join pg_namespace n on n.oid=t.typnamespace
    where n.nspname='dev_nexus' and t.typname='message_direction'
  ) then
    create type dev_nexus.message_direction as enum ('inbound','outbound');
  end if;
end$$;

-- ========== Core Tenancy ==========
create table if not exists dev_nexus.tenant (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  created_at  timestamptz not null default now()
);

create table if not exists dev_nexus.project (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references dev_nexus.tenant(id) on delete restrict,
  name        text not null,
  created_at  timestamptz not null default now()
);

-- ========== Contacts & Campaigns ==========
create table if not exists dev_nexus.contact (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references dev_nexus.project(id) on delete restrict,
  full_name   text,
  email       text,
  phone       text,
  created_at  timestamptz not null default now()
);

create table if not exists dev_nexus.campaign (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references dev_nexus.project(id) on delete restrict,
  name        text not null,
  created_at  timestamptz not null default now()
);

-- ========== Enrollments & Dependents ==========
create table if not exists dev_nexus.enrollment (
  id           uuid primary key default gen_random_uuid(),
  project_id   uuid not null references dev_nexus.project(id)   on delete restrict,
  campaign_id  uuid not null references dev_nexus.campaign(id)  on delete restrict,
  contact_id   uuid not null references dev_nexus.contact(id)   on delete restrict,
  status       text default 'active',
  created_at   timestamptz not null default now()
);

create table if not exists dev_nexus.outcome (
  id             uuid primary key default gen_random_uuid(),
  enrollment_id  uuid not null references dev_nexus.enrollment(id) on delete cascade,
  kind           text not null,
  notes          text,
  created_at     timestamptz not null default now()
);

create table if not exists dev_nexus.handoff (
  id             uuid primary key default gen_random_uuid(),
  enrollment_id  uuid not null references dev_nexus.enrollment(id) on delete cascade,
  to_owner       text,
  created_at     timestamptz not null default now()
);

-- ========== Providers / Messages / Events ==========
create table if not exists dev_nexus.providers (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique,
  created_at  timestamptz not null default now()
);

create table if not exists dev_nexus.message (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references dev_nexus.project(id) on delete restrict,
  provider_id   uuid references dev_nexus.providers(id) on delete restrict,
  provider_ref  text not null,
  direction     dev_nexus.message_direction not null,
  payload       jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);

create table if not exists dev_nexus.event (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references dev_nexus.project(id) on delete restrict,
  provider_id   uuid references dev_nexus.providers(id) on delete restrict,
  provider_ref  text not null,
  direction     dev_nexus.message_direction not null,
  type          text not null,
  data          jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);

-- Uniqueness required by tests: (provider_ref, direction) on message & event
create unique index if not exists ux_message_ref_dir on dev_nexus.message (provider_ref, direction);
create unique index if not exists ux_event_ref_dir   on dev_nexus.event   (provider_ref, direction);

-- Helpful indexes
create index if not exists ix_message_project_id          on dev_nexus.message (project_id);
create index if not exists ix_event_project_id            on dev_nexus.event (project_id);
create index if not exists ix_enrollment_fk_combo         on dev_nexus.enrollment (project_id, campaign_id, contact_id);
create index if not exists ix_message_provider_ref_dir    on dev_nexus.message (provider_ref, direction);
create index if not exists ix_event_provider_ref_dir      on dev_nexus.event (provider_ref, direction);

-- ========== Templates ==========
create table if not exists dev_nexus.template (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  description text,
  body        jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

create table if not exists dev_nexus.template_variant (
  id           uuid primary key default gen_random_uuid(),
  template_id  uuid not null,
  name         text not null,
  body         jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);
-- (FK to template is optional for B1.1; add later if needed)

-- ========== Grants & Default Privileges ==========
grant usage on schema dev_nexus to service_role, authenticated, anon;

grant select on all tables in schema dev_nexus to service_role;
grant usage, select on all sequences in schema dev_nexus to service_role;

alter default privileges in schema dev_nexus grant select on tables to service_role;
alter default privileges in schema dev_nexus grant usage, select on sequences to service_role;

-- ========== RPCs used by tests (drop conflicting versions, then recreate) ==========
drop function if exists public.inspect_tables(text);
drop function if exists public.inspect_foreign_keys(text);
drop function if exists public.inspect_indexes(text, text[]);

-- inspect_tables(p_schema text) -> table(table_name text)
create or replace function public.inspect_tables(p_schema text)
returns table(table_name text)
language sql
stable
security definer
set search_path = public, pg_catalog
as $$
  select t.table_name
  from information_schema.tables t
  where t.table_schema = p_schema
  order by t.table_name;
$$;
grant execute on function public.inspect_tables(text) to service_role, authenticated, anon;

-- inspect_foreign_keys(p_schema text)
-- -> table(child_table text, child_column text, parent_table text)
create or replace function public.inspect_foreign_keys(p_schema text)
returns table(
  child_table  text,
  child_column text,
  parent_table text
)
language sql
stable
security definer
set search_path = public, pg_catalog
as $$
  select
    tc.table_name   as child_table,
    kcu.column_name as child_column,
    ccu.table_name  as parent_table
  from information_schema.table_constraints tc
  join information_schema.key_column_usage kcu
    on tc.constraint_name = kcu.constraint_name
   and tc.constraint_schema = kcu.constraint_schema
  join information_schema.constraint_column_usage ccu
    on ccu.constraint_name = tc.constraint_name
   and ccu.constraint_schema = tc.constraint_schema
  where tc.constraint_type = 'FOREIGN KEY'
    and tc.constraint_schema = p_schema
  order by tc.table_name, tc.constraint_name, kcu.ordinal_position;
$$;
grant execute on function public.inspect_foreign_keys(text) to service_role, authenticated, anon;

-- inspect_indexes(p_schema text, p_tables text[])
-- -> table(table_name text, index_name text, is_unique boolean, index_def text)
create or replace function public.inspect_indexes(p_schema text, p_tables text[])
returns table(
  table_name text,
  index_name text,
  is_unique  boolean,
  index_def  text
)
language sql
stable
security definer
set search_path = public, pg_catalog
as $$
  select
    t.relname::text                as table_name,
    i.relname::text                as index_name,
    ix.indisunique                 as is_unique,
    pg_get_indexdef(ix.indexrelid) as index_def
  from pg_index ix
  join pg_class i on i.oid = ix.indexrelid
  join pg_class t on t.oid = ix.indrelid
  join pg_namespace n on n.oid = t.relnamespace
  where n.nspname = p_schema
    and (p_tables is null or t.relname = any(p_tables))
  order by t.relname, i.relname;
$$;
grant execute on function public.inspect_indexes(text, text[]) to service_role, authenticated, anon;

commit;

-- NOTE: Expose the schema to REST in the dashboard (one-time setting):
-- Studio → Project Settings → API → "Schemas exposed to the REST API" → add `dev_nexus`
