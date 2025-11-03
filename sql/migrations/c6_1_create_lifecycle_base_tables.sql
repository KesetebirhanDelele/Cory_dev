-- ===============================================
-- 00xx_create_lifecycle_base_tables.sql
-- Create missing lead lifecycle tables
-- ===============================================

BEGIN;

-- =====================================================
-- 1. Nurture Campaigns
-- =====================================================
CREATE TABLE IF NOT EXISTS nurture_campaign (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenant(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  trigger_condition TEXT,              -- e.g. "low_engagement_7_days"
  schedule_definition JSONB DEFAULT '{}',  -- cadence rules
  template_variables JSONB DEFAULT '{}',   -- token variables
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nurture_campaign_tenant_active
  ON nurture_campaign(tenant_id, is_active);

-- =====================================================
-- 2. Re-Engagement Campaigns
-- =====================================================
CREATE TABLE IF NOT EXISTS reengagement_campaign (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenant(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  trigger_condition TEXT,              -- e.g. "contact_inactive_30_days"
  message_templates JSONB DEFAULT '{}',
  cadence_definition JSONB DEFAULT '{}',
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reengagement_campaign_tenant_active
  ON reengagement_campaign(tenant_id, is_active);

-- =====================================================
-- 3. Appointments
-- =====================================================
CREATE TABLE IF NOT EXISTS appointment (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  enrollment_id UUID REFERENCES enrollment(id) ON DELETE CASCADE,
  contact_id UUID REFERENCES contact(id) ON DELETE CASCADE,
  assigned_user UUID REFERENCES providers(id),
  appointment_time TIMESTAMPTZ NOT NULL,
  duration_minutes INTEGER DEFAULT 30 CHECK (duration_minutes BETWEEN 15 AND 120),
  status TEXT DEFAULT 'scheduled' CHECK (status IN ('scheduled','completed','cancelled','no_show','rescheduled')),
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_appointment_contact_enroll
  ON appointment(contact_id, enrollment_id);
CREATE INDEX IF NOT EXISTS idx_appointment_time_status
  ON appointment(appointment_time, status);

-- =====================================================
-- 4. Lead Campaign Steps
-- =====================================================
CREATE TABLE IF NOT EXISTS lead_campaign_step (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  enrollment_id UUID REFERENCES enrollment(id) ON DELETE CASCADE,
  campaign_id UUID REFERENCES campaign(id) ON DELETE CASCADE,
  step_name TEXT NOT NULL,
  step_order INTEGER NOT NULL,
  scheduled_at TIMESTAMPTZ,
  executed_at TIMESTAMPTZ,
  status TEXT DEFAULT 'pending'
    CHECK (status IN ('pending','in_progress','completed','failed','skipped')),
  action_type TEXT
    CHECK (action_type IN ('voice_call','send_sms','send_email','escalate_to_human','wait','custom')),
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lead_campaign_step_enroll_campaign
  ON lead_campaign_step(enrollment_id, campaign_id);

COMMIT;
