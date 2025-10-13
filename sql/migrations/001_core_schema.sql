-- db/bootstrap.sql
-- Combined, idempotent bootstrap for Ticket B1.1 — Core Schema, Indexes, Campaign Automation, RPCs & Views
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

-- Ensure idempotent enrollments per (project,campaign,contact)
create unique index if not exists ux_enrollment_triplet
  on dev_nexus.enrollment(project_id, campaign_id, contact_id);

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

-- ====================================================
-- ===== Campaign Automation & Call Log Staging  ======
-- ====================================================

-- Campaign Steps (definition of the playbook)
create table if not exists dev_nexus.campaign_step (
  id                   uuid primary key default gen_random_uuid(),
  campaign_id          uuid not null references dev_nexus.campaign(id) on delete cascade,
  step_order           int  not null,
  name                 text not null,
  channel              text not null check (channel in ('voice','sms','email','webhook')),
  action               text not null,                                  -- 'call','send_sms','send_email','post_webhook'
  delay_minutes        int  not null default 0,                        -- wait from prior step
  template_id          uuid references dev_nexus.template(id) on delete set null,
  template_variant_id  uuid references dev_nexus.template_variant(id) on delete set null,
  retry_limit          int  not null default 0,
  metadata             jsonb not null default '{}'::jsonb,
  created_at           timestamptz not null default now(),
  unique (campaign_id, step_order)
);
create index if not exists ix_campaign_step_campaign on dev_nexus.campaign_step(campaign_id);

-- Per-campaign call throttles / business rules
create table if not exists dev_nexus.campaign_call_policy (
  id                           uuid primary key default gen_random_uuid(),
  campaign_id                  uuid not null references dev_nexus.campaign(id) on delete cascade,
  max_attempts                 int not null default 3,
  min_minutes_between_attempts int not null default 60,
  allow_voicemail              boolean not null default true,
  quiet_hours                  jsonb not null default '{"start":"21:00","end":"08:00","tz":"America/New_York"}',
  business_days                jsonb not null default '[1,2,3,4,5]'::jsonb, -- ISO weekday ints
  created_at                   timestamptz not null default now(),
  unique (campaign_id)
);

-- Activities (scheduled and executed actions per enrollment)
create table if not exists dev_nexus.campaign_activity (
  id               uuid primary key default gen_random_uuid(),
  enrollment_id    uuid not null references dev_nexus.enrollment(id) on delete cascade,
  campaign_id      uuid not null references dev_nexus.campaign(id) on delete cascade,
  contact_id       uuid not null references dev_nexus.contact(id) on delete cascade,
  step_id          uuid references dev_nexus.campaign_step(id) on delete set null,
  channel          text not null check (channel in ('voice','sms','email','webhook')),
  status           text not null default 'pending' check (status in ('pending','in_progress','completed','failed','cancelled','skipped')),
  attempt_no       int not null default 0,
  due_at           timestamptz not null default now(),
  started_at       timestamptz,
  completed_at     timestamptz,
  result_summary   text,
  result_payload   jsonb not null default '{}'::jsonb,
  error_message    text,
  created_at       timestamptz not null default now()
);

-- migrations/2025_10_12_add_variant_id_to_activities.sql
alter table dev_nexus.campaign_activity
    add column if not exists variant_id uuid null;
create index if not exists ix_campaign_activity_variant_id
    on dev_nexus.campaign_activity (variant_id);

create index if not exists ix_activity_due        on dev_nexus.campaign_activity(status, due_at);
create index if not exists ix_activity_enrollment on dev_nexus.campaign_activity(enrollment_id, due_at);
create index if not exists ix_activity_campaign   on dev_nexus.campaign_activity(campaign_id, status, due_at);
create index if not exists ix_activity_contact    on dev_nexus.campaign_activity(contact_id, status);

-- Staging for raw phone call logs (webhook drops)
create table if not exists dev_nexus.phone_call_logs_stg (
  id               uuid primary key default gen_random_uuid(),
  project_id       uuid references dev_nexus.project(id) on delete set null,
  provider_id      uuid references dev_nexus.providers(id) on delete set null,
  provider_ref     text,
  direction        dev_nexus.message_direction not null,
  status           text,                                         -- 'completed','failed','no_answer'
  from_number      text,
  to_number        text,
  duration_seconds int,
  recording_url    text,
  transcript       text,
  occurred_at      timestamptz,
  raw_payload      jsonb not null default '{}'::jsonb,
  processed_at     timestamptz,
  created_at       timestamptz not null default now()
);
create index if not exists ix_phone_call_logs_stg_unprocessed on dev_nexus.phone_call_logs_stg(processed_at) where processed_at is null;
create index if not exists ix_phone_call_logs_stg_provider    on dev_nexus.phone_call_logs_stg(provider_id, provider_ref);

-- ====================================================
-- =================== Grants =========================
-- ====================================================
grant usage on schema dev_nexus to service_role, authenticated, anon;

grant select on all tables in schema dev_nexus to service_role;
grant usage, select on all sequences in schema dev_nexus to service_role;

alter default privileges in schema dev_nexus grant select on tables to service_role;
alter default privileges in schema dev_nexus grant usage, select on sequences to service_role;

-- ====================================================
-- ====== RPCs used by tests (introspection) ==========
-- ====================================================
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

-- ====================================================
-- =============== App RPCs ===========================
-- ====================================================

-- Enroll a contact and seed first activity
drop function if exists dev_nexus.usp_enrollcontactintocampaign(uuid, uuid, uuid);
create or replace function dev_nexus.usp_enrollcontactintocampaign(
  p_project_id uuid,
  p_contact_id uuid,
  p_campaign_id uuid
)
returns uuid
language plpgsql
security definer
set search_path = dev_nexus, public, pg_catalog
as $$
declare
  v_enrollment_id uuid;
  v_first_step dev_nexus.campaign_step;
  v_due_at timestamptz;
begin
  -- idempotent via unique index ux_enrollment_triplet
  insert into dev_nexus.enrollment(project_id, campaign_id, contact_id, status)
  values (p_project_id, p_campaign_id, p_contact_id, 'active')
  on conflict (project_id, campaign_id, contact_id) do update
    set status = excluded.status;

  select id into v_enrollment_id
  from dev_nexus.enrollment
  where project_id = p_project_id and campaign_id = p_campaign_id and contact_id = p_contact_id
  limit 1;

  -- seed first step activity if none exists
  if not exists (
    select 1 from dev_nexus.campaign_activity a
    where a.enrollment_id = v_enrollment_id
  ) then
    select * into v_first_step
    from dev_nexus.campaign_step
    where campaign_id = p_campaign_id
    order by step_order asc
    limit 1;

    if found then
      -- schedule immediately if delay <= 0, else honor delay
      if coalesce(v_first_step.delay_minutes, 0) <= 0 then
        v_due_at := now();
      else
        v_due_at := now() + make_interval(mins => v_first_step.delay_minutes);
      end if;

      insert into dev_nexus.campaign_activity (
        enrollment_id, campaign_id, contact_id, step_id, channel, status, due_at
      ) values (
        v_enrollment_id, p_campaign_id, p_contact_id, v_first_step.id, v_first_step.channel, 'pending', v_due_at
      );
    end if;
  end if;

  return v_enrollment_id;
end$$;
grant execute on function dev_nexus.usp_enrollcontactintocampaign(uuid, uuid, uuid) to service_role, authenticated;

-- Log a voice call, complete current voice step, advance to next
drop function if exists dev_nexus.usp_logvoicecallandadvance(uuid, text, text, int, text, text);
create or replace function dev_nexus.usp_logvoicecallandadvance(
  p_enrollment_id uuid,
  p_provider_ref  text,
  p_status        text,              -- 'completed','failed','no_answer'
  p_duration_sec  int,
  p_recording_url text,
  p_transcript    text
)
returns void
language plpgsql
security definer
set search_path = dev_nexus, public, pg_catalog
as $$
declare
  v_proj uuid; v_cmp uuid; v_ctc uuid; v_provider uuid;
  v_curr_act dev_nexus.campaign_activity;
  v_next_step dev_nexus.campaign_step;
  v_next_due timestamptz;
begin
  select e.project_id, e.campaign_id, e.contact_id into v_proj, v_cmp, v_ctc
  from dev_nexus.enrollment e where e.id = p_enrollment_id;

  -- optional: resolve a known provider by name (can be null)
  select id into v_provider from dev_nexus.providers where name = 'synthflow';

  -- message + event (idempotent on (provider_ref, direction))
  insert into dev_nexus.message (project_id, provider_id, provider_ref, direction, payload)
  values (v_proj, v_provider, p_provider_ref, 'outbound', jsonb_build_object(
    'status', p_status,
    'duration_seconds', p_duration_sec,
    'recording_url', p_recording_url,
    'transcript', p_transcript
  ))
  on conflict (provider_ref, direction) do nothing;

  insert into dev_nexus.event (project_id, provider_id, provider_ref, direction, type, data)
  values (v_proj, v_provider, p_provider_ref, 'outbound', 'voice_call', jsonb_build_object(
    'status', p_status,
    'duration_seconds', p_duration_sec,
    'recording_url', p_recording_url
  ))
  on conflict (provider_ref, direction) do nothing;

  -- complete oldest pending/in-progress voice activity
  select * into v_curr_act
  from dev_nexus.campaign_activity
  where enrollment_id = p_enrollment_id
    and channel = 'voice'
    and status in ('pending','in_progress')
  order by due_at asc
  limit 1;

  if found then
    update dev_nexus.campaign_activity
      set status = case when p_status='completed' then 'completed' else 'failed' end,
          completed_at = now(),
          result_summary = p_status,
          result_payload = jsonb_build_object('duration_seconds', p_duration_sec, 'recording_url', p_recording_url)
    where id = v_curr_act.id;
  end if;

  -- schedule next step or close enrollment
  if v_curr_act.step_id is not null then
    select s2.* into v_next_step
    from dev_nexus.campaign_step s1
    join dev_nexus.campaign_step s2
      on s2.campaign_id = s1.campaign_id and s2.step_order = s1.step_order + 1
    where s1.id = v_curr_act.step_id
    limit 1;

    if found then
      -- schedule immediately if delay <= 0, else honor delay
      if coalesce(v_next_step.delay_minutes, 0) <= 0 then
        v_next_due := now();
      else
        v_next_due := now() + make_interval(mins => v_next_step.delay_minutes);
      end if;

      insert into dev_nexus.campaign_activity (
        enrollment_id, campaign_id, contact_id, step_id, channel, status, due_at
      ) values (
        p_enrollment_id, v_cmp, v_ctc, v_next_step.id, v_next_step.channel, 'pending', v_next_due
      );
    else
      update dev_nexus.enrollment set status = 'completed' where id = p_enrollment_id;
    end if;
  end if;
end$$;
grant execute on function dev_nexus.usp_logvoicecallandadvance(uuid, text, text, int, text, text) to service_role, authenticated;

-- Ingest staged phone call logs into normalized message/event rows
drop function if exists dev_nexus.usp_ingestphonecalllogs();
create or replace function dev_nexus.usp_ingestphonecalllogs()
returns int
language plpgsql
security definer
set search_path = dev_nexus, public, pg_catalog
as $$
declare
  v_count int := 0;
  r record;
begin
  for r in
    select *
    from dev_nexus.phone_call_logs_stg
    where processed_at is null
    order by created_at asc
  loop
    insert into dev_nexus.message (project_id, provider_id, provider_ref, direction, payload, created_at)
    values (r.project_id, r.provider_id, r.provider_ref, r.direction,
            coalesce(r.raw_payload,'{}'::jsonb) ||
            jsonb_build_object('status', r.status, 'duration_seconds', r.duration_seconds, 'recording_url', r.recording_url, 'transcript', r.transcript),
            coalesce(r.occurred_at, r.created_at))
    on conflict (provider_ref, direction) do nothing;

    insert into dev_nexus.event (project_id, provider_id, provider_ref, direction, type, data, created_at)
    values (r.project_id, r.provider_id, r.provider_ref, r.direction, 'voice_call',
            coalesce(r.raw_payload,'{}'::jsonb) ||
            jsonb_build_object('from_number', r.from_number, 'to_number', r.to_number, 'status', r.status),
            coalesce(r.occurred_at, r.created_at))
    on conflict (provider_ref, direction) do nothing;

    update dev_nexus.phone_call_logs_stg
      set processed_at = now()
      where id = r.id;

    v_count := v_count + 1;
  end loop;

  return v_count;
end$$;
grant execute on function dev_nexus.usp_ingestphonecalllogs() to service_role, authenticated;

-- ====================================================
-- =================== Views ==========================
-- ====================================================

-- Activities ready to run now (includes project_id for orchestrator filtering)
drop view if exists dev_nexus.v_due_sms_followups;
drop view if exists dev_nexus.v_due_actions;
create view dev_nexus.v_due_actions as
select
  a.id              as activity_id,
  a.enrollment_id,
  a.campaign_id,
  a.contact_id,
  a.step_id,
  a.channel,
  a.due_at,
  cmp.project_id,                      -- NEW: enable project-scoped queries
  c.full_name,
  c.email,
  c.phone,
  cmp.name          as campaign_name,
  s.step_order,
  s.name            as step_name,
  s.action          as step_action
from dev_nexus.campaign_activity a
join dev_nexus.contact  c   on c.id  = a.contact_id
join dev_nexus.campaign cmp on cmp.id = a.campaign_id
left join dev_nexus.campaign_step s on s.id = a.step_id
where a.status = 'pending'
  and a.due_at <= now()
order by a.due_at, a.id;

-- SMS-only subset
create view dev_nexus.v_due_sms_followups as
select *
from dev_nexus.v_due_actions
where channel = 'sms';

-- View grants
grant select on dev_nexus.v_due_actions, dev_nexus.v_due_sms_followups to service_role;

commit;

-- NOTE: Expose the schema to REST in the dashboard (one-time setting):
-- Studio → Project Settings → API → "Schemas exposed to the REST API" → add `dev_nexus`

-- ========== Mirror Views in Public Schema for Dashboard ==========
create or replace view public.v_due_actions as
select * from dev_nexus.v_due_actions;

create or replace view public.v_due_actions as
select * from dev_nexus.v_due_actions;

create or replace view public.phone_call_logs_stg as
select * from dev_nexus.phone_call_logs_stg;

create or replace view public.campaign_activity as
select
  a.id,
  e.project_id              as org_id,            -- was e.org_id (doesn't exist)
  a.enrollment_id,
  a.campaign_id,
  a.contact_id,
  a.step_id,
  a.channel,
  a.status,
  a.attempt_no,
  a.due_at                 as scheduled_at,       -- alias for your code
  a.started_at,
  a.completed_at,
  a.result_summary         as generated_message,  -- alias for your code
  a.result_payload,
  a.error_message,
  a.created_at,
  a.variant_id
from dev_nexus.campaign_activity a
join dev_nexus.enrollment e on e.id = a.enrollment_id;

create or replace view public.v_variant_attribution as
select * from dev_nexus.v_variant_attribution;