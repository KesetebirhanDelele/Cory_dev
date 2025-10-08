-- seed_all.sql — Minimal, idempotent data for dev_nexus (extended with campaign automation)
BEGIN;

-- Treat this session like service_role (RLS baseline bypass for seeding)
SELECT set_config('request.jwt.claims', '{"role":"service_role"}', true);

CREATE SCHEMA IF NOT EXISTS dev_nexus;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
DECLARE
  -- fixed IDs (idempotent re-runs)
  v_tenant     uuid := '11111111-1111-1111-1111-111111111111';
  v_project    uuid := '22222222-2222-2222-2222-222222222222';
  v_contact    uuid := '33333333-3333-3333-3333-333333333333';
  v_campaign   uuid := '44444444-4444-4444-4444-444444444444';
  v_enroll     uuid := '55555555-5555-5555-5555-555555555555';
  v_provider   uuid := '66666666-6666-6666-6666-666666666666';
  v_template   uuid := '77777777-7777-7777-7777-777777777777';
  v_variant    uuid := '88888888-8888-8888-8888-888888888888';
  -- new: steps/policy/activity IDs
  v_step1      uuid := 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1';
  v_step2      uuid := 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2';
  v_policy     uuid := 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
  v_activity   uuid := 'cccccccc-cccc-cccc-cccc-cccccccccccc';
  -- provider refs must be unique per (provider_ref, direction)
  v_msg_ref    text := 'seed-msg-1';
  v_evt_ref    text := 'seed-evt-1';
  v_call_ref   text := 'seed-call-1';  -- for staging → normalization
  v_now        timestamptz := now();
BEGIN
  -- 1) Tenancy
  INSERT INTO dev_nexus.tenant (id, name)
  VALUES (v_tenant, 'Acme U')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO dev_nexus.project (id, tenant_id, name)
  VALUES (v_project, v_tenant, 'Acme Recruiting')
  ON CONFLICT (id) DO NOTHING;

  -- 2) Contacts & Campaigns
  INSERT INTO dev_nexus.contact (id, project_id, full_name, email, phone)
  VALUES (v_contact, v_project, 'Casey Student', 'casey@example.com', '+15555550100')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO dev_nexus.campaign (id, project_id, name)
  VALUES (v_campaign, v_project, 'Fall Outreach')
  ON CONFLICT (id) DO NOTHING;

  -- 3) Enrollment & dependents
  INSERT INTO dev_nexus.enrollment (id, project_id, campaign_id, contact_id, status)
  VALUES (v_enroll, v_project, v_campaign, v_contact, 'active')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO dev_nexus.outcome (id, enrollment_id, kind, notes)
  VALUES (gen_random_uuid(), v_enroll, 'interested', 'left VM')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO dev_nexus.handoff (id, enrollment_id, to_owner)
  VALUES (gen_random_uuid(), v_enroll, 'Admissions Counselor A')
  ON CONFLICT (id) DO NOTHING;

  -- 4) Providers + initial channel events
  INSERT INTO dev_nexus.providers (id, name)
  VALUES (v_provider, 'TestProvider')
  ON CONFLICT (id) DO NOTHING;

  -- keep refs unique per (provider_ref, direction)
  -- message (unique on provider_ref,direction)
  INSERT INTO dev_nexus.message (id, project_id, provider_id, provider_ref, direction, payload, created_at)
  VALUES (gen_random_uuid(), v_project, v_provider, v_msg_ref, 'outbound', '{}'::jsonb, v_now - interval '5 minutes')
  ON CONFLICT (provider_ref, direction) 
  DO UPDATE SET
    project_id = EXCLUDED.project_id,
    provider_id = EXCLUDED.provider_id;  -- event (unique on provider_ref,direction)
  INSERT INTO dev_nexus.event (id, project_id, provider_id, provider_ref, direction, type, data, created_at)
  VALUES (gen_random_uuid(), v_project, v_provider, v_evt_ref, 'outbound', 'classification', '{}'::jsonb, v_now - interval '4 minutes')
  ON CONFLICT (provider_ref, direction) 
  DO UPDATE SET
    project_id = EXCLUDED.project_id,
    provider_id = EXCLUDED.provider_id;

  -- 5) Templates
  INSERT INTO dev_nexus.template (id, name, description, body)
  VALUES (v_template, 'Welcome', 'Welcome message', jsonb_build_object('subject','Hi','text','Hello!'))
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO dev_nexus.template_variant (id, template_id, name, body)
  VALUES (v_variant, v_template, 'A', jsonb_build_object('text','Hello, {{name}}!'))
  ON CONFLICT (id) DO NOTHING;

  -- 6) Campaign Playbook (steps + policy)
  INSERT INTO dev_nexus.campaign_step (id, campaign_id, step_order, name, channel, action, delay_minutes, template_id, template_variant_id, retry_limit, metadata, created_at)
  VALUES
    (v_step1, v_campaign, 1, 'Intro Call', 'voice',  'call',       0,  NULL, NULL, 1, '{}'::jsonb, v_now - interval '6 minutes'),
    (v_step2, v_campaign, 2, 'SMS Followup', 'sms',  'send_sms',  10,  v_template, v_variant, 0, jsonb_build_object('cta','reply YES'), v_now - interval '6 minutes')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO dev_nexus.campaign_call_policy (id, campaign_id, max_attempts, min_minutes_between_attempts, allow_voicemail, quiet_hours, business_days, created_at)
  VALUES (v_policy, v_campaign, 3, 60, true, '{"start":"21:00","end":"08:00","tz":"America/New_York"}', '[1,2,3,4,5]'::jsonb, v_now - interval '6 minutes')
  ON CONFLICT (id) DO NOTHING;

  -- 7) Seed first activity via RPC (idempotent: seeds only if none exist)
  PERFORM dev_nexus.usp_enrollcontactintocampaign(v_project, v_contact, v_campaign);

  -- Ensure at least one activity exists and is due now-ish (some runners call immediately)
  INSERT INTO dev_nexus.campaign_activity (
    id, enrollment_id, campaign_id, contact_id, step_id, channel, status, attempt_no, due_at, created_at
  )
  SELECT v_activity, v_enroll, v_campaign, v_contact, v_step1, 'voice', 'pending', 0, v_now - interval '1 minute', v_now - interval '2 minutes'
  WHERE NOT EXISTS (
    SELECT 1 FROM dev_nexus.campaign_activity WHERE enrollment_id = v_enroll
  );

  -- 8) Stage a call log then normalize with RPC
  INSERT INTO dev_nexus.phone_call_logs_stg (
    id, project_id, provider_id, provider_ref, direction, status, from_number, to_number,
    duration_seconds, recording_url, transcript, occurred_at, raw_payload, created_at
  )
  VALUES (
    gen_random_uuid(), v_project, v_provider, v_call_ref, 'outbound', 'completed',
    '+15555550111', '+15555550100', 42, 'https://example.com/rec.wav', 'Sample transcript',
    v_now - interval '3 minutes', jsonb_build_object('note','seeded'), v_now - interval '3 minutes'
  )
  ON CONFLICT DO NOTHING;

  -- Will upsert into message/event (respects unique(provider_ref,direction))
  PERFORM dev_nexus.usp_ingestphonecalllogs();

END $$;

COMMIT;

-- Quick check (optional)
SELECT 'tenant' t, count(*) FROM dev_nexus.tenant
UNION ALL SELECT 'project', count(*) FROM dev_nexus.project
UNION ALL SELECT 'contact', count(*) FROM dev_nexus.contact
UNION ALL SELECT 'campaign', count(*) FROM dev_nexus.campaign
UNION ALL SELECT 'enrollment', count(*) FROM dev_nexus.enrollment
UNION ALL SELECT 'outcome', count(*) FROM dev_nexus.outcome
UNION ALL SELECT 'handoff', count(*) FROM dev_nexus.handoff
UNION ALL SELECT 'providers', count(*) FROM dev_nexus.providers
UNION ALL SELECT 'message', count(*) FROM dev_nexus.message
UNION ALL SELECT 'event', count(*) FROM dev_nexus.event
UNION ALL SELECT 'template', count(*) FROM dev_nexus.template
UNION ALL SELECT 'template_variant', count(*) FROM dev_nexus.template_variant
UNION ALL SELECT 'campaign_step', count(*) FROM dev_nexus.campaign_step
UNION ALL SELECT 'campaign_activity', count(*) FROM dev_nexus.campaign_activity
UNION ALL SELECT 'campaign_call_policy', count(*) FROM dev_nexus.campaign_call_policy
UNION ALL SELECT 'phone_call_logs_stg', count(*) FROM dev_nexus.phone_call_logs_stg
ORDER BY 1;
