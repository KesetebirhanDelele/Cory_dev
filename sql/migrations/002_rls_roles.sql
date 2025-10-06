-- db/migrations/002_rls_roles.sql
-- Ticket B1.2 — RLS & Roles
-- Baseline RLS: anon/auth have NO access; service_role bypasses via policy helper.
-- This is intentionally least-privileged for user-facing tables.
-- Safe to run multiple times.

begin;

-- Helper: identify service_role via JWT (works with PostgREST/Supabase)
create or replace function public.is_service_role()
returns boolean
language sql
stable
as $$
  select coalesce( (current_setting('request.jwt.claims', true)::jsonb ->> 'role') = 'service_role', false );
$$;

comment on function public.is_service_role() is 'True when request JWT role is service_role (bypass policy).';

-- Target “user-facing” tables from B1.1
-- You can add/remove tables here as your surface grows.
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
    'dev_nexus.template_variant'
  ];
begin
  foreach t in array tables loop
    -- Enable RLS
    execute format('alter table %s enable row level security;', t);

    -- Remove any previously defined baseline policy with the same name (idempotent)
    execute format('drop policy if exists svc_all on %s;', t);

    -- SERVICE ROLE: full access (USING & CHECK)
    execute format($fmt$
      create policy svc_all on %s
      for all
      using (public.is_service_role())
      with check (public.is_service_role());
    $fmt$, t);

    -- NOTE:
    -- No anon/authenticated policies are created here (least privilege).
    -- Add additional role-specific policies in later tickets as needed.
  end loop;
end$$;

commit;
