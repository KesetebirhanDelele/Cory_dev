-- =====================================================================================
-- Ensure schema exists
-- =====================================================================================
create schema if not exists dev_education;

-- =====================================================================================
-- Helper: resolve call policy (per-campaign override first, then global defaults)
-- Returns exactly one row with fully-coalesced values (safe defaults if nothing found)
-- =====================================================================================
drop function if exists dev_education.fn_resolve_call_policy(uuid, text, text) cascade;
create or replace function dev_education.fn_resolve_call_policy(
  p_campaign_id uuid,
  p_status      text,
  p_end_reason  text
)
returns table(
  is_connected      boolean,
  should_retry      boolean,
  retry_sms         boolean,
  first_retry_mins  int,
  next_retry_mins   int,
  max_retry_days    int,
  align_same_time   boolean
)
language sql
stable
as $$
  with c as (
    select *
    from dev_education.campaign_call_policies
    where campaign_id = p_campaign_id
      and (status = coalesce(p_status, 'ANY') or status = 'ANY')
      and (end_call_reason = coalesce(p_end_reason, 'ANY') or end_call_reason = 'ANY')
    order by
      case when status = coalesce(p_status, 'ANY') then 0 else 1 end,
      case when end_call_reason = coalesce(p_end_reason, 'ANY') then 0 else 1 end
    limit 1
  ),
  g as (
    select *
    from dev_education.phone_log_decisions
    where (status = coalesce(p_status, 'ANY') or status = 'ANY')
      and (end_call_reason = coalesce(p_end_reason, 'ANY') or end_call_reason = 'ANY')
    order by
      case when status = coalesce(p_status, 'ANY') then 0 else 1 end,
      case when end_call_reason = coalesce(p_end_reason, 'ANY') then 0 else 1 end
    limit 1
  )
  select
    coalesce(c.is_connected,    g.is_connected,    false)  as is_connected,
    coalesce(c.should_retry,    g.should_retry,    false)  as should_retry,
    coalesce(c.retry_sms,       g.retry_sms,       false)  as retry_sms,
    coalesce(c.first_retry_mins,g.first_retry_mins,1440)   as first_retry_mins,
    coalesce(c.next_retry_mins, g.next_retry_mins, 1440)   as next_retry_mins,
    coalesce(c.max_retry_days,  g.max_retry_days,  4)      as max_retry_days,
    coalesce(c.align_same_time, g.align_same_time, true)   as align_same_time
  from (select 1) x
  left join c on true
  left join g on true
$$;

-- =====================================================================================
-- Helper: get next step (id, wait, channel) after current_step_id within a campaign
-- Returns 0 or 1 rows
-- =====================================================================================
drop function if exists dev_education.fn_next_step(uuid, uuid) cascade;
create or replace function dev_education.fn_next_step(
  p_campaign_id     uuid,
  p_current_step_id uuid
)
returns table(step_id uuid, wait_before_ms bigint, channel text)
language sql
stable
as $$
  with cur as (
    select order_id
    from dev_education.campaign_steps
    where id = p_current_step_id
  ),
  nxt as (
    select id as step_id, wait_before_ms, channel
    from dev_education.campaign_steps
    where campaign_id = p_campaign_id
      and order_id > (select order_id from cur)
    order by order_id asc
    limit 1
  )
  select * from nxt
$$;

-- =====================================================================================
-- usp_EnrollContactIntoCampaign
-- Closes any existing active enrollment for (org, contact), picks entry step, sets next_run_at
-- RETURNS: enrollment_id (uuid)
-- =====================================================================================
drop function if exists dev_education.usp_EnrollContactIntoCampaign(uuid, uuid, uuid, text) cascade;
create or replace function dev_education.usp_EnrollContactIntoCampaign(
  p_org_id      uuid,
  p_contact_id  uuid,
  p_campaign_id uuid,
  p_reason      text default 'switch'
)
returns uuid
language plpgsql
security definer
set search_path = dev_education, public
as $$
declare
  v_old_id    uuid;
  v_step_id   uuid;
  v_channel   text;
  v_wait_ms   bigint;
  v_next_run  timestamptz;
  v_new_id    uuid;
begin
  -- Close existing active
  select id into v_old_id
  from dev_education.campaign_enrollments
  where org_id = p_org_id
    and contact_id = p_contact_id
    and status = 'active'
  order by started_at desc
  limit 1;

  if v_old_id is not null then
    update dev_education.campaign_enrollments
       set status    = 'switched',
           ended_at  = now(),
           reason    = p_reason,
           updated_at = now()
     where id = v_old_id;
  end if;

  -- Entry step: lowest order_id
  select id, channel, coalesce(wait_before_ms, 0)
    into v_step_id, v_channel, v_wait_ms
  from dev_education.campaign_steps
  where campaign_id = p_campaign_id
  order by order_id asc
  limit 1;

  if v_step_id is null then
    raise exception 'Campaign % has no steps', p_campaign_id;
  end if;

  v_next_run := now() + (v_wait_ms::text || ' milliseconds')::interval;

  insert into dev_education.campaign_enrollments
    (org_id, contact_id, campaign_id, status, started_at,
     current_step_id, next_channel, next_run_at, created_at, updated_at)
  values
    (p_org_id, p_contact_id, p_campaign_id, 'active', now(),
     v_step_id, v_channel, v_next_run, now(), now())
  returning id into v_new_id;

  if v_old_id is not null then
    update dev_education.campaign_enrollments
       set switched_to_enrollment = v_new_id
     where id = v_old_id;
  end if;

  return v_new_id;
end
$$;

-- =====================================================================================
-- usp_ScheduleSmsAfterCall
-- Inserts a planned SMS activity for the current step of the active enrollment
-- RETURNS: activity_id (uuid) or NULL if enrollment not active
-- =====================================================================================
drop function if exists dev_education.usp_ScheduleSmsAfterCall(uuid, text, text, timestamptz, text) cascade;
create or replace function dev_education.usp_ScheduleSmsAfterCall(
  p_enrollment_id uuid,
  p_message       text default null,
  p_prompt_used   text default null,
  p_send_at       timestamptz default null,
  p_provider_ref  text default null
)
returns uuid
language plpgsql
security definer
set search_path = dev_education, public
as $$
declare
  v_org_id     uuid;
  v_campaign_id uuid;
  v_step_id    uuid;
  v_activity_id uuid;
begin
  if p_send_at is null then
    p_send_at := now();
  end if;

  select org_id, campaign_id, current_step_id
    into v_org_id, v_campaign_id, v_step_id
  from dev_education.campaign_enrollments
  where id = p_enrollment_id
    and status = 'active'
  limit 1;

  if v_org_id is null then
    -- no-op for inactive/missing enrollment
    return null;
  end if;

  insert into dev_education.campaign_activities
    (org_id, enrollment_id, campaign_id, step_id, attempt_no, channel,
     status, scheduled_at, sent_at, delivered_at, completed_at,
     outcome, provider_ref, prompt_used, generated_message, ai_analysis,
     provider_call_id, provider_module_id, call_duration_sec, end_call_reason,
     executed_actions_json, prompt_variables_json, recording_url, transcript,
     call_started_at, agent_name, call_timezone, phone_number_to, phone_number_from,
     call_status, campaign_type, created_at, updated_at)
  values
    (v_org_id, p_enrollment_id, v_campaign_id, v_step_id, 1, 'sms',
     'planned', p_send_at, null, null, null,
     null, p_provider_ref, p_prompt_used, p_message, null,
     null, null, null, null,
     null, null, null, null,
     null, null, null, null, null,
     null, null, now(), now())
  returning id into v_activity_id;

  return v_activity_id;
end
$$;

-- =====================================================================================
-- usp_IngestPhoneCallLogs
-- Consume up to p_max_rows rows from phone_call_logs_stg where processed=false
-- For each: log voice activity, apply policy, maybe schedule retry + SMS, or advance/complete
-- RETURNS: number of rows processed
-- =====================================================================================
drop function if exists dev_education.usp_IngestPhoneCallLogs(int, int, boolean, int) cascade;
create or replace function dev_education.usp_IngestPhoneCallLogs(
  p_vm_retry_window_days   int default 4,
  p_vm_retry_interval_mins int default 1440,
  p_schedule_sms_on_retry  boolean default true,
  p_max_rows               int default 100
)
returns int
language plpgsql
security definer
set search_path = dev_education, public
as $$
declare
  v_now           timestamptz := now();
  v_rows          int := 0;
  r               record;

  v_enrollment_id uuid;
  v_contact_id    uuid;
  v_campaign_id   uuid;

  v_org_id        uuid;
  v_step_id       uuid;
  v_order_id      int;
  v_started_at    timestamptz;

  v_is_connected      boolean;
  v_should_retry      boolean;
  v_retry_sms         boolean;
  v_first_retry_mins  int;
  v_next_retry_mins   int;
  v_max_retry_days    int;
  v_align_same_time   boolean;

  v_attempts      int;
  v_next_run      timestamptz;

  v_class         text;
  v_next_step_id  uuid;
  v_next_wait_ms  bigint;
  v_next_channel  text;

  v_first_call_ts timestamptz;
begin
  for r in
    select *
    from dev_education.phone_call_logs_stg
    where processed = false
    order by id
    limit p_max_rows
    for update skip locked
  loop
    v_enrollment_id := r.enrollment_id;
    v_contact_id    := r.contact_id;
    v_campaign_id   := r.campaign_id;

    -- Resolve missing enrollment from active by contact
    if v_enrollment_id is null and v_contact_id is not null then
      select id, campaign_id into v_enrollment_id, v_campaign_id
      from dev_education.campaign_enrollments
      where contact_id = v_contact_id and status = 'active'
      order by started_at desc
      limit 1;
    end if;

    -- Load enrollment state
    select org_id, current_step_id, started_at
      into v_org_id, v_step_id, v_started_at
    from dev_education.campaign_enrollments
    where id = v_enrollment_id and status = 'active'
    limit 1;

    if v_org_id is null then
      update dev_education.phone_call_logs_stg
         set processed = true, processed_at = v_now, error_msg = 'No active enrollment'
       where id = r.id;
      continue;
    end if;

    -- current step order
    select s.order_id into v_order_id
    from dev_education.campaign_steps s
    where s.id = v_step_id;

    -- Log voice activity
    v_attempts := coalesce((
      select count(*) from dev_education.campaign_activities
      where enrollment_id = v_enrollment_id and step_id = v_step_id and channel = 'voice'
    ),0) + 1;

    insert into dev_education.campaign_activities
      (org_id, enrollment_id, campaign_id, step_id, attempt_no, channel,
       status, scheduled_at, sent_at, delivered_at, completed_at,
       outcome, provider_ref, prompt_used, generated_message, ai_analysis,
       provider_call_id, provider_module_id, call_duration_sec, end_call_reason,
       executed_actions_json, prompt_variables_json, recording_url, transcript,
       call_started_at, agent_name, call_timezone, phone_number_to, phone_number_from,
       call_status, campaign_type, created_at, updated_at)
    values
      (v_org_id, v_enrollment_id, v_campaign_id, v_step_id, v_attempts, 'voice',
       'completed', coalesce(r.start_time, v_now), coalesce(r.start_time, v_now), null, v_now,
       r.status, r.call_id, null, null, null,
       r.call_id, r.module_id, r.duration_seconds, r.end_call_reason,
       r.executed_actions, r.prompt_variables, r.recording_url, r.transcript,
       coalesce(r.start_time, v_now), r.agent, r.timezone, r.phone_number_to, r.phone_number_from,
       r.status, r.campaign_type, v_now, v_now);

    -- Policy decision
    select is_connected, should_retry, retry_sms,
           first_retry_mins, next_retry_mins, max_retry_days, align_same_time
    into v_is_connected, v_should_retry, v_retry_sms,
         v_first_retry_mins, v_next_retry_mins, v_max_retry_days, v_align_same_time
    from dev_education.fn_resolve_call_policy(v_campaign_id, r.status, r.end_call_reason);

    -- Retry path
    if (not v_is_connected) and v_should_retry then
      if v_now < (v_started_at + (v_max_retry_days || ' days')::interval) then
        -- choose minutes based on attempts
        if v_attempts <= 1 then
          v_next_run := v_now + (v_first_retry_mins || ' minutes')::interval;
        else
          v_next_run := v_now + (v_next_retry_mins || ' minutes')::interval;
        end if;

        if v_align_same_time then
          select call_started_at into v_first_call_ts
          from dev_education.campaign_activities
          where enrollment_id = v_enrollment_id and step_id = v_step_id and channel = 'voice'
          order by call_started_at asc
          limit 1;

          if v_first_call_ts is not null then
            v_next_run :=
              date_trunc('day', v_next_run)
              + (extract(hour   from v_first_call_ts) || ' hours')::interval
              + (extract(minute from v_first_call_ts) || ' minutes')::interval
              + (extract(second from v_first_call_ts) || ' seconds')::interval;
          end if;
        end if;

        update dev_education.campaign_enrollments
           set next_channel = 'voice',
               next_run_at  = v_next_run,
               updated_at   = v_now
         where id = v_enrollment_id;

        if p_schedule_sms_on_retry and v_retry_sms then
          perform dev_education.usp_ScheduleSmsAfterCall(v_enrollment_id, null, null, v_now, null);
        end if;

        update dev_education.phone_call_logs_stg
           set processed = true, processed_at = v_now, error_msg = null
         where id = r.id;

        v_rows := v_rows + 1;
        continue;
      end if;
      -- else: retry window over → fallthrough to classification/advance
    end if;

    -- Connected or window expired: use classification
    v_class := coalesce(r.classification, 'followup');

    if v_class in ('booked','appointment_booked','cold','not_interested','dnc') then
      update dev_education.campaign_enrollments
         set status = 'completed', ended_at = v_now,
             current_step_id = null, next_channel = null, next_run_at = null,
             updated_at = v_now
       where id = v_enrollment_id;
    else
      -- advance to next step
      select step_id, wait_before_ms, channel
        into v_next_step_id, v_next_wait_ms, v_next_channel
      from dev_education.fn_next_step(v_campaign_id, v_step_id);

      if v_next_step_id is null then
        update dev_education.campaign_enrollments
           set status = 'completed', ended_at = v_now,
               current_step_id = null, next_channel = null, next_run_at = null,
               updated_at = v_now
         where id = v_enrollment_id;
      else
        update dev_education.campaign_enrollments
           set current_step_id = v_next_step_id,
               next_channel    = v_next_channel,
               next_run_at     = v_now + (coalesce(v_next_wait_ms,0)::text || ' milliseconds')::interval,
               updated_at      = v_now
         where id = v_enrollment_id;
      end if;
    end if;

    update dev_education.phone_call_logs_stg
       set processed = true, processed_at = v_now, error_msg = null
     where id = r.id;

    v_rows := v_rows + 1;
  end loop;

  return v_rows;
end
$$;

-- =====================================================================================
-- usp_LogVoiceCallAndAdvance
-- Convenience wrapper: write one call log into staging, then immediately ingest (1 row)
-- RETURNS: staging row id (bigint)
-- =====================================================================================
drop function if exists dev_education.usp_LogVoiceCallAndAdvance(
  uuid, text, text, int, text, jsonb, jsonb, text, text, timestamptz,
  text, text, text, text, text, text, text
) cascade;

create or replace function dev_education.usp_LogVoiceCallAndAdvance(
  p_enrollment_id      uuid,
  p_provider_call_id   text,
  p_provider_module_id text,
  p_duration_seconds   int,
  p_end_call_reason    text,
  p_executed_actions   jsonb,
  p_prompt_variables   jsonb,
  p_recording_url      text,
  p_transcript         text,
  p_call_started_at    timestamptz,
  p_agent_name         text,
  p_call_timezone      text,
  p_phone_to           text,
  p_phone_from         text,
  p_call_status        text,
  p_campaign_type      text,
  p_outcome            text,     -- optional semantic outcome; stored in activity.outcome by ingest
  p_classification     text      -- optional: booked/cold/followup...
)
returns bigint
language plpgsql
security definer
set search_path = dev_education, public
as $$
declare
  v_contact_id   uuid;
  v_campaign_id  uuid;
  v_id           bigint;
begin
  -- resolve contact + campaign for convenience
  select contact_id, campaign_id
    into v_contact_id, v_campaign_id
  from dev_education.campaign_enrollments
  where id = p_enrollment_id
  limit 1;

  insert into dev_education.phone_call_logs_stg
    (enrollment_id, contact_id, campaign_id, type_of_call,
     call_id, module_id, duration_seconds, end_call_reason,
     executed_actions, prompt_variables, recording_url, transcript,
     start_time_epoch_ms, start_time, agent, timezone,
     phone_number_to, phone_number_from, status, campaign_type,
     classification, appointment_time, processed, processed_at, error_msg)
  values
    (p_enrollment_id, v_contact_id, v_campaign_id, 'outbound',
     p_provider_call_id, p_provider_module_id, p_duration_seconds, p_end_call_reason,
     p_executed_actions, p_prompt_variables, p_recording_url, p_transcript,
     null, p_call_started_at, p_agent_name, p_call_timezone,
     p_phone_to, p_phone_from, p_call_status, p_campaign_type,
     p_classification, null, false, null, null)
  returning id into v_id;

  -- Immediately process 1 row
  perform dev_education.usp_IngestPhoneCallLogs(4, 1440, true, 1);

  return v_id;
end
$$;
