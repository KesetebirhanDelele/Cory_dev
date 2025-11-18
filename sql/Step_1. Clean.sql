BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==========================================================
-- 1️⃣ TENANT & ORGANIZATION STRUCTURE
-- ==========================================================
CREATE TABLE public.tenant (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.project (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    tenant_id uuid NOT NULL REFERENCES public.tenant(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.organizations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    slug text NOT NULL UNIQUE,
    domain text,
    phone text,
    timezone text DEFAULT 'America/New_York',
    website text,
    address jsonb DEFAULT '{}'::jsonb,
    branding jsonb DEFAULT '{}'::jsonb,
    business_hours jsonb DEFAULT '{"start":"09:00","end":"17:00","days":[1,2,3,4,5]}'::jsonb,
    is_active boolean DEFAULT TRUE,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE public.organization_settings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    setting_key text NOT NULL,
    setting_value jsonb NOT NULL,
    setting_type text DEFAULT 'general',
    is_public boolean DEFAULT FALSE,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE public.organization_integrations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    integration_name text NOT NULL,
    integration_type text NOT NULL,
    config jsonb DEFAULT '{}'::jsonb,
    credentials jsonb DEFAULT '{}'::jsonb,
    is_active boolean DEFAULT TRUE,
    sync_status text DEFAULT 'pending',
    error_message text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE public.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid REFERENCES public.organizations(id) ON DELETE CASCADE,
    email text NOT NULL,
    first_name text,
    last_name text,
    avatar_url text,
    role text DEFAULT 'user',
    is_active boolean DEFAULT TRUE,
    permissions jsonb DEFAULT '[]'::jsonb,
    last_login_at timestamptz,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

-- ==========================================================
-- 2️⃣ CORE ENTITIES
-- ==========================================================
CREATE TABLE public.campaigns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    name text NOT NULL,
    description text,
    is_active boolean DEFAULT TRUE,
    max_attempts integer DEFAULT 3,
    policy jsonb DEFAULT '{}'::jsonb,
    prompts jsonb DEFAULT '{}'::jsonb,
    steps jsonb DEFAULT '[]'::jsonb,
    settings jsonb DEFAULT '{}'::jsonb,
    created_by uuid REFERENCES public.users(id),
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    CONSTRAINT uq_campaigns_name_per_org UNIQUE (organization_id, name)
);

CREATE TABLE public.contact (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid REFERENCES public.project(id) ON DELETE CASCADE,
    first_name text,
    last_name text,
    email text,
    phone text,
    wa_number text,
    consent boolean DEFAULT FALSE,
    field_of_study text,
    level_of_interest text DEFAULT 'unknown',
    source text,
    last_interaction_at timestamptz DEFAULT now(),
    created_at timestamptz DEFAULT now(),
    CONSTRAINT uq_contact_project_phone UNIQUE (project_id, phone)
);

CREATE TABLE public.enrollment (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid REFERENCES public.project(id) ON DELETE CASCADE,
    campaign_id uuid REFERENCES public.campaigns(id) ON DELETE SET NULL,
    contact_id uuid REFERENCES public.contact(id) ON DELETE CASCADE,
    registration_id uuid DEFAULT gen_random_uuid(),
    trace_id uuid DEFAULT gen_random_uuid(),
    campaign_type text DEFAULT 'standard',
    campaign_tier text DEFAULT 'tier1',
    status text DEFAULT 'created',
    current_step text,
    last_step_completed integer,
    appointment_id uuid,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    CONSTRAINT uq_enrollment_contact_campaign UNIQUE (contact_id, campaign_id)
);

-- ==========================================================
-- 3️⃣ COMMUNICATION ENTITIES
-- ==========================================================
CREATE TABLE public.message (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.project(id) ON DELETE CASCADE,
    enrollment_id uuid REFERENCES public.enrollment(id) ON DELETE CASCADE,
    channel text NOT NULL, -- email, sms, voice, whatsapp
    direction text NOT NULL, -- inbound/outbound
    content jsonb NOT NULL DEFAULT '{}'::jsonb,
    provider_ref text,
    status text,
    occurred_at timestamptz DEFAULT now(),
    created_at timestamptz DEFAULT now()
);

ALTER TABLE public.message
ADD COLUMN transcript text,
ADD COLUMN audio_url text;

CREATE TABLE public.event (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.project(id) ON DELETE CASCADE,
    enrollment_id uuid REFERENCES public.enrollment(id) ON DELETE CASCADE,
    event_type text NOT NULL,
    direction text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb,
    provider_ref text,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE public.outcome (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid REFERENCES public.project(id) ON DELETE CASCADE,
    enrollment_id uuid REFERENCES public.enrollment(id) ON DELETE CASCADE,
    variant_id uuid,
    kind text NOT NULL,
    value text,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE public.handoff (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid REFERENCES public.project(id) ON DELETE CASCADE,
    enrollment_id uuid REFERENCES public.enrollment(id) ON DELETE CASCADE,
    status text DEFAULT 'open',
    assignee text,
    sla_due_at timestamptz,
    resolved_at timestamptz,
    created_at timestamptz DEFAULT now()
);

-- ==========================================================
-- 4️⃣ CONTENT & CAMPAIGN ASSETS
-- ==========================================================
CREATE TABLE public.template (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid REFERENCES public.project(id) ON DELETE CASCADE,
    name text NOT NULL,
    channel text NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE public.template_variant (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id uuid REFERENCES public.template(id) ON DELETE CASCADE,
    name text NOT NULL,
    content jsonb NOT NULL DEFAULT '{}'::jsonb,
    weight integer DEFAULT 100,
    created_at timestamptz DEFAULT now()
);

-- ==========================================================
-- 5️⃣ APPOINTMENTS & CAMPAIGN VARIANTS
-- ==========================================================
CREATE TABLE public.appointments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    registration_id uuid,
    lead_id uuid,
    project_id uuid REFERENCES public.project(id) ON DELETE CASCADE,
    campaign_id uuid REFERENCES public.campaigns(id) ON DELETE SET NULL,
    scheduled_for timestamptz NOT NULL,
    completed_at timestamptz,
    canceled_at timestamptz,
    assigned_to uuid REFERENCES public.users(id),
    outcome text,
    notes text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE public.lead_campaign_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    registration_id uuid REFERENCES public.enrollment(registration_id) ON DELETE CASCADE,
    step_order integer NOT NULL,
    step_name text NOT NULL,
    step_type text NOT NULL, -- email, sms, call, meeting
    template_id uuid REFERENCES public.template(id) ON DELETE SET NULL,
    completed_at timestamptz,
    status text DEFAULT 'pending',
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamptz DEFAULT now()
);

ALTER TABLE public.lead_campaign_steps
ADD COLUMN intent text,
ADD COLUMN next_action text,
ADD COLUMN transcript text,
ADD COLUMN updated_at timestamptz DEFAULT now();

CREATE TABLE public.nurture_campaigns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    description text,
    organization_id uuid REFERENCES public.organizations(id) ON DELETE CASCADE,
    registration_id uuid REFERENCES public.enrollment(registration_id) ON DELETE SET NULL,
    goal text,
    start_date date,
    end_date date,
    is_active boolean DEFAULT TRUE,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE public.reengagement_campaigns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    description text,
    organization_id uuid REFERENCES public.organizations(id) ON DELETE CASCADE,
    registration_id uuid REFERENCES public.enrollment(registration_id) ON DELETE SET NULL,
    trigger_condition text,
    message_template_id uuid REFERENCES public.template(id),
    is_active boolean DEFAULT TRUE,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

ALTER TABLE public.enrollment ALTER COLUMN status SET DEFAULT 'created';
ALTER TABLE public.message ALTER COLUMN status SET DEFAULT 'pending';

ALTER TABLE public.enrollment
    ADD COLUMN IF NOT EXISTS program_interest text,
    ADD COLUMN IF NOT EXISTS start_term text,
    ADD COLUMN IF NOT EXISTS preferred_channel text,
    ADD COLUMN IF NOT EXISTS preferred_contact_times jsonb DEFAULT '[]'::jsonb;

-- first_name / last_name stay on public.contact (no duplication)

------------------------------------------------------------
-- 2️⃣ Extend lead_campaign_steps for full lifecycle tracking
------------------------------------------------------------

ALTER TABLE public.lead_campaign_steps
    ADD COLUMN IF NOT EXISTS enrollment_id uuid REFERENCES public.enrollment(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS campaign_id uuid REFERENCES public.campaigns(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS channel text,       -- sms | email | voice | whatsapp
    ADD COLUMN IF NOT EXISTS direction text,     -- outbound | inbound
    ADD COLUMN IF NOT EXISTS prompt_used text,   -- dynamic prompt sent to Synthflow
    ADD COLUMN IF NOT EXISTS provider_ref text,  -- Synthflow call/message ID
    ADD COLUMN IF NOT EXISTS started_at timestamptz,
    ADD COLUMN IF NOT EXISTS next_run_at timestamptz;

-- Optional backfill for existing rows (ties steps to enrollment/campaign using registration_id)
UPDATE public.lead_campaign_steps lcs
SET
    enrollment_id = e.id,
    campaign_id   = e.campaign_id
FROM public.enrollment e
WHERE lcs.enrollment_id IS NULL
  AND lcs.registration_id = e.registration_id;

------------------------------------------------------------
-- 3️⃣ Extend appointments with enrollment + channel info
------------------------------------------------------------

ALTER TABLE public.appointments
    ADD COLUMN IF NOT EXISTS enrollment_id uuid REFERENCES public.enrollment(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS channel text,            -- phone | zoom | in_person
    ADD COLUMN IF NOT EXISTS source text,             -- synthflow_voice | sms_link | email_link | manual
    ADD COLUMN IF NOT EXISTS calendar_event_id text,  -- Google/HubSpot event ID
    ADD COLUMN IF NOT EXISTS status text DEFAULT 'scheduled';

-- Optional: backfill enrollment_id using registration_id where possible
UPDATE public.appointments a
SET enrollment_id = e.id
FROM public.enrollment e
WHERE a.enrollment_id IS NULL
  AND a.registration_id IS NOT NULL
  AND a.registration_id = e.registration_id;

------------------------------------------------------------
-- 4️⃣ Campaign enrollments table (fresh, correct shape)
------------------------------------------------------------

-- If you had an older/incorrect version, drop it so we can recreate.
DROP TABLE IF EXISTS public.campaign_enrollments;

CREATE TABLE public.campaign_enrollments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id uuid NOT NULL REFERENCES public.enrollment(id) ON DELETE CASCADE,
    campaign_id uuid NOT NULL REFERENCES public.campaigns(id) ON DELETE CASCADE,
    campaign_type text NOT NULL DEFAULT 'lead',  -- lead | nurture | reengagement
    tier text DEFAULT 'tier1',
    is_active boolean DEFAULT TRUE,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    CONSTRAINT uq_campaign_enrollment UNIQUE (enrollment_id, campaign_id, campaign_type)
);

COMMIT;

-- Indexes for performance optimization
CREATE INDEX idx_campaigns_org_id ON public.campaigns (organization_id);
CREATE INDEX idx_enrollment_campaign_id ON public.enrollment (campaign_id);
CREATE INDEX idx_contact_project_id ON public.contact (project_id);
CREATE INDEX idx_message_enrollment_id ON public.message (enrollment_id);

-- Seeding Data 

BEGIN;

-- ==========================================================
-- 🚿 SAFE RESET (no Supabase ownership conflicts)
-- ==========================================================
-- 🔹 We do NOT truncate public.users or auth.users — Supabase owns them
-- 🔹 We just clean application tables in dependency order
DELETE FROM public.message;
DELETE FROM public.event;
DELETE FROM public.outcome;
DELETE FROM public.lead_campaign_steps;
DELETE FROM public.enrollment;
DELETE FROM public.contact;
DELETE FROM public.template_variant;
DELETE FROM public.template;
DELETE FROM public.campaigns;
DELETE FROM public.organization_integrations;
DELETE FROM public.organization_settings;
DELETE FROM public.organizations;
DELETE FROM public.project;
DELETE FROM public.tenant;

-- ==========================================================
-- 1️⃣ TENANT, PROJECT, ORGANIZATION
-- ==========================================================
INSERT INTO public.tenant (id, name)
VALUES ('11111111-1111-1111-1111-111111111111', 'Cory Platform');

INSERT INTO public.project (id, name, tenant_id)
VALUES ('22222222-2222-2222-2222-222222222222', 'Admissions Automation', '11111111-1111-1111-1111-111111111111');

INSERT INTO public.organizations (id, name, slug, domain, phone, website)
VALUES ('33333333-3333-3333-3333-333333333333', 'Cory Admissions', 'cory-admissions', 'cory.edu', '+1-555-2000', 'https://cory.edu');

INSERT INTO public.organization_settings (id, organization_id, setting_key, setting_value)
VALUES
  ('44444444-4444-4444-4444-444444444441', '33333333-3333-3333-3333-333333333333', 'lead_scoring', '{"enabled": true, "threshold": 70}'::jsonb),
  ('44444444-4444-4444-4444-444444444442', '33333333-3333-3333-3333-333333333333', 'timezone', '{"tz": "America/New_York"}'::jsonb);

INSERT INTO public.organization_integrations 
(id, organization_id, integration_name, integration_type, config)
VALUES
  ('55555555-5555-5555-5555-555555555551', 
   '33333333-3333-3333-3333-333333333333', 
   'Mandrill', 
   'mandrill', 
   '{"api_key": "MANDRILL_TEST_KEY"}'::jsonb),

  ('55555555-5555-5555-5555-555555555552', 
   '33333333-3333-3333-3333-333333333333', 
   'SlickText', 
   'slicktext', 
   '{"api_key": "SLICKTEXT_TEST_KEY"}'::jsonb),

  ('55555555-5555-5555-5555-555555555553', 
   '33333333-3333-3333-3333-333333333333', 
   'Synthflow', 
   'synthflow', 
   '{"token": "SYNTHFLOW_TEST_KEY"}'::jsonb);

-- ==========================================================
-- 2️⃣ CAMPAIGNS & CONTENT
-- ==========================================================
-- 🔹 Reuse any existing Supabase user for created_by (replace below)
-- Run: SELECT id, email FROM public.users LIMIT 1;
-- Then paste that UUID into created_by

INSERT INTO public.campaigns (id, organization_id, name, description, created_by, steps)
VALUES
  ('77777777-7777-7777-7777-777777777771', '33333333-3333-3333-3333-333333333333',
   'Fall 2025 Outreach', 'Primary fall admissions campaign.',
   NULL,  -- or '<existing-user-id>'
   '[{"step":1,"name":"Email Intro","type":"email"},{"step":2,"name":"SMS Reminder","type":"sms"},{"step":3,"name":"Call Followup","type":"voice"}]'::jsonb),
  ('77777777-7777-7777-7777-777777777772', '33333333-3333-3333-3333-333333333333',
   'Reengagement Series', 'Follow-up for inactive leads.',
   NULL,
   '[{"step":1,"name":"Reengagement Email","type":"email"},{"step":2,"name":"Final SMS","type":"sms"}]'::jsonb);

INSERT INTO public.template (id, project_id, name, channel)
VALUES
  ('88888888-8888-8888-8888-888888888881', '22222222-2222-2222-2222-222222222222', 'Welcome Email', 'email'),
  ('88888888-8888-8888-8888-888888888882', '22222222-2222-2222-2222-222222222222', 'Followup SMS', 'sms');

INSERT INTO public.template_variant (id, template_id, name, content)
VALUES
  ('99999999-9999-9999-9999-999999999991', '88888888-8888-8888-8888-888888888881', 'A/B Subject Test', '{"subject":"Welcome to Cory!","body":"Thank you for applying!"}'::jsonb);

-- ==========================================================
-- 3️⃣ CONTACTS & ENROLLMENTS
-- ==========================================================
INSERT INTO public.contact (id, project_id, first_name, last_name, email, phone, consent, source)
VALUES
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1', '22222222-2222-2222-2222-222222222222', 'Evelyn', 'Brooks', 'evelyn.brooks@example.com', '+15550001', TRUE, 'landing_page'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2', '22222222-2222-2222-2222-222222222222', 'Carlos', 'Ramirez', 'carlos.ramirez@example.com', '+15550002', TRUE, 'webinar'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3', '22222222-2222-2222-2222-222222222222', 'Fatima', 'Ali', 'fatima.ali@example.com', '+15550003', TRUE, 'referral'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa4', '22222222-2222-2222-2222-222222222222', 'Daniel', 'Hughes', 'daniel.hughes@example.com', '+15550004', TRUE, 'social_ad'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa5', '22222222-2222-2222-2222-222222222222', 'Sophia', 'Mendez', 'sophia.mendez@example.com', '+15550005', TRUE, 'webinar');

INSERT INTO public.enrollment (id, project_id, campaign_id, contact_id, status, current_step)
VALUES
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1', '22222222-2222-2222-2222-222222222222', '77777777-7777-7777-7777-777777777771', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1', 'in_progress', 'Email Intro'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2', '22222222-2222-2222-2222-222222222222', '77777777-7777-7777-7777-777777777771', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2', 'created', 'Email Intro'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3', '22222222-2222-2222-2222-222222222222', '77777777-7777-7777-7777-777777777771', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3', 'completed', 'Call Followup'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb4', '22222222-2222-2222-2222-222222222222', '77777777-7777-7777-7777-777777777771', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa4', 'in_progress', 'SMS Reminder'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb5', '22222222-2222-2222-2222-222222222222', '77777777-7777-7777-7777-777777777772', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa5', 'created', 'Reengagement Email');

-- ==========================================================
-- 4️⃣ CAMPAIGN STEPS
-- ==========================================================
INSERT INTO public.lead_campaign_steps (id, registration_id, step_order, step_name, step_type, status)
SELECT gen_random_uuid(), e.registration_id, (s.step->>'step')::integer, s.step->>'name', s.step->>'type', 'pending'
FROM public.enrollment e
JOIN LATERAL jsonb_array_elements(
  '[{"step":1,"name":"Email Intro","type":"email"},{"step":2,"name":"SMS Reminder","type":"sms"},{"step":3,"name":"Call Followup","type":"voice"}]'::jsonb
) AS s(step) ON TRUE
WHERE e.campaign_id = '77777777-7777-7777-7777-777777777771';

-- ==========================================================
-- 5️⃣ COMMUNICATION LOGS
-- ==========================================================
INSERT INTO public.message (id, project_id, enrollment_id, channel, direction, content, status)
VALUES
  (gen_random_uuid(), '22222222-2222-2222-2222-222222222222', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1', 'email', 'outbound', '{"subject":"Welcome!","body":"Hello Evelyn!"}'::jsonb, 'sent'),
  (gen_random_uuid(), '22222222-2222-2222-2222-222222222222', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1', 'sms', 'inbound', '{"message":"Thanks for reaching out!"}'::jsonb, 'received');

INSERT INTO public.event (id, project_id, enrollment_id, event_type, direction, payload)
VALUES
  (gen_random_uuid(), '22222222-2222-2222-2222-222222222222', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1', 'email_opened', 'inbound', '{"opened_at":"2025-11-05T15:00Z"}'::jsonb);

INSERT INTO public.outcome (id, project_id, enrollment_id, kind, value)
VALUES
  (gen_random_uuid(), '22222222-2222-2222-2222-222222222222', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1', 'engagement_score', 'high');

-- ==========================================================
-- 6️⃣ SECONDARY CAMPAIGNS
-- ==========================================================
INSERT INTO public.nurture_campaigns (id, name, organization_id, goal, start_date, end_date)
VALUES
  ('cccccccc-cccc-cccc-cccc-ccccccccccc1', 'Spring Nurture 2025', '33333333-3333-3333-3333-333333333333', 'Re-engage warm leads', '2025-02-01', '2025-06-01');

INSERT INTO public.reengagement_campaigns (id, name, organization_id, trigger_condition, message_template_id)
VALUES
  ('cccccccc-cccc-cccc-cccc-ccccccccccc2', 'Dormant Reconnect', '33333333-3333-3333-3333-333333333333', 'no_response_30_days', '88888888-8888-8888-8888-888888888881');

COMMIT;

BEGIN;

INSERT INTO public.lead_campaign_steps (
    id,
    registration_id,
    enrollment_id,
    campaign_id,
    step_order,
    step_name,
    step_type,
    channel,
    direction,
    status,
    prompt_used,
    provider_ref,
    metadata,
    started_at,
    completed_at
)
SELECT
    gen_random_uuid(),
    e.registration_id,
    e.id,
    e.campaign_id,
    99,
    'Voice Outreach (Seed)',
    'voice',
    'voice',
    'outbound',
    'completed',
    'You are Cory, an AI admissions assistant for Cory College. You are calling a prospective student about their registration and interest in our programs...',
    'TEST-CALL-ID-123',
    jsonb_build_object('seed', true, 'note', 'example voice step for Ticket 1'),
    now() - interval '5 minutes',
    now()
FROM public.enrollment e
LIMIT 1;

COMMIT;
