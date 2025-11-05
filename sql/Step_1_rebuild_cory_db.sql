-- ==========================================================
-- 🧩 CORY DATABASE REBUILD SCRIPT (Schema + Tables)
-- ==========================================================
BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==========================================================
-- 1️⃣ ORGANIZATIONAL STRUCTURE
-- ==========================================================
CREATE TABLE public.tenant (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.project (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    tenant_id uuid NOT NULL REFERENCES public.tenant(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.organizations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    slug text NOT NULL,
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
    organization_id uuid REFERENCES public.organizations(id),
    setting_key text NOT NULL,
    setting_value jsonb NOT NULL,
    setting_type text DEFAULT 'general',
    is_public boolean DEFAULT FALSE,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE public.organization_integrations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid REFERENCES public.organizations(id),
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
    id uuid PRIMARY KEY,
    organization_id uuid REFERENCES public.organizations(id),
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
    organization_id uuid REFERENCES public.organizations(id),
    name text NOT NULL,
    description text,
    is_active boolean DEFAULT TRUE,
    max_attempts integer DEFAULT 3,
    policy jsonb DEFAULT '{}'::jsonb,
    prompts jsonb NOT NULL DEFAULT '{}'::jsonb,
    steps jsonb NOT NULL DEFAULT '[]'::jsonb,
    settings jsonb DEFAULT '{}'::jsonb,
    created_by uuid REFERENCES public.users(id),
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE public.contact (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid REFERENCES public.project(id),
    email text,
    phone text,
    wa_number text,
    consent boolean NOT NULL DEFAULT FALSE,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ==========================================================
-- 🔧 CONTACT TABLE SCHEMA UPGRADE
-- Adds fields for personalization, outreach, and lead info
-- ==========================================================

ALTER TABLE public.contact
ADD COLUMN IF NOT EXISTS first_name text,
ADD COLUMN IF NOT EXISTS last_name text,
ADD COLUMN IF NOT EXISTS field_of_study text,
ADD COLUMN IF NOT EXISTS level_of_interest text DEFAULT 'unknown',  -- e.g. high | medium | low | unknown
ADD COLUMN IF NOT EXISTS source text,                                -- e.g. webinar, landing_page, referral
ADD COLUMN IF NOT EXISTS last_interaction_at timestamptz DEFAULT now();

CREATE TABLE public.enrollment (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid REFERENCES public.project(id),
    campaign_id uuid REFERENCES public.campaigns(id),
    contact_id uuid REFERENCES public.contact(id),
    trace_id uuid NOT NULL DEFAULT gen_random_uuid(),
    status text NOT NULL DEFAULT 'created',
    current_step text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.message (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.project(id),
    enrollment_id uuid REFERENCES public.enrollment(id),
    channel text NOT NULL,
    direction text NOT NULL,
    content jsonb NOT NULL DEFAULT '{}'::jsonb,
    provider_ref text,
    status text,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.event (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.project(id),
    enrollment_id uuid REFERENCES public.enrollment(id),
    event_type text NOT NULL,
    direction text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    provider_ref text,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE public.outcome (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid REFERENCES public.project(id),
    enrollment_id uuid REFERENCES public.enrollment(id),
    variant_id uuid,
    kind text NOT NULL,
    value text,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE public.handoff (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.project(id),
    enrollment_id uuid NOT NULL REFERENCES public.enrollment(id),
    status text NOT NULL DEFAULT 'open',
    assignee text,
    sla_due_at timestamptz,
    resolved_at timestamptz,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE public.template (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.project(id),
    name text NOT NULL,
    channel text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.template_variant (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id uuid NOT NULL REFERENCES public.template(id),
    name text NOT NULL,
    content jsonb NOT NULL DEFAULT '{}'::jsonb,
    weight integer NOT NULL DEFAULT 100,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.appointments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  registration_id uuid,
  lead_id uuid REFERENCES public.leads(id) ON DELETE CASCADE,
  project_id uuid REFERENCES public.project(id) ON DELETE CASCADE,
  campaign_id uuid REFERENCES public.campaigns(id) ON DELETE SET NULL,
  scheduled_for timestamptz NOT NULL,
  completed_at timestamptz,
  canceled_at timestamptz,
  assigned_to uuid REFERENCES public.users(id),
  outcome text,
  notes text,
  created_at timestamptz DEFAULT NOW(),
  updated_at timestamptz DEFAULT NOW()
);

-- --------------------------------------------------------------
-- 2️⃣ Extend existing enrollment table
-- --------------------------------------------------------------
ALTER TABLE public.enrollment
  ADD COLUMN IF NOT EXISTS registration_id uuid DEFAULT gen_random_uuid(),
  ADD COLUMN IF NOT EXISTS campaign_type text DEFAULT 'standard',  -- e.g. standard | nurture | reengagement
  ADD COLUMN IF NOT EXISTS campaign_tier text DEFAULT 'tier1',     -- e.g. tier1 | tier2 | premium
  ADD COLUMN IF NOT EXISTS last_step_completed integer,
  ADD COLUMN IF NOT EXISTS appointment_id uuid;

-- --------------------------------------------------------------
-- 3️⃣ New Table: lead_campaign_steps
-- --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.lead_campaign_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  registration_id uuid NOT NULL REFERENCES public.enrollment(registration_id) ON DELETE CASCADE,
  step_order integer NOT NULL,
  step_name text NOT NULL,
  step_type text NOT NULL,  -- e.g. email, sms, call, meeting
  template_id uuid REFERENCES public.template(id),
  completed_at timestamptz,
  status text DEFAULT 'pending',
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamptz DEFAULT NOW()
);

-- --------------------------------------------------------------
-- 4️⃣ New Table: nurture_campaigns
-- --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.nurture_campaigns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  description text,
  organization_id uuid REFERENCES public.organizations(id) ON DELETE CASCADE,
  registration_id uuid REFERENCES public.enrollment(registration_id) ON DELETE SET NULL,
  goal text,
  start_date date,
  end_date date,
  is_active boolean DEFAULT TRUE,
  created_at timestamptz DEFAULT NOW(),
  updated_at timestamptz DEFAULT NOW()
);

-- --------------------------------------------------------------
-- 5️⃣ New Table: reengagement_campaigns
-- --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.reengagement_campaigns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  description text,
  organization_id uuid REFERENCES public.organizations(id) ON DELETE CASCADE,
  registration_id uuid REFERENCES public.enrollment(registration_id) ON DELETE SET NULL,
  trigger_condition text,   -- e.g. "no response in 30 days"
  message_template_id uuid REFERENCES public.template(id),
  is_active boolean DEFAULT TRUE,
  created_at timestamptz DEFAULT NOW(),
  updated_at timestamptz DEFAULT NOW()
);

-- --------------------------------------------------------------
-- 1️⃣ New Table: appointments  (must come first)
-- --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.appointments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  registration_id uuid,
  lead_id uuid REFERENCES public.leads(id) ON DELETE CASCADE,
  project_id uuid REFERENCES public.project(id) ON DELETE CASCADE,
  campaign_id uuid REFERENCES public.campaigns(id) ON DELETE SET NULL,
  scheduled_for timestamptz NOT NULL,
  completed_at timestamptz,
  canceled_at timestamptz,
  assigned_to uuid REFERENCES public.users(id),
  outcome text,
  notes text,
  created_at timestamptz DEFAULT NOW(),
  updated_at timestamptz DEFAULT NOW()
);

-- --------------------------------------------------------------
-- 2️⃣ Extend existing enrollment table
-- --------------------------------------------------------------
ALTER TABLE public.enrollment
  ADD COLUMN IF NOT EXISTS registration_id uuid DEFAULT gen_random_uuid(),
  ADD COLUMN IF NOT EXISTS campaign_type text DEFAULT 'standard',  -- e.g. standard | nurture | reengagement
  ADD COLUMN IF NOT EXISTS campaign_tier text DEFAULT 'tier1',     -- e.g. tier1 | tier2 | premium
  ADD COLUMN IF NOT EXISTS last_step_completed integer,
  ADD COLUMN IF NOT EXISTS appointment_id uuid;

-- --------------------------------------------------------------
-- 3️⃣ New Table: lead_campaign_steps
-- --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.lead_campaign_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  registration_id uuid NOT NULL REFERENCES public.enrollment(registration_id) ON DELETE CASCADE,
  step_order integer NOT NULL,
  step_name text NOT NULL,
  step_type text NOT NULL,  -- e.g. email, sms, call, meeting
  template_id uuid REFERENCES public.template(id),
  completed_at timestamptz,
  status text DEFAULT 'pending',
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamptz DEFAULT NOW()
);

-- --------------------------------------------------------------
-- 4️⃣ New Table: nurture_campaigns
-- --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.nurture_campaigns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  description text,
  organization_id uuid REFERENCES public.organizations(id) ON DELETE CASCADE,
  registration_id uuid REFERENCES public.enrollment(registration_id) ON DELETE SET NULL,
  goal text,
  start_date date,
  end_date date,
  is_active boolean DEFAULT TRUE,
  created_at timestamptz DEFAULT NOW(),
  updated_at timestamptz DEFAULT NOW()
);

-- --------------------------------------------------------------
-- 5️⃣ New Table: reengagement_campaigns
-- --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.reengagement_campaigns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  description text,
  organization_id uuid REFERENCES public.organizations(id) ON DELETE CASCADE,
  registration_id uuid REFERENCES public.enrollment(registration_id) ON DELETE SET NULL,
  trigger_condition text,   -- e.g. "no response in 30 days"
  message_template_id uuid REFERENCES public.template(id),
  is_active boolean DEFAULT TRUE,
  created_at timestamptz DEFAULT NOW(),
  updated_at timestamptz DEFAULT NOW()
);

-- 🔹 Add unique and check constraints where logical
ALTER TABLE public.organizations
  ADD CONSTRAINT uq_organizations_slug UNIQUE (slug);

ALTER TABLE public.campaigns
  ADD CONSTRAINT uq_campaigns_name_per_org UNIQUE (organization_id, name);

ALTER TABLE public.contact
  ADD CONSTRAINT uq_contact_project_phone UNIQUE (project_id, phone);

ALTER TABLE public.enrollment
  ADD CONSTRAINT uq_enrollment_contact_campaign UNIQUE (contact_id, campaign_id);

ALTER TABLE public.organization_integrations
DROP CONSTRAINT IF EXISTS organization_integrations_integration_type_check;

ALTER TABLE public.organization_integrations
ADD CONSTRAINT organization_integrations_integration_type_check
CHECK (
  integration_type IN ('mandrill', 'slicktext', 'synthflow')
);

ALTER TABLE public.users
DROP CONSTRAINT IF EXISTS users_role_check;

ALTER TABLE public.users
ADD CONSTRAINT users_role_check
CHECK (
  role IN ('owner', 'admin', 'advisor', 'manager', 'agent', 'viewer')
);

COMMIT;


