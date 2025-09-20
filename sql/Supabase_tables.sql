-- =========================================================
-- dev_nexus bootstrap for Cory_dev (idempotent)
-- Run in Supabase SQL Editor (correct project)
-- =========================================================

-- 0) Schema + extension
create schema if not exists dev_nexus;
create extension if not exists pgcrypto; -- for gen_random_uuid()
set search_path to dev_nexus, public;

-- 1) Core tables
create table if not exists dev_nexus.organizations(
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists dev_nexus.contacts(
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references dev_nexus.organizations(id),
  first_name text,
  last_name  text,
  full_name  text,
  email      text,
  phone      text,
  created_at timestamptz not null default now()
);

create table if not exists dev_nexus.campaigns(
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references dev_nexus.organizations(id),
  name text not null,
  description text,
  overall_goal_prompt text,
  goal_prompt         text,
  campaign_type       text,
  created_at timestamptz not null default now()
);

-- NEW: add updated_at to campaigns (idempotent)
do $$
begin
  if not exists (
    select 1 from information_schema.columns
    where table_schema='dev_nexus' and table_name='campaigns' and column_name='updated_at'
  ) then
    alter table dev_nexus.campaigns add column updated_at timestamptz not null default now();
  end if;
end$$;

-- Optional check constraint on campaign_type
do $$
begin
  if not exists (select 1 from pg_constraint where conname='ck_campaigns_campaign_type') then
    alter table dev_nexus.campaigns
      add constraint ck_campaigns_campaign_type
      check (campaign_type in ('live','draft') or campaign_type is null);
  end if;
end$$;

create table if not exists dev_nexus.campaign_steps(
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references dev_nexus.campaigns(id),
  order_id int not null,
  channel text not null check (channel in ('voice','sms','email')),
  wait_before_ms bigint not null default 0,
  label text,
  metadata jsonb default '{}'::jsonb
);
create index if not exists ix_steps_campaign_order on dev_nexus.campaign_steps(campaign_id, order_id);

-- NEW: add goal_prompt to campaign_steps to match builder code
do $$
begin
  if not exists (
    select 1 from information_schema.columns
    where table_schema='dev_nexus' and table_name='campaign_steps' and column_name='goal_prompt'
  ) then
    alter table dev_nexus.campaign_steps add column goal_prompt text;
  end if;
end$$;

-- NEW: add created_at/updated_at to campaign_steps so trigger can auto-touch
do $$
begin
  if not exists (
    select 1 from information_schema.columns
    where table_schema='dev_nexus' and table_name='campaign_steps' and column_name='created_at'
  ) then
    alter table dev_nexus.campaign_steps add column created_at timestamptz not null default now();
  end if;
  if not exists (
    select 1 from information_schema.columns
    where table_schema='dev_nexus' and table_name='campaign_steps' and column_name='updated_at'
  ) then
    alter table dev_nexus.campaign_steps add column updated_at timestamptz not null default now();
  end if;
end$$;

-- (optional) keep steps in order unique per campaign
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname='ux_campaign_steps_unique_order'
  ) then
    alter table dev_nexus.campaign_steps
      add constraint ux_campaign_steps_unique_order unique (campaign_id, order_id);
  end if;
end$$;

create table if not exists dev_nexus.campaign_enrollments(
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references dev_nexus.organizations(id),
  contact_id uuid not null references dev_nexus.contacts(id),
  campaign_id uuid not null references dev_nexus.campaigns(id),
  current_step_id uuid references dev_nexus.campaign_steps(id),
  next_channel text check (next_channel in ('voice','sms','email')),
  next_run_at timestamptz,
  status text not null default 'active' check (status in ('active','paused','completed','switched','cancelled')),
  reason text,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  switched_to_enrollment uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists ix_enroll_next on dev_nexus.campaign_enrollments(next_channel, next_run_at) where status='active';
create index if not exists ix_enroll_contact_active on dev_nexus.campaign_enrollments(org_id, contact_id) where status='active';

create table if not exists dev_nexus.campaign_activities(
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references dev_nexus.organizations(id),
  enrollment_id uuid not null references dev_nexus.campaign_enrollments(id),
  campaign_id uuid not null references dev_nexus.campaigns(id),
  step_id uuid references dev_nexus.campaign_steps(id),
  attempt_no int,
  channel text not null check (channel in ('voice','sms','email')),
  status text not null check (status in ('planned','completed','failed')),
  scheduled_at timestamptz,
  sent_at timestamptz,
  delivered_at timestamptz,
  completed_at timestamptz,
  outcome text,
  provider_ref text,
  prompt_used text,
  generated_message text,
  ai_analysis text,
  -- voice-only fields
  provider_call_id text,
  provider_module_id text,
  call_duration_sec int,
  end_call_reason text,
  executed_actions_json jsonb,
  prompt_variables_json jsonb,
  recording_url text,
  transcript text,
  call_started_at timestamptz,
  agent_name text,
  call_timezone text,
  phone_number_to text,
  phone_number_from text,
  call_status text,
  campaign_type text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists ix_activities_sms_due on dev_nexus.campaign_activities(channel, status, scheduled_at);

-- 2) Staging & policy tables
create table if not exists dev_nexus.phone_call_logs_stg(
  id bigserial primary key,
  enrollment_id uuid,
  contact_id uuid,
  campaign_id uuid,
  type_of_call text,
  call_id text,
  module_id text,
  duration_seconds int,
  end_call_reason text,
  executed_actions jsonb,
  prompt_variables jsonb,
  recording_url text,
  transcript text,
  start_time_epoch_ms bigint,
  start_time timestamptz,
  agent text,
  timezone text,
  phone_number_to text,
  phone_number_from text,
  status text,
  campaign_type text,
  classification text,
  appointment_time timestamptz,
  processed boolean not null default false,
  processed_at timestamptz,
  error_msg text
);
create index if not exists ix_phone_stg_unprocessed on dev_nexus.phone_call_logs_stg(processed, id);

create unique index if not exists ux_activities_provider_call_id
on dev_nexus.campaign_activities(provider_call_id)
where provider_call_id is not null;

create table if not exists dev_nexus.phone_log_decisions(
  status text not null,
  end_call_reason text not null,
  is_connected boolean not null,
  should_retry boolean not null,
  retry_sms boolean not null,
  first_retry_mins int,
  next_retry_mins int,
  max_retry_days int,
  align_same_time boolean,
  primary key(status, end_call_reason)
);

create table if not exists dev_nexus.campaign_call_policies(
  campaign_id uuid not null references dev_nexus.campaigns(id),
  status text not null,
  end_call_reason text not null,
  is_connected boolean not null,
  should_retry boolean not null,
  retry_sms boolean not null,
  first_retry_mins int not null,
  next_retry_mins int not null,
  max_retry_days int not null,
  align_same_time boolean not null,
  primary key(campaign_id, status, end_call_reason)
);
create index if not exists ix_campaign_policy_lookup on dev_nexus.campaign_call_policies(campaign_id, status, end_call_reason);

create table if not exists dev_nexus.prompt_templates(
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references dev_nexus.organizations(id),
  name text not null,
  channel text not null check (channel in ('voice','sms','email')),
  purpose text,
  template_text text not null,
  created_at timestamptz not null default now()
);

-- 3) Views used by your jobs
create or replace view dev_nexus.v_due_sms_followups as
select
  a.id               as activity_id,
  a.org_id,
  a.enrollment_id,
  a.campaign_id,
  a.step_id,
  a.channel,
  a.status,
  a.scheduled_at,
  a.generated_message,
  e.contact_id
from dev_nexus.campaign_activities a
join dev_nexus.campaign_enrollments e on e.id = a.enrollment_id
where a.channel='sms' and a.status='planned'
  and a.scheduled_at is not null and a.scheduled_at <= now();

create or replace view dev_nexus.v_due_actions as
select e.id as enrollment_id, e.org_id, e.contact_id, e.campaign_id,
       e.current_step_id, e.next_channel, e.next_run_at
from dev_nexus.campaign_enrollments e
where e.status='active' and e.next_run_at is not null and e.next_run_at <= now();

create or replace view dev_nexus.v_due_waits as
select e.*, c.name as campaign_name
from dev_nexus.campaign_enrollments e
join dev_nexus.campaigns c on c.id = e.campaign_id
where e.status='active' and e.next_run_at is not null;

-- 4) Backfills / sensible defaults
update dev_nexus.campaigns set campaign_type = coalesce(campaign_type, 'live');

-- If you previously used overall_goal_prompt, copy into goal_prompt when empty
update dev_nexus.campaigns
   set goal_prompt = coalesce(goal_prompt, overall_goal_prompt)
 where goal_prompt is null;

-- Seed a demo org if none exists (tests expect at least one)
insert into dev_nexus.organizations (name)
select 'Demo Org' where not exists (select 1 from dev_nexus.organizations);

-- Seed default phone decision rules (safe upserts)
insert into dev_nexus.phone_log_decisions
(status, end_call_reason, is_connected, should_retry, retry_sms, first_retry_mins, next_retry_mins, max_retry_days, align_same_time)
values
('failed','no_answer', false, true,  false, 10, 30, 2, true),
('failed','busy',      false, true,  false, 10, 30, 2, true),
('failed','failed',    false, true,  false, 15, 60, 2, true),
('completed','completed', true, false, false, 0, 0, 0, false)
on conflict (status, end_call_reason) do nothing;

-- 5) Auto-touch updated_at on BASE TABLES only (skip views)
create or replace function dev_nexus.touch_updated_at()
returns trigger language plpgsql as $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = TG_TABLE_SCHEMA
      and table_name   = TG_TABLE_NAME
      and column_name  = 'updated_at'
  ) then
    new.updated_at := now();
  end if;
  return new;
end$$;

do $$
declare r record;
begin
  for r in
    select t.table_schema, t.table_name
    from information_schema.tables t
    where t.table_schema = 'dev_nexus'
      and t.table_type   = 'BASE TABLE'
      and exists (
        select 1 from information_schema.columns c
        where c.table_schema = t.table_schema
          and c.table_name   = t.table_name
          and c.column_name  = 'updated_at'
      )
  loop
    execute format($f$
      do $g$
      begin
        if not exists (select 1 from pg_trigger where tgname=%L) then
          create trigger %I before update on %I.%I
          for each row execute function dev_nexus.touch_updated_at();
        end if;
      end$g$;
    $f$, 'trg_touch_'||r.table_name, 'trg_touch_'||r.table_name, r.table_schema, r.table_name);
  end loop;
end$$;

-- 6) Privileges for server-side REST (service_role)
grant usage on schema dev_nexus to service_role;
grant select, insert, update, delete on all tables in schema dev_nexus to service_role;
grant usage, select on all sequences in schema dev_nexus to service_role;
grant execute on all functions in schema dev_nexus to service_role;

alter default privileges in schema dev_nexus
  grant select, insert, update, delete on tables to service_role;

alter default privileges in schema dev_nexus
  grant usage, select on sequences to service_role;

-- 7) Ask PostgREST to reload schema cache (also click "Refresh schema cache" in Data API settings)
select pg_notify('pgrst', 'reload schema');

-- View of planned email activities that are due now
create or replace view dev_nexus.v_due_email_followups as
select
  a.id              as activity_id,
  a.org_id,
  a.enrollment_id,
  a.campaign_id,
  a.step_id,
  a.channel,
  a.status,
  a.scheduled_at,
  a.generated_message,
  e.contact_id,
  c.email           as contact_email,
  c.first_name,
  c.last_name
from dev_nexus.campaign_activities a
join dev_nexus.campaign_enrollments e on e.id = a.enrollment_id
join dev_nexus.contacts c            on c.id = e.contact_id
where a.channel = 'email'
  and a.status  = 'planned'
  and a.scheduled_at is not null
  and a.scheduled_at <= now()
  and coalesce(c.email, '') <> '';

-- (optional) easy button: let service_role SELECT it explicitly
grant select on dev_nexus.v_due_email_followups to service_role;

-- Ask PostgREST to refresh its cache so REST sees the new view
select pg_notify('pgrst', 'reload schema');

INSERT INTO dev_nexus.organizations (id, name, created_at)
VALUES ('14dfa4be-8508-4fc4-8392-dea0c6d0a041', 'Test Org', NOW())
ON CONFLICT (id) DO NOTHING;