-- ==========================================================
-- 🧩 CORY DATABASE REBUILD SCRIPT — STEP 2 (Index + Constraints)
-- ==========================================================
BEGIN;

-- 🔹 Common lookup indexes
CREATE INDEX idx_campaigns_org_active       ON public.campaigns(organization_id, is_active);
CREATE INDEX idx_campaigns_name             ON public.campaigns(name);

CREATE INDEX idx_contacts_project           ON public.contact(project_id);
CREATE INDEX idx_contacts_phone_email       ON public.contact(phone, email);

-- Optional: Indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_contact_first_name ON public.contact(first_name);
CREATE INDEX IF NOT EXISTS idx_contact_email ON public.contact(email);
CREATE INDEX IF NOT EXISTS idx_contact_project_id ON public.contact(project_id);

CREATE INDEX idx_enrollment_project_campaign ON public.enrollment(project_id, campaign_id);
CREATE INDEX idx_enrollment_contact          ON public.enrollment(contact_id);

CREATE INDEX idx_messages_enrollment        ON public.message(enrollment_id);
CREATE INDEX idx_messages_project_channel   ON public.message(project_id, channel);

CREATE INDEX idx_events_enrollment          ON public.event(enrollment_id);
CREATE INDEX idx_events_project_type        ON public.event(project_id, event_type);

CREATE INDEX idx_handoff_project_status     ON public.handoff(project_id, status);
CREATE INDEX idx_handoff_enrollment         ON public.handoff(enrollment_id);

CREATE INDEX idx_outcome_project_enrollment ON public.outcome(project_id, enrollment_id);
CREATE INDEX idx_outcome_kind_value         ON public.outcome(kind, value);

CREATE INDEX idx_template_project           ON public.template(project_id);
CREATE INDEX idx_template_variant_template  ON public.template_variant(template_id);

CREATE INDEX idx_users_org_role             ON public.users(organization_id, role);

-- 🔹 Add unique and check constraints where logical
ALTER TABLE public.organizations
  ADD CONSTRAINT uq_organizations_slug UNIQUE (slug);

ALTER TABLE public.campaigns
  ADD CONSTRAINT uq_campaigns_name_per_org UNIQUE (organization_id, name);

ALTER TABLE public.contact
  ADD CONSTRAINT uq_contact_project_phone UNIQUE (project_id, phone);

ALTER TABLE public.enrollment
  ADD CONSTRAINT uq_enrollment_contact_campaign UNIQUE (contact_id, campaign_id);

-- ==============================================================
-- 🎟️ Ticket 1 — STEP 2 : Indexes and Constraints Only
-- ==============================================================

BEGIN;

-- --------------------------------------------------------------
-- 🔗 ENROLLMENT CONSTRAINTS + INDEXES
-- --------------------------------------------------------------

-- add unique constraint for lifecycle join key
ALTER TABLE public.enrollment
  ADD CONSTRAINT uq_enrollment_registration_id UNIQUE (registration_id);

-- foreign key to appointments
ALTER TABLE public.enrollment
  ADD CONSTRAINT fk_enrollment_appointment
  FOREIGN KEY (appointment_id)
  REFERENCES public.appointments(id)
  ON DELETE SET NULL;

-- index on registration_id for fast joins
CREATE INDEX IF NOT EXISTS idx_enrollment_registration_id
  ON public.enrollment(registration_id);

-- --------------------------------------------------------------
-- 🔗 APPOINTMENTS INDEXES
-- --------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_appointments_registration_id
  ON public.appointments(registration_id);

CREATE INDEX IF NOT EXISTS idx_appointments_lead_id
  ON public.appointments(lead_id);

-- --------------------------------------------------------------
-- 🔗 LEAD CAMPAIGN STEPS INDEX + FK
-- --------------------------------------------------------------
ALTER TABLE public.lead_campaign_steps
  ADD CONSTRAINT fk_lead_steps_registration
  FOREIGN KEY (registration_id)
  REFERENCES public.enrollment(registration_id)
  ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_lead_campaign_steps_registration
  ON public.lead_campaign_steps(registration_id);

-- --------------------------------------------------------------
-- 🔗 NURTURE CAMPAIGNS FK + TRIGGER
-- --------------------------------------------------------------
ALTER TABLE public.nurture_campaigns
  ADD CONSTRAINT fk_nurture_registration
  FOREIGN KEY (registration_id)
  REFERENCES public.enrollment(registration_id)
  ON DELETE SET NULL;

-- --------------------------------------------------------------
-- 🔗 REENGAGEMENT CAMPAIGNS FK + TRIGGER
-- --------------------------------------------------------------
ALTER TABLE public.reengagement_campaigns
  ADD CONSTRAINT fk_reengage_registration
  FOREIGN KEY (registration_id)
  REFERENCES public.enrollment(registration_id)
  ON DELETE SET NULL;

ALTER TABLE public.enrollment
  ADD CONSTRAINT fk_enrollment_appointment
  FOREIGN KEY (appointment_id)
  REFERENCES public.appointments(id)
  ON DELETE SET NULL;

ALTER TABLE public.enrollment
  ADD COLUMN IF NOT EXISTS registration_id uuid DEFAULT gen_random_uuid(),
  ADD CONSTRAINT uq_enrollment_registration_id UNIQUE (registration_id);

COMMIT;
