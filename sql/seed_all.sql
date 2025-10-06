-- seed_all.sql — Minimal, idempotent data for dev_nexus
BEGIN;

-- Let policies treat this session like service_role (RLS bypass for seeding)
SELECT set_config('request.jwt.claims', '{"role":"service_role"}', true);

CREATE SCHEMA IF NOT EXISTS dev_nexus;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
DECLARE
  v_tenant     uuid := '11111111-1111-1111-1111-111111111111';
  v_project    uuid := '22222222-2222-2222-2222-222222222222';
  v_contact    uuid := '33333333-3333-3333-3333-333333333333';
  v_campaign   uuid := '44444444-4444-4444-4444-444444444444';
  v_enroll     uuid := '55555555-5555-5555-5555-555555555555';
  v_provider   uuid := '66666666-6666-6666-6666-666666666666';
  v_template   uuid := '77777777-7777-7777-7777-777777777777';
  v_variant    uuid := '88888888-8888-8888-8888-888888888888';
BEGIN
  -- 1) Tenancy
  INSERT INTO dev_nexus.tenant (id, name)
  VALUES (v_tenant, 'Acme U')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO dev_nexus.project (id, tenant_id, name)
  VALUES (v_project, v_tenant, 'Acme Recruiting')
  ON CONFLICT (id) DO NOTHING;

  -- 2) Contacts & Campaigns (both point to project)
  INSERT INTO dev_nexus.contact (id, project_id, full_name, email, phone)
  VALUES (v_contact, v_project, 'Casey Student', 'casey@example.com', '+15555550100')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO dev_nexus.campaign (id, project_id, name)
  VALUES (v_campaign, v_project, 'Fall Outreach')
  ON CONFLICT (id) DO NOTHING;

  -- 3) Enrollment & dependents (FKs to project/campaign/contact; outcomes/handoffs → enrollment)
  INSERT INTO dev_nexus.enrollment (id, project_id, campaign_id, contact_id, status)
  VALUES (v_enroll, v_project, v_campaign, v_contact, 'active')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO dev_nexus.outcome (id, enrollment_id, kind, notes)
  VALUES (gen_random_uuid(), v_enroll, 'interested', 'left VM')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO dev_nexus.handoff (id, enrollment_id, to_owner)
  VALUES (gen_random_uuid(), v_enroll, 'Admissions Counselor A')
  ON CONFLICT (id) DO NOTHING;

  -- 4) Providers (parent for message/event provider_id) and channel events
  INSERT INTO dev_nexus.providers (id, name)
  VALUES (v_provider, 'TestProvider')
  ON CONFLICT (id) DO NOTHING;

  -- (provider_ref, direction) must be unique on both tables; use distinct refs. :contentReference[oaicite:3]{index=3}
  INSERT INTO dev_nexus.message (id, project_id, provider_id, provider_ref, direction, payload, created_at)
  VALUES (gen_random_uuid(), v_project, v_provider, 'seed-msg-1', 'outbound', '{}'::jsonb, now() - interval '5 minutes')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO dev_nexus.event (id, project_id, provider_id, provider_ref, direction, type, data, created_at)
  VALUES (gen_random_uuid(), v_project, v_provider, 'seed-evt-1', 'outbound', 'classification', '{}'::jsonb, now() - interval '4 minutes')
  ON CONFLICT (id) DO NOTHING;

  -- 5) Templates (standalone per schema)
  INSERT INTO dev_nexus.template (id, name, description, body)
  VALUES (v_template, 'Welcome', 'Welcome message', jsonb_build_object('subject','Hi','text','Hello!'))
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO dev_nexus.template_variant (id, template_id, name, body)
  VALUES (v_variant, v_template, 'A', jsonb_build_object('text','Hello, {{name}}!'))
  ON CONFLICT (id) DO NOTHING;
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
ORDER BY 1;
