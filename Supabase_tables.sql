-- Schema
create schema if not exists dev_education;

-- Helpful extensions
create extension if not exists pgcrypto; -- gen_random_uuid()

-- Core tables
create table if not exists dev_education.organizations(
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists dev_education.contacts(
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references dev_education.organizations(id),
  full_name text,
  email text,
  phone text,
  created_at timestamptz not null default now()
);

create table if not exists dev_education.campaigns(
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references dev_education.organizations(id),
  name text not null,
  description text,
  overall_goal_prompt text,
  created_at timestamptz not null default now()
);

create table if not exists dev_education.campaign_steps(
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references dev_education.campaigns(id),
  order_id int not null,
  channel text not null check (channel in ('voice','sms','email')),
  wait_before_ms bigint not null default 0,
  label text,
  metadata jsonb default '{}'::jsonb
);
create index if not exists ix_steps_campaign_order on dev_education.campaign_steps(campaign_id, order_id);

create table if not exists dev_education.campaign_enrollments(
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references dev_education.organizations(id),
  contact_id uuid not null references dev_education.contacts(id),
  campaign_id uuid not null references dev_education.campaigns(id),
  current_step_id uuid references dev_education.campaign_steps(id),
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
create index if not exists ix_enroll_next on dev_education.campaign_enrollments(next_channel, next_run_at) where status='active';
create index if not exists ix_enroll_contact_active on dev_education.campaign_enrollments(org_id, contact_id) where status='active';

create table if not exists dev_education.campaign_activities(
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references dev_education.organizations(id),
  enrollment_id uuid not null references dev_education.campaign_enrollments(id),
  campaign_id uuid not null references dev_education.campaigns(id),
  step_id uuid references dev_education.campaign_steps(id),
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
create index if not exists ix_activities_sms_due on dev_education.campaign_activities(channel, status, scheduled_at);

-- Staging + decisions
create table if not exists dev_education.phone_call_logs_stg(
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
create index if not exists ix_phone_stg_unprocessed on dev_education.phone_call_logs_stg(processed, id);

-- Global defaults (uses 'ANY' sentinel)
create table if not exists dev_education.phone_log_decisions(
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

-- Per-campaign policy override
create table if not exists dev_education.campaign_call_policies(
  campaign_id uuid not null references dev_education.campaigns(id),
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
create index if not exists ix_campaign_policy_lookup on dev_education.campaign_call_policies(campaign_id, status, end_call_reason);

-- Prompts
create table if not exists dev_education.prompt_templates(
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references dev_education.organizations(id),
  name text not null,
  channel text not null check (channel in ('voice','sms','email')),
  purpose text,
  template_text text not null,
  created_at timestamptz not null default now()
);

-- Views
create or replace view dev_education.v_due_sms_followups as
select a.id as activity_id, a.org_id, a.enrollment_id, a.campaign_id, a.step_id,
       a.channel, a.status, a.scheduled_at, e.contact_id
from dev_education.campaign_activities a
join dev_education.campaign_enrollments e on e.id = a.enrollment_id
where a.channel='sms' and a.status='planned'
  and a.scheduled_at is not null and a.scheduled_at <= now();

create or replace view dev_education.v_due_actions as
select e.id as enrollment_id, e.org_id, e.contact_id, e.campaign_id,
       e.current_step_id, e.next_channel, e.next_run_at
from dev_education.campaign_enrollments e
where e.status='active' and e.next_run_at is not null and e.next_run_at <= now();

create or replace view dev_education.v_due_waits as
select e.*, c.name as campaign_name
from dev_education.campaign_enrollments e
join dev_education.campaigns c on c.id = e.campaign_id
where e.status='active' and e.next_run_at is not null;
