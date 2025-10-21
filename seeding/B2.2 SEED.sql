-- ============================================
-- B2.2 SEED SCRIPT (schema: dev_nexus)
-- Creates tenant → project → campaign and 4 enrollments:
--   E1 -> delivered
--   E2 -> policy_denied
--   E3 -> timeout (no_answer)
--   E4 -> failed
-- Uses a session tag via set_config/current_setting.
-- ============================================

-- 0) Create a unique tag for this run and store it in the session
SELECT set_config('b22.tag', 'b22_' || substr(gen_random_uuid()::text, 1, 8), true);

BEGIN;

-- 1) tenant -> 2) project -> 3) campaign
WITH seed AS (
  SELECT current_setting('b22.tag', true) AS tag
),
t AS (
  INSERT INTO dev_nexus.tenant (name)
  SELECT seed.tag || '_tenant' FROM seed
  RETURNING id AS tenant_id
),
p AS (
  INSERT INTO dev_nexus.project (name, tenant_id)
  SELECT seed.tag || '_project', t.tenant_id
  FROM seed, t
  RETURNING id AS project_id
),
c AS (
  INSERT INTO dev_nexus.campaign (project_id, name)
  SELECT p.project_id, seed.tag || '_campaign'
  FROM p, seed
  RETURNING id AS campaign_id
)
SELECT 1;

-- ========== E1 -> delivered (completed) ==========
WITH seed AS (SELECT current_setting('b22.tag', true) AS tag),
p AS (SELECT id AS project_id FROM dev_nexus.project ORDER BY created_at DESC LIMIT 1),
c AS (SELECT id AS campaign_id FROM dev_nexus.campaign ORDER BY created_at DESC LIMIT 1),
ct AS (
  INSERT INTO dev_nexus.contact(project_id, full_name, email)
  SELECT p.project_id, 'B22 User Delivered', seed.tag || '_deliv@example.com'
  FROM p, seed
  RETURNING id, project_id
),
e AS (
  INSERT INTO dev_nexus.enrollment(project_id, campaign_id, contact_id)
  SELECT ct.project_id, c.campaign_id, ct.id
  FROM ct, c
  RETURNING id AS enrollment_id, campaign_id, contact_id
)
INSERT INTO dev_nexus.campaign_activity(
  enrollment_id, campaign_id, contact_id, channel, status, result_summary, created_at, completed_at
)
SELECT e.enrollment_id, e.campaign_id, e.contact_id,
       'sms', 'completed', 'completed', now(), now()
FROM e;

-- ========== E2 -> policy_denied ==========
WITH seed AS (SELECT current_setting('b22.tag', true) AS tag),
p AS (SELECT id AS project_id FROM dev_nexus.project ORDER BY created_at DESC LIMIT 1),
c AS (SELECT id AS campaign_id FROM dev_nexus.campaign ORDER BY created_at DESC LIMIT 1),
ct AS (
  INSERT INTO dev_nexus.contact(project_id, full_name, email)
  SELECT p.project_id, 'B22 User Policy', seed.tag || '_policy@example.com'
  FROM p, seed
  RETURNING id, project_id
),
e AS (
  INSERT INTO dev_nexus.enrollment(project_id, campaign_id, contact_id)
  SELECT ct.project_id, c.campaign_id, ct.id
  FROM ct, c
  RETURNING id AS enrollment_id, campaign_id, contact_id
)
INSERT INTO dev_nexus.campaign_activity(
  enrollment_id, campaign_id, contact_id, channel, status, result_summary, result_payload, created_at
)
SELECT e.enrollment_id, e.campaign_id, e.contact_id,
       'email', 'in_progress', 'in_progress', '{"policy_denied": true}'::jsonb, now()
FROM e;

-- ========== E3 -> timeout (no_answer) ==========
WITH seed AS (SELECT current_setting('b22.tag', true) AS tag),
p AS (SELECT id AS project_id FROM dev_nexus.project ORDER BY created_at DESC LIMIT 1),
c AS (SELECT id AS campaign_id FROM dev_nexus.campaign ORDER BY created_at DESC LIMIT 1),
ct AS (
  INSERT INTO dev_nexus.contact(project_id, full_name, email)
  SELECT p.project_id, 'B22 User Timeout', seed.tag || '_timeout@example.com'
  FROM p, seed
  RETURNING id, project_id
),
e AS (
  INSERT INTO dev_nexus.enrollment(project_id, campaign_id, contact_id)
  SELECT ct.project_id, c.campaign_id, ct.id
  FROM ct, c
  RETURNING id AS enrollment_id, campaign_id, contact_id
)
INSERT INTO dev_nexus.campaign_activity(
  enrollment_id, campaign_id, contact_id, channel, status, result_summary, created_at
)
SELECT e.enrollment_id, e.campaign_id, e.contact_id,
       'voice', 'failed', 'no_answer', now()
FROM e;

-- ========== E4 -> failed ==========
WITH seed AS (SELECT current_setting('b22.tag', true) AS tag),
p AS (SELECT id AS project_id FROM dev_nexus.project ORDER BY created_at DESC LIMIT 1),
c AS (SELECT id AS campaign_id FROM dev_nexus.campaign ORDER BY created_at DESC LIMIT 1),
ct AS (
  INSERT INTO dev_nexus.contact(project_id, full_name, email)
  SELECT p.project_id, 'B22 User Failed', seed.tag || '_failed@example.com'
  FROM p, seed
  RETURNING id, project_id
),
e AS (
  INSERT INTO dev_nexus.enrollment(project_id, campaign_id, contact_id)
  SELECT ct.project_id, c.campaign_id, ct.id
  FROM ct, c
  RETURNING id AS enrollment_id, campaign_id, contact_id
)
INSERT INTO dev_nexus.campaign_activity(
  enrollment_id, campaign_id, contact_id, channel, status, result_summary, created_at
)
SELECT e.enrollment_id, e.campaign_id, e.contact_id,
       'sms', 'failed', 'failed', now()
FROM e;

COMMIT;

-- 5) Refresh MV
SELECT public.rpc_refresh_enrollment_state_snapshot();

-- 6) Inspect results for this seed batch (should see 4 rows)
WITH seed AS (SELECT current_setting('b22.tag', true) AS tag)
SELECT es.enrollment_id,
       es.delivery_state,
       c.email,
       es.last_event_at
FROM dev_nexus.enrollment_state_snapshot es
JOIN dev_nexus.enrollment e ON e.id = es.enrollment_id
JOIN dev_nexus.contact    c ON c.id = e.contact_id
WHERE c.email LIKE (SELECT tag || '%' FROM seed)
ORDER BY c.email;

-- Optional: counts per state for this seed batch
WITH seed AS (SELECT current_setting('b22.tag', true) AS tag)
SELECT es.delivery_state, count(*)
FROM dev_nexus.enrollment_state_snapshot es
JOIN dev_nexus.enrollment e ON e.id = es.enrollment_id
JOIN dev_nexus.contact    c ON c.id = e.contact_id
WHERE c.email LIKE (SELECT tag || '%' FROM seed)
GROUP BY es.delivery_state
ORDER BY 1;

-- TEST-ONLY: auto-create tenant if project.tenant_id doesn't exist
-- Safe for dev/test; drop after tests if you prefer.

begin;

-- Function
create or replace function dev_nexus._test_autocreate_tenant_for_project()
returns trigger
language plpgsql
as $$
declare
  _name text := coalesce(new.name, 'auto_tenant');
begin
  if new.tenant_id is null then
    -- No tenant provided -> create one and assign
    insert into dev_nexus.tenant(name) values (_name || '_tenant')
    returning id into new.tenant_id;
  elsif not exists (select 1 from dev_nexus.tenant t where t.id = new.tenant_id) then
    -- Tenant provided but doesn't exist -> create with exact id to satisfy FK
    insert into dev_nexus.tenant(id, name)
    values (new.tenant_id, _name || '_tenant');
  end if;

  return new;
end;
$$;

-- Trigger
drop trigger if exists trg_test_autocreate_tenant on dev_nexus.project;
create trigger trg_test_autocreate_tenant
before insert on dev_nexus.project
for each row
execute function dev_nexus._test_autocreate_tenant_for_project();

commit;
