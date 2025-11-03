-- ==========================================================
-- 🧩 CORY DATABASE REBUILD SCRIPT — STEP 6 (Seed Data)
-- ==========================================================
BEGIN;

-- ----------------------------------------------------------
-- 1️⃣  Core Entities
-- ----------------------------------------------------------
INSERT INTO public.tenant (id, name, created_at)
VALUES (gen_random_uuid(), 'Demo Tenant', NOW())
ON CONFLICT DO NOTHING;

-- fetch the created tenant_id
DO $$
DECLARE
  t_id uuid;
  org_id uuid;
  proj_id uuid;
  user_id uuid;
  camp_id uuid;
BEGIN
  SELECT id INTO t_id FROM public.tenant LIMIT 1;

  -- organization
  INSERT INTO public.organizations (id, name, slug, timezone, created_at)
  VALUES (gen_random_uuid(), 'Cory University', 'cory-university', 'America/New_York', NOW())
  RETURNING id INTO org_id;

  -- project
  INSERT INTO public.project (id, name, tenant_id, created_at)
  VALUES (gen_random_uuid(), 'Demo Project', t_id, NOW())
  RETURNING id INTO proj_id;

  -- admin user
  INSERT INTO public.users (id, email, first_name, last_name, organization_id, role, is_active, created_at)
  VALUES (
    gen_random_uuid(),
    'admin@cory.ai',
    'Admin',
    'User',
    org_id,
    'admin',
    TRUE,
    NOW()
  )
  RETURNING id INTO user_id;

  -- campaign
  INSERT INTO public.campaigns (id, name, description, organization_id, created_by, is_active, prompts, steps, created_at)
  VALUES (
    gen_random_uuid(),
    'Welcome Series',
    'Introductory onboarding campaign for new leads.',
    org_id,
    user_id,
    TRUE,
    '{}'::jsonb,
    '[]'::jsonb,
    NOW()
  )
  RETURNING id INTO camp_id;

  -- contact
  INSERT INTO public.contact (id, project_id, email, phone, consent, created_at)
  VALUES (gen_random_uuid(), proj_id, 'lead@example.com', '+15555550123', TRUE, NOW());

  -- template + variant
  INSERT INTO public.template (id, name, channel, project_id, created_at)
  VALUES (gen_random_uuid(), 'Welcome Message', 'sms', proj_id, NOW());

  INSERT INTO public.template_variant (id, template_id, name, content, weight, created_at)
  SELECT gen_random_uuid(), t.id, 'Default', '{"text": "Welcome to Cory University!"}'::jsonb, 100, NOW()
  FROM public.template t LIMIT 1;

END $$;

-- ----------------------------------------------------------
-- 2️⃣  Metrics Snapshot
-- ----------------------------------------------------------
INSERT INTO public.campaign_metrics (
  id, campaign_id, date, calls_made, emails_sent, sms_sent, conversions, conversion_rate, leads_processed, created_at
)
SELECT
  gen_random_uuid(),
  id,
  CURRENT_DATE,
  25,
  120,
  180,
  12,
  0.10,
  200,
  NOW()
FROM public.campaigns
LIMIT 1;

COMMIT;


-- ==============================================================
-- 🎟️ Ticket 1: Lead Lifecycle Expansion – SEED DATA (Final)
-- Using plural 'campaigns' table
-- ==============================================================

BEGIN;

-- --------------------------------------------------------------
-- 0️⃣ Tenant
-- --------------------------------------------------------------
INSERT INTO public.tenant (id, name, created_at)
VALUES ('99999999-9999-9999-9999-999999999999', 'Demo Tenant', now())
ON CONFLICT DO NOTHING;

-- --------------------------------------------------------------
-- 1️⃣ Organization
-- --------------------------------------------------------------
INSERT INTO public.organizations (
  id,
  name,
  slug,
  type,
  is_active,
  created_at
)
VALUES (
  '88888888-8888-8888-8888-888888888888',
  'Demo University',
  'demo-university',
  'university',
  TRUE,
  now()
)
ON CONFLICT DO NOTHING;

-- --------------------------------------------------------------
-- 2️⃣ Project
-- --------------------------------------------------------------
INSERT INTO public.project (id, name, tenant_id, created_at)
VALUES (
  '11111111-1111-1111-1111-111111111111',
  'Demo Project',
  '99999999-9999-9999-9999-999999999999',
  now()
)
ON CONFLICT DO NOTHING;

-- --------------------------------------------------------------
-- 3️⃣ Campaign (plural table name)
-- --------------------------------------------------------------
INSERT INTO public.campaigns (id, name, organization_id, is_active, created_at)
VALUES (
  '22222222-2222-2222-2222-222222222222',
  'Fall 2025 Outreach',
  '88888888-8888-8888-8888-888888888888',
  TRUE,
  now()
)
ON CONFLICT DO NOTHING;

-- --------------------------------------------------------------
-- 4️⃣ Lead
-- --------------------------------------------------------------
INSERT INTO public.leads (id, name, email, phone, organization_id, created_at)
VALUES (
  '33333333-3333-3333-3333-333333333333',
  'Alex Rivera',
  'alex@demo.edu',
  '+15555550123',
  '88888888-8888-8888-8888-888888888888',
  now()
)
ON CONFLICT DO NOTHING;

-- --------------------------------------------------------------
-- 5️⃣ Enrollment (extended schema)
-- --------------------------------------------------------------
INSERT INTO public.enrollment (
  id,
  project_id,
  campaign_id,
  contact_id,
  registration_id,
  campaign_type,
  campaign_tier,
  status,
  created_at,
  updated_at
)
VALUES (
  '44444444-4444-4444-4444-444444444444',
  '11111111-1111-1111-1111-111111111111',
  '22222222-2222-2222-2222-222222222222',
  '33333333-3333-3333-3333-333333333333',
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  'standard',
  'tier1',
  'active',
  now(),
  now()
)
ON CONFLICT DO NOTHING;

-- --------------------------------------------------------------
-- 6️⃣ Lead Campaign Steps
-- --------------------------------------------------------------
INSERT INTO public.lead_campaign_steps (
  id,
  registration_id,
  step_order,
  step_name,
  step_type,
  status,
  metadata,
  created_at
)
VALUES
  (
    gen_random_uuid(),
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    1,
    'Intro Email Sent',
    'email',
    'completed',
    '{"template": "welcome_email"}',
    now()
  ),
  (
    gen_random_uuid(),
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    2,
    'SMS Follow-up',
    'sms',
    'pending',
    '{"template": "followup_sms"}',
    now()
  );

-- --------------------------------------------------------------
-- 7️⃣ Appointment
-- --------------------------------------------------------------
INSERT INTO public.appointments (
  id,
  registration_id,
  lead_id,
  project_id,
  campaign_id,
  scheduled_for,
  assigned_to,
  notes,
  created_at,
  updated_at
)
VALUES (
  '55555555-5555-5555-5555-555555555555',
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  '33333333-3333-3333-3333-333333333333',
  '11111111-1111-1111-1111-111111111111',
  '22222222-2222-2222-2222-222222222222',
  now() + interval '3 days',
  NULL,
  'Initial admissions consultation',
  now(),
  now()
)
ON CONFLICT DO NOTHING;

UPDATE public.enrollment
SET appointment_id = '55555555-5555-5555-5555-555555555555'
WHERE registration_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';

-- --------------------------------------------------------------
-- 8️⃣ Nurture Campaign
-- --------------------------------------------------------------
INSERT INTO public.nurture_campaigns (
  id,
  name,
  description,
  organization_id,
  registration_id,
  goal,
  start_date,
  end_date,
  is_active,
  created_at,
  updated_at
)
VALUES (
  '66666666-6666-6666-6666-666666666666',
  'Post-Event Follow-up',
  'Engage students after webinar',
  '88888888-8888-8888-8888-888888888888',
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  'Encourage application submission',
  current_date,
  current_date + interval '30 days',
  TRUE,
  now(),
  now()
)
ON CONFLICT DO NOTHING;

-- --------------------------------------------------------------
-- 9️⃣ Re-engagement Campaign
-- --------------------------------------------------------------
INSERT INTO public.reengagement_campaigns (
  id,
  name,
  description,
  organization_id,
  registration_id,
  trigger_condition,
  is_active,
  created_at,
  updated_at
)
VALUES (
  '77777777-7777-7777-7777-777777777777',
  'Dormant Lead Reconnect',
  'Reaches out to inactive leads',
  '88888888-8888-8888-8888-888888888888',
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  'no activity in 30 days',
  TRUE,
  now(),
  now()
)
ON CONFLICT DO NOTHING;

COMMIT;
