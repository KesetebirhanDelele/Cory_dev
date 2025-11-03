-- ===============================================
-- 00xx_lead_lifecycle.sql
-- Lead Lifecycle Schema Expansion
-- ===============================================

BEGIN;

-- =====================================================
-- 1. Extend registrations table
-- =====================================================
ALTER TABLE registrations
ADD COLUMN IF NOT EXISTS lead_id UUID REFERENCES leads(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS current_stage TEXT,
ADD COLUMN IF NOT EXISTS last_campaign_id UUID REFERENCES campaigns(id),
ADD COLUMN IF NOT EXISTS last_nurture_campaign_id UUID REFERENCES nurture_campaigns(id),
ADD COLUMN IF NOT EXISTS last_reengagement_campaign_id UUID REFERENCES reengagement_campaigns(id),
ADD COLUMN IF NOT EXISTS appointment_id UUID REFERENCES appointments(id),
ADD COLUMN IF NOT EXISTS last_interacted_at TIMESTAMPTZ DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_registrations_lead_id ON registrations(lead_id);
CREATE INDEX IF NOT EXISTS idx_registrations_appointment_id ON registrations(appointment_id);

-- =====================================================
-- 2. Campaign Enrollments Extension
-- =====================================================
ALTER TABLE campaign_enrollments
ADD COLUMN IF NOT EXISTS campaign_type TEXT DEFAULT 'standard' CHECK (campaign_type IN ('standard', 'nurture', 'reengagement')),
ADD COLUMN IF NOT EXISTS campaign_tier TEXT DEFAULT 'primary' CHECK (campaign_tier IN ('primary', 'secondary', 'tertiary'));

-- =====================================================
-- 3. Lead Campaign Steps
-- =====================================================
CREATE TABLE IF NOT EXISTS lead_campaign_steps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  registration_id UUID REFERENCES registrations(id) ON DELETE CASCADE,
  campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
  step_name TEXT NOT NULL,
  step_order INTEGER NOT NULL,
  scheduled_at TIMESTAMPTZ,
  executed_at TIMESTAMPTZ,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'failed', 'skipped')),
  action_type TEXT CHECK (action_type IN ('voice_call', 'send_sms', 'send_email', 'escalate_to_human', 'wait', 'custom')),
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_lead_campaign_steps_reg_campaign ON lead_campaign_steps(registration_id, campaign_id);

-- =====================================================
-- 4. Nurture Campaigns
-- =====================================================
CREATE TABLE IF NOT EXISTS nurture_campaigns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  trigger_condition TEXT, -- e.g. "low_engagement_7_days"
  schedule_definition JSONB DEFAULT '{}', -- cadence/timing definition
  template_variables JSONB DEFAULT '{}',
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_nurture_campaigns_org_active ON nurture_campaigns(organization_id, is_active);

-- =====================================================
-- 5. Re-Engagement Campaigns
-- =====================================================
CREATE TABLE IF NOT EXISTS reengagement_campaigns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  trigger_condition TEXT, -- e.g. "lead_inactive_30_days"
  message_templates JSONB DEFAULT '{}',
  cadence_definition JSONB DEFAULT '{}',
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_reengagement_campaigns_org_active ON reengagement_campaigns(organization_id, is_active);

-- =====================================================
-- 6. Appointments
-- =====================================================
CREATE TABLE IF NOT EXISTS appointments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  registration_id UUID REFERENCES registrations(id) ON DELETE CASCADE,
  lead_id UUID REFERENCES leads(id) ON DELETE CASCADE,
  scheduled_with UUID REFERENCES users(id),
  appointment_time TIMESTAMPTZ NOT NULL,
  duration_minutes INTEGER DEFAULT 30 CHECK (duration_minutes BETWEEN 15 AND 120),
  status TEXT DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'completed', 'cancelled', 'no_show', 'rescheduled')),
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_appointments_lead_reg ON appointments(lead_id, registration_id);
CREATE INDEX idx_appointments_time_status ON appointments(appointment_time, status);

-- =====================================================
-- 7. Foreign Key Integrity
-- =====================================================
ALTER TABLE lead_campaign_steps
  ADD CONSTRAINT fk_lead_campaign_steps_reg FOREIGN KEY (registration_id) REFERENCES registrations(id) ON DELETE CASCADE;

-- =====================================================
-- 8. Example Seed Data (for /seeding)
-- =====================================================
INSERT INTO nurture_campaigns (organization_id, name, description, trigger_condition)
SELECT id, 'Low Engagement Drip', 'Follow-up for leads inactive >7 days', 'low_engagement_7_days'
FROM organizations LIMIT 1;

INSERT INTO reengagement_campaigns (organization_id, name, description, trigger_condition)
SELECT id, 'Reactivation Outreach', 'Re-engage leads inactive >30 days', 'lead_inactive_30_days'
FROM organizations LIMIT 1;

COMMIT;
