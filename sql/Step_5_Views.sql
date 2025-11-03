-- ==========================================================
-- 🧩 CORY DATABASE REBUILD SCRIPT — STEP 5 (Views)
-- ==========================================================
BEGIN;

-- ----------------------------------------------------------
-- 1️⃣  v_campaign_performance
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW public.v_campaign_performance AS
SELECT
  cm.campaign_id,
  c.name AS campaign_name,
  c.organization_id,
  c.is_active,
  cm.appointments_scheduled,
  cm.calls_made,
  cm.conversions,
  cm.conversion_rate,
  cm.emails_sent,
  cm.leads_processed,
  cm.opt_outs,
  cm.responses_received,
  cm.sms_sent,
  cm.date AS metric_date,
  cm.created_at AS metric_created_at
FROM public.campaign_metrics cm
JOIN public.campaigns c ON c.id = cm.campaign_id;

-- ----------------------------------------------------------
-- 2️⃣  v_campaign_activity_summary
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW public.v_campaign_activity_summary AS
SELECT
  campaign_id,
  channel,
  status,
  COUNT(*)::bigint AS total
FROM public.campaign_activity
GROUP BY campaign_id, channel, status;

-- ----------------------------------------------------------
-- 3️⃣  v_due_actions
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW public.v_due_actions AS
SELECT
  a.id AS activity_id,
  a.campaign_id,
  c.name AS campaign_name,
  a.channel,
  e.contact_id,
  a.enrollment_id,
  coalesce(ct.email, '') AS email,
  coalesce(ct.phone, '') AS phone,
  concat_ws(' ', ct.first_name, ct.last_name) AS full_name,
  a.step_id,
  s.name AS step_name,
  s.action AS step_action,
  s.step_order,
  a.due_at,
  e.project_id
FROM public.campaign_activity a
LEFT JOIN public.enrollment e ON e.id = a.enrollment_id
LEFT JOIN public.campaigns c ON c.id = a.campaign_id
LEFT JOIN public.contact ct ON ct.id = e.contact_id
LEFT JOIN public.campaign_step s ON s.id = a.step_id
WHERE a.status = 'pending' AND a.due_at <= NOW();

-- ----------------------------------------------------------
-- 4️⃣  v_due_sms_followups
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW public.v_due_sms_followups AS
SELECT
  v.activity_id,
  v.campaign_id,
  v.campaign_name,
  v.channel,
  v.contact_id,
  v.enrollment_id,
  v.email,
  v.phone,
  v.full_name,
  v.step_id,
  v.step_name,
  v.step_action,
  v.step_order,
  v.due_at,
  v.project_id
FROM public.v_due_actions v
WHERE v.channel = 'sms';

-- ----------------------------------------------------------
-- 5️⃣  v_lead_engagement_summary
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW public.v_lead_engagement_summary AS
SELECT
  l.id AS lead_id,
  l.name AS lead_name,
  l.email,
  l.phone,
  l.status AS lead_status,
  l.organization_id,
  l.source,
  l.interest,
  MAX(i.created_at) AS last_interaction_at,
  COUNT(i.id)::bigint AS total_interactions,
  COUNT(c.id)::bigint AS total_classifications,
  jsonb_object_agg(c.label, c.confidence) AS label_summary
FROM public.leads l
LEFT JOIN public.interactions i ON i.lead_id = l.id
LEFT JOIN public.classifications c ON c.lead_id = l.id
GROUP BY l.id;

-- ----------------------------------------------------------
-- 6️⃣  v_variant_attribution
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW public.v_variant_attribution AS
SELECT
  i.channel,
  i.step_id::text AS variant_id,
  COUNT(*) FILTER (WHERE i.delivery_status = 'delivered') AS delivered,
  COUNT(*) FILTER (WHERE i.delivery_status = 'failed') AS failed,
  COUNT(*) AS total_sent,
  ROUND(100.0 * COUNT(*) FILTER (WHERE i.delivery_status = 'delivered') / NULLIF(COUNT(*), 0), 2) AS delivery_rate
FROM public.interactions i
GROUP BY i.channel, i.step_id;

COMMIT;
