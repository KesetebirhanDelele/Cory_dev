-- 🧠 Campaign definitions
create table if not exists public.campaigns (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  max_attempts int default 3,
  policy jsonb default '{}'::jsonb,
  created_at timestamp default now()
);

-- 📋 Steps for each campaign
create table if not exists public.campaign_steps (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid references public.campaigns(id) on delete cascade,
  step_index int not null,
  channel text check (channel in ('voice','sms','email','escalate')),
  prompt_template text,
  wait_seconds int default 30,
  allowed_hours int[] default '{9,17}', -- business hours
  created_at timestamp default now()
);

-- 👤 Leads to be contacted
create table if not exists public.leads (
  id uuid primary key default gen_random_uuid(),
  name text,
  phone text,
  email text,
  intent text default 'inquiry',
  created_at timestamp default now()
);

-- 📈 Enrollments (each lead in a campaign)
create table if not exists public.campaign_enrollments (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid references public.campaigns(id),
  lead_id uuid references public.leads(id),
  step_index int default 0,
  attempts int default 0,
  next_run_at timestamp default now(),
  status text default 'pending',
  created_at timestamp default now()
);

ALTER TABLE campaign_enrollments
ADD COLUMN last_contacted_at timestamp without time zone,
ADD COLUMN updated_at timestamp without time zone;

-- 💬 Interaction logs (each outreach attempt)
create table if not exists public.interactions (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid references public.leads(id),
  campaign_id uuid references public.campaigns(id),
  step_index int,
  channel text,
  content text,
  status text,
  provider_ref text,
  metadata jsonb default '{}'::jsonb,
  created_at timestamp default now()
);

alter table public.campaigns
add column if not exists max_attempts int default 3,
add column if not exists policy jsonb default '{}'::jsonb;



