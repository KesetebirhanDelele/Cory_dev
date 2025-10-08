-- 0012_b2_1_telemetry_view.sql (revised for dev_nexus + RLS posture)
-- Purpose: unified, read-only timeline across message & event with an RPC to query.

begin;

-- 1) Enum for view type tag (optional but handy)
do $$ begin
  if not exists (
    select 1 from pg_type t
    join pg_namespace n on n.oid = t.typnamespace
    where n.nspname='public' and t.typname='telemetry_event_kind'
  ) then
    create type public.telemetry_event_kind as enum ('message','event');
  end if;
end $$;

-- 2) Unified read-only view (only columns that exist)
create or replace view dev_nexus.telemetry_view as
  select
    m.created_at                                   as occurred_at,
    m.id                                           as event_pk,
    'message'::public.telemetry_event_kind         as event_kind,
    m.project_id,
    m.provider_id,
    m.provider_ref,
    (m.direction)::text                            as direction,
    m.payload                                      as payload
  from dev_nexus.message m
union all
  select
    e.created_at                                   as occurred_at,
    e.id                                           as event_pk,
    'event'::public.telemetry_event_kind           as event_kind,
    e.project_id,
    e.provider_id,
    e.provider_ref,
    (e.direction)::text                            as direction,
    jsonb_build_object('type', e.type, 'data', e.data) as payload
  from dev_nexus.event e;

comment on view dev_nexus.telemetry_view
  is 'Unified append-only telemetry from message/event tables.';

-- 3) Hard block any DML on the view (append via base tables only)
create or replace function dev_nexus.telemetry_view_block_write()
returns trigger language plpgsql as $$
begin
  raise exception 'telemetry_view is append-only/read-only; % not allowed', tg_op
    using errcode = '25P02';
end $$;

drop trigger if exists telemetry_view_no_insert on dev_nexus.telemetry_view;
drop trigger if exists telemetry_view_no_update on dev_nexus.telemetry_view;
drop trigger if exists telemetry_view_no_delete on dev_nexus.telemetry_view;

create trigger telemetry_view_no_insert
  instead of insert on dev_nexus.telemetry_view
  for each row execute function dev_nexus.telemetry_view_block_write();

create trigger telemetry_view_no_update
  instead of update on dev_nexus.telemetry_view
  for each row execute function dev_nexus.telemetry_view_block_write();

create trigger telemetry_view_no_delete
  instead of delete on dev_nexus.telemetry_view
  for each row execute function dev_nexus.telemetry_view_block_write();

-- 4) Ordered timeline helper (time, then pk)
drop function if exists dev_nexus.telemetry_timeline(uuid, timestamptz, timestamptz, int);
create or replace function dev_nexus.telemetry_timeline(
  _project_id uuid,
  _since timestamptz default '-infinity',
  _until timestamptz default 'infinity',
  _limit int default 1000
)
returns table (
  occurred_at timestamptz,
  event_pk uuid,
  event_kind public.telemetry_event_kind,
  project_id uuid,
  provider_id uuid,
  provider_ref text,
  direction text,
  payload jsonb
)
language sql
stable
set search_path = dev_nexus, public, pg_catalog
as $$
  select *
  from dev_nexus.telemetry_view
  where project_id = _project_id
    and occurred_at >= _since
    and occurred_at <= _until
  order by occurred_at, event_pk
  limit _limit
$$;

-- 5) Grants aligned with RLS posture:
--    • Views don’t have RLS, so restrict via GRANTs.
--    • Only service_role should read this view / call the RPC by default.
revoke all on dev_nexus.telemetry_view from public, anon, authenticated;
grant select on dev_nexus.telemetry_view to service_role;

revoke all on function dev_nexus.telemetry_timeline(uuid, timestamptz, timestamptz, int)
  from public, anon, authenticated;
grant execute on function dev_nexus.telemetry_timeline(uuid, timestamptz, timestamptz, int)
  to service_role;

commit;
