-- ==============================================================
-- 🧪 CORY LEAD LIFECYCLE SEED VERIFICATION
-- ==============================================================

-- --------------------------------------------------------------
-- 1️⃣ Check Enrollment Relationships
-- --------------------------------------------------------------
SELECT 
  e.id AS enrollment_id,
  e.registration_id,
  e.status,
  e.campaign_type,
  e.campaign_tier,
  p.name AS project_name,
  c.name AS campaign_name,
  l.name AS lead_name,
  a.id AS appointment_id
FROM public.enrollment e
LEFT JOIN public.project p ON e.project_id = p.id
LEFT JOIN public.campaigns c ON e.campaign_id = c.id
LEFT JOIN public.leads l ON e.contact_id = l.id
LEFT JOIN public.appointments a ON e.appointment_id = a.id
ORDER BY e.created_at DESC;

-- --------------------------------------------------------------
-- 2️⃣ Verify Appointment Linkage
-- --------------------------------------------------------------
SELECT 
  a.id AS appointment_id,
  a.registration_id,
  l.name AS lead_name,
  c.name AS campaign_name,
  p.name AS project_name,
  a.scheduled_for,
  a.notes
FROM public.appointments a
LEFT JOIN public.leads l ON a.lead_id = l.id
LEFT JOIN public.campaigns c ON a.campaign_id = c.id
LEFT JOIN public.project p ON a.project_id = p.id
ORDER BY a.scheduled_for;

-- --------------------------------------------------------------
-- 3️⃣ Confirm Lead Campaign Steps Progression
-- --------------------------------------------------------------
SELECT 
  s.registration_id,
  s.step_order,
  s.step_name,
  s.step_type,
  s.status,
  s.metadata
FROM public.lead_campaign_steps s
WHERE s.registration_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
ORDER BY s.step_order;

-- --------------------------------------------------------------
-- 4️⃣ Check Nurture Campaign Association
-- --------------------------------------------------------------
SELECT 
  n.id AS nurture_campaign_id,
  n.name,
  n.goal,
  n.registration_id,
  e.id AS enrollment_id,
  o.name AS org_name
FROM public.nurture_campaigns n
LEFT JOIN public.enrollment e ON n.registration_id = e.registration_id
LEFT JOIN public.organizations o ON n.organization_id = o.id;

-- --------------------------------------------------------------
-- 5️⃣ Check Re-engagement Campaign Association
-- --------------------------------------------------------------
SELECT 
  r.id AS reengagement_campaign_id,
  r.name,
  r.trigger_condition,
  r.registration_id,
  e.id AS enrollment_id,
  o.name AS org_name
FROM public.reengagement_campaigns r
LEFT JOIN public.enrollment e ON r.registration_id = e.registration_id
LEFT JOIN public.organizations o ON r.organization_id = o.id;

-- --------------------------------------------------------------
-- 6️⃣ Quick Integrity Summary (counts)
-- --------------------------------------------------------------
SELECT 
  (SELECT COUNT(*) FROM public.enrollment) AS enrollments,
  (SELECT COUNT(*) FROM public.lead_campaign_steps) AS steps,
  (SELECT COUNT(*) FROM public.appointments) AS appointments,
  (SELECT COUNT(*) FROM public.nurture_campaigns) AS nurture_campaigns,
  (SELECT COUNT(*) FROM public.reengagement_campaigns) AS reengagement_campaigns;
