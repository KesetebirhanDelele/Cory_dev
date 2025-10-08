-- db/migrations/002_rls_roles.sql
-- Ticket B1.2 — RLS & Roles
-- Baseline RLS: anon/auth have NO access; service_role allowed via policy helper.
-- Applies to all user-facing + automation tables (including new campaign automation + staging).
-- Safe to run multiple times.

begin;

-- Helper: identify service_role via JWT (works with PostgREST/Supabase)
create or replace function public.is_service_role()
returns boolean
language sql
stable
as $$
  select coalesce((current_setting('request.jwt.claims', true)::jsonb ->> 'role') = 'service_role', false);
$$;

comment on function public.is_service_role() is 'True when request JWT role is service_role (bypass policy via USING/CHECK).';

-- RLS target tables
-- NOTE: Views are not included (RLS applies on underlying tables).
do $$
declare
  t text;
  tables text[] := array[
    -- Core tenancy
    'dev_nexus.tenant',
    'dev_nexus.project',
    -- Contacts & campaigns
    'dev_nexus.contact',
    'dev_nexus.campaign',
    -- Enrollments & dependents
    'dev_nexus.enrollment',
    'dev_nexus.outcome',
    'dev_nexus.handoff',
    -- Providers / messages / events
    'dev_nexus.providers',
    'dev_nexus.message',
    'dev_nexus.event',
    -- Templates
    'dev_nexus.template',
    'dev_nexus.template_variant',
    -- NEW: Campaign automation + staging
    'dev_nexus.campaign_step',
    'dev_nexus.campaign_activity',
    'dev_nexus.campaign_call_policy',
    'dev_nexus.phone_call_logs_stg'
  ];
begin
  foreach t in array tables loop
    -- Enable & enforce RLS
    execute format('alter table %s enable row level security;', t);
    execute format('alter table %s force row level security;', t);

    -- Clean any previous baseline policies
    execute format('drop policy if exists svc_all on %s;', t);

    -- SERVICE ROLE: full access (applies to all commands)
    execute format($fmt$
      create policy svc_all on %s
      for all
      using (public.is_service_role())
      with check (public.is_service_role());
    $fmt$, t);
  end loop;
end$$;

-- Optional: ensure anon/auth have no legacy grants (idempotent hardening)
-- (You already grant SELECT to service_role only in bootstrap; this is just belt & suspenders.)
do $$
declare
  t text;
  tables text[] := array[
    'dev_nexus.tenant',
    'dev_nexus.project',
    'dev_nexus.contact',
    'dev_nexus.campaign',
    'dev_nexus.enrollment',
    'dev_nexus.outcome',
    'dev_nexus.handoff',
    'dev_nexus.providers',
    'dev_nexus.message',
    'dev_nexus.event',
    'dev_nexus.template',
    'dev_nexus.template_variant',
    'dev_nexus.campaign_step',
    'dev_nexus.campaign_activity',
    'dev_nexus.campaign_call_policy',
    'dev_nexus.phone_call_logs_stg'
  ];
begin
  foreach t in array tables loop
    -- These REVOKEs are safe if no grant exists.
    execute format('revoke all on %s from anon;', t);
    execute format('revoke all on %s from authenticated;', t);
  end loop;
end$$;

commit;

-- Usage notes:
-- • service_role requests (e.g., server-side/edge functions, n8n with service key)
--   will pass USING/CHECK via public.is_service_role().
-- • Add finer-grained policies for authenticated users in later tickets (e.g., tenant scoping).
