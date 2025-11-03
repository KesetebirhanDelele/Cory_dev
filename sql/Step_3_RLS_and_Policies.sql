-- ==========================================================
-- 🧩 CORY DATABASE REBUILD SCRIPT — STEP 3 (RLS & POLICIES)
-- ==========================================================
BEGIN;

-- ----------------------------------------------------------
-- Enable RLS
-- ----------------------------------------------------------
ALTER TABLE public.organizations          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.campaigns              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contact                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.enrollment             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.message                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.handoff                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outcome                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.template               ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.template_variant       ENABLE ROW LEVEL SECURITY;

-- ----------------------------------------------------------
-- Helper assumption: each authenticated user session provides
-- current_setting('app.current_organization') = org UUID
-- ----------------------------------------------------------

-- Organizations
CREATE POLICY org_owner_policy
  ON public.organizations
  USING (id::text = current_setting('app.current_organization', true));

-- Users
CREATE POLICY users_same_org
  ON public.users
  USING (organization_id::text = current_setting('app.current_organization', true));

-- Campaigns
CREATE POLICY campaigns_same_org
  ON public.campaigns
  USING (organization_id::text = current_setting('app.current_organization', true))
  WITH CHECK (organization_id::text = current_setting('app.current_organization', true));

-- Contacts
CREATE POLICY contacts_same_project
  ON public.contact
  USING (project_id IN (
      SELECT id FROM public.project
      WHERE tenant_id IN (
          SELECT tenant_id FROM public.project
          WHERE id::text = current_setting('app.current_project', true)
      )
  ));

-- Enrollments
CREATE POLICY enrollment_same_org
  ON public.enrollment
  USING (campaign_id IN (
      SELECT id FROM public.campaigns
      WHERE organization_id::text = current_setting('app.current_organization', true)
  ));

-- Messages
CREATE POLICY messages_same_project
  ON public.message
  USING (project_id::text = current_setting('app.current_project', true));

-- Events
CREATE POLICY events_same_project
  ON public.event
  USING (project_id::text = current_setting('app.current_project', true));

-- Outcomes
CREATE POLICY outcomes_same_project
  ON public.outcome
  USING (project_id::text = current_setting('app.current_project', true));

-- Handoffs
CREATE POLICY handoff_same_project
  ON public.handoff
  USING (project_id::text = current_setting('app.current_project', true));

-- Templates
CREATE POLICY templates_same_project
  ON public.template
  USING (project_id::text = current_setting('app.current_project', true));

-- Template Variants
CREATE POLICY template_variant_same_project
  ON public.template_variant
  USING (template_id IN (
      SELECT id FROM public.template
      WHERE project_id::text = current_setting('app.current_project', true)
  ));

COMMIT;
