-- 0013_b2_2_state_snapshot.sql
-- Ticket B2.2 — State Snapshot (Materialized)
-- Snapshot per ENROLLMENT using latest campaign_activity row.

begin;

-- 1) Materialized view (one row per enrollment)
drop materialized view if exists dev_nexus.enrollment_state_snapshot;

create materialized view dev_nexus.enrollment_state_snapshot as
with latest_activity as (
  select distinct on (a.enrollment_id)
         a.enrollment_id,
         a.campaign_id,
         a.contact_id,
         a.channel,
         a.status,
         a.result_summary,
         a.result_payload,
         coalesce(a.completed_at, a.started_at, a.due_at, a.created_at) as activity_ts
  from dev_nexus.campaign_activity a
  order by a.enrollment_id,
           coalesce(a.completed_at, a.started_at, a.due_at, a.created_at) desc,
           a.id desc
)
select
  e.id            as enrollment_id,
  e.project_id    as project_id,
  la.campaign_id  as campaign_id,
  la.contact_id   as contact_id,
  la.channel      as channel,
  -- Deterministic mapping:
  case
    -- explicit policy/timeout flags in result_payload
    when coalesce( (la.result_payload->>'policy_denied')::boolean, false ) then 'policy_denied'
    when coalesce( (la.result_payload->>'timeout')::boolean, false ) then 'timeout'

    -- voice 'no_answer' surfaced in result_summary by usp_logvoicecallandadvance() -> treat as timeout
    when la.result_summary = 'no_answer' then 'timeout'

    -- core campaign_activity statuses
    when la.status = 'failed'        then 'failed'
    when la.status = 'completed'     then 'delivered'
    when la.status = 'in_progress'   then 'sent'
    when la.status = 'pending'       then 'queued'

    -- cancelled/skipped or anything else => queued (safe default)
    else 'queued'
  end as delivery_state,
  la.activity_ts  as last_event_at
from latest_activity la
join dev_nexus.enrollment e on e.id = la.enrollment_id;

-- 2) Unique index required for CONCURRENT refresh
create unique index if not exists uq_enrollment_state_snapshot
  on dev_nexus.enrollment_state_snapshot (enrollment_id);

-- Helpful lookups
create index if not exists ix_snapshot_campaign on dev_nexus.enrollment_state_snapshot (campaign_id);
create index if not exists ix_snapshot_last_event on dev_nexus.enrollment_state_snapshot (last_event_at desc);

-- 3) RPC to refresh snapshot (call from server/n8n after events)
drop function if exists public.rpc_refresh_enrollment_state_snapshot();
create or replace function public.rpc_refresh_enrollment_state_snapshot()
returns void
language plpgsql
security definer
set search_path = public, dev_nexus, pg_catalog
as $$
begin
  begin
    refresh materialized view concurrently dev_nexus.enrollment_state_snapshot;
  exception
    when object_not_in_prerequisite_state then
      refresh materialized view dev_nexus.enrollment_state_snapshot;
  end;
end;
$$;

revoke all on function public.rpc_refresh_enrollment_state_snapshot() from public, anon, authenticated;
grant execute on function public.rpc_refresh_enrollment_state_snapshot() to service_role;

commit;
