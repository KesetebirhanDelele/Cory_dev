DROP VIEW IF EXISTS public.campaign_activity CASCADE;

CREATE OR REPLACE VIEW public.campaign_activity AS
SELECT
    id,
    campaign_id,
    enrollment_id,
    channel,
    status,
    -- sent_at,
    completed_at
    -- outcome
FROM dev_nexus.campaign_activity;

DROP VIEW IF EXISTS public.phone_call_logs_stg CASCADE;

CREATE OR REPLACE VIEW public.phone_call_logs_stg AS
SELECT
    id,
    project_id,
    provider_id,
    provider_ref,
    direction,
    status,
    from_number,
    to_number,
    duration_seconds,
    recording_url,
    transcript,
    occurred_at,
    raw_payload,
    processed_at,
    created_at
FROM dev_nexus.phone_call_logs_stg;

DROP VIEW IF EXISTS public.v_due_actions CASCADE;

CREATE OR REPLACE VIEW public.v_due_actions AS
SELECT
    e.id AS enrollment_id,
    e.lead_id,
    e.campaign_id,
    e.step_index,
    e.next_run_at,
    e.status,
    s.id AS step_id,
    s.channel,
    s.prompt_template,
    s.wait_seconds,
    s.allowed_hours
FROM public.campaign_enrollments e
JOIN public.campaign_steps s
  ON e.campaign_id = s.campaign_id
 AND e.step_index = s.step_index
WHERE
    e.status = 'active'
    AND e.next_run_at <= NOW();

DROP VIEW IF EXISTS public.v_variant_attribution CASCADE;

CREATE OR REPLACE VIEW public.v_variant_attribution AS
SELECT
    channel,
    total_sent,
    delivered,
    failed,
    delivery_rate
FROM dev_nexus.v_variant_attribution;

