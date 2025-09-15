-- ===== Seed Org, Contact, Campaign, Steps =====
-- Schema: dev_nexus

-- 1) ORG (idempotent)
INSERT INTO dev_nexus.organizations (name)
VALUES ('Colaberry')
ON CONFLICT (name) DO NOTHING;

-- 2) CONTACT (idempotent; adjust ON CONFLICT to your constraint set)
WITH o AS (
  SELECT id AS org_id
  FROM dev_nexus.organizations
  WHERE name = 'Colaberry'
  LIMIT 1
)
INSERT INTO dev_nexus.contacts (org_id, full_name, email, phone)
SELECT o.org_id, 'Daisy Example', 'daisy@example.com', '+13125153855'
FROM o
ON CONFLICT (org_id, email) DO NOTHING;

-- 3) CAMPAIGN (idempotent). NOTE: using a normal hyphen '-' in the name.
WITH o AS (
  SELECT id AS org_id
  FROM dev_nexus.organizations
  WHERE name = 'Colaberry'
  LIMIT 1
)
INSERT INTO dev_nexus.campaigns (org_id, name, description, overall_goal_prompt)
SELECT o.org_id,
       'New Lead - 4-Day VM follow-up',
       'Initial outreach with VM/no-answer retry policy for 4 days.',
       'Goal: connect live and book intro call'
FROM o
ON CONFLICT (org_id, name) DO NOTHING;

-- 4) STEP 1: initial voice call (idempotent)
WITH c AS (
  SELECT id AS campaign_id
  FROM dev_nexus.campaigns
  WHERE name = 'New Lead - 4-Day VM follow-up'
  AND org_id = (SELECT id FROM dev_nexus.organizations WHERE name='Colaberry' LIMIT 1)
  LIMIT 1
)
INSERT INTO dev_nexus.campaign_steps
  (campaign_id, order_id, channel, wait_before_ms, label, metadata)
SELECT c.campaign_id, 1, 'voice', 0, 'Initial call', '{}'::jsonb
FROM c
ON CONFLICT (campaign_id, order_id) DO NOTHING;

-- 5) STEP 2: follow-up email after 2 days (idempotent)
WITH c AS (
  SELECT id AS campaign_id
  FROM dev_nexus.campaigns
  WHERE name = 'New Lead - 4-Day VM follow-up'
  AND org_id = (SELECT id FROM dev_nexus.organizations WHERE name='Colaberry' LIMIT 1)
  LIMIT 1
)
INSERT INTO dev_nexus.campaign_steps
  (campaign_id, order_id, channel, wait_before_ms, label, metadata)
SELECT c.campaign_id, 2, 'email', 2*24*60*60*1000, 'Program overview email', '{}'::jsonb
FROM c
ON CONFLICT (campaign_id, order_id) DO NOTHING;

-- Optional: show what you created
SELECT 'org' AS kind, id, name FROM dev_nexus.organizations WHERE name='Colaberry'
UNION ALL
SELECT 'campaign' AS kind, id, name FROM dev_nexus.campaigns WHERE name='New Lead - 4-Day VM follow-up';

SELECT campaign_id, order_id, channel, wait_before_ms, label
FROM dev_nexus.campaign_steps s
JOIN dev_nexus.campaigns c ON c.id = s.campaign_id
WHERE c.name = 'New Lead - 4-Day VM follow-up'
ORDER BY order_id;
