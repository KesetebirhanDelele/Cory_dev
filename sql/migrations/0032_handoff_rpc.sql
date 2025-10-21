-- Ensure we're in the right schema
SET search_path = public;

-- handoff_create
CREATE OR REPLACE FUNCTION public.handoff_create(
  p_organization_id uuid,
  p_title text,
  p_task_type text,
  p_source text DEFAULT 'system',
  p_source_key text DEFAULT NULL,
  p_lead_id uuid DEFAULT NULL,
  p_interaction_id uuid DEFAULT NULL,
  p_description text DEFAULT NULL,
  p_priority handoff_priority DEFAULT 'normal',
  p_assigned_to uuid DEFAULT NULL,
  p_metadata jsonb DEFAULT '{}'::jsonb,
  p_explicit_sla_due_at timestamptz DEFAULT NULL
)
RETURNS SETOF handoffs
LANGUAGE plpgsql
AS $$
DECLARE
  v_minutes int := COALESCE((
    CASE p_task_type
      WHEN 'escalation'    THEN 60
      WHEN 'callback'      THEN 1440
      WHEN 'manual_email'  THEN 720
      WHEN 'review_outcome'THEN 240
      ELSE 1440
    END
  ), 1440);
  v_sla_due timestamptz := COALESCE(p_explicit_sla_due_at, now() + make_interval(mins => v_minutes));
BEGIN
  RETURN QUERY
  WITH existing AS (
    SELECT * FROM handoffs
     WHERE organization_id = p_organization_id
       AND task_type = p_task_type
       AND COALESCE(lead_id, '00000000-0000-0000-0000-000000000000'::uuid) = COALESCE(p_lead_id, '00000000-0000-0000-0000-000000000000'::uuid)
       AND source = p_source
       AND COALESCE(source_key,'') = COALESCE(p_source_key,'')
       AND status IN ('open','in_progress')
     ORDER BY created_at ASC
     LIMIT 1
  ), ins AS (
    INSERT INTO handoffs (
      organization_id, lead_id, interaction_id, task_type, source, source_key,
      title, description, priority, status, assigned_to, sla_due_at, metadata
    )
    SELECT p_organization_id, p_lead_id, p_interaction_id, p_task_type, p_source, p_source_key,
           p_title, p_description, p_priority, 'open', p_assigned_to, v_sla_due, COALESCE(p_metadata,'{}'::jsonb)
    WHERE NOT EXISTS (SELECT 1 FROM existing)
    RETURNING *
  )
  SELECT * FROM ins
  UNION ALL
  SELECT * FROM existing;
END;
$$;

-- handoff_mark_first_response
CREATE OR REPLACE FUNCTION public.handoff_mark_first_response(
  p_handoff_id uuid
)
RETURNS SETOF handoffs
LANGUAGE sql
AS $$
  UPDATE handoffs
     SET first_response_at = COALESCE(first_response_at, now()),
         status = CASE WHEN status='open' THEN 'in_progress' ELSE status END
   WHERE id = p_handoff_id
   RETURNING *;
$$;

-- handoff_resolve
CREATE OR REPLACE FUNCTION public.handoff_resolve(
  p_handoff_id uuid,
  p_resolved_by uuid,
  p_resolution_note text,
  p_outcome_snapshot jsonb
)
RETURNS SETOF handoffs
LANGUAGE sql
AS $$
  UPDATE handoffs
     SET status = 'resolved',
         resolved_at = COALESCE(resolved_at, now()),
         resolved_by = COALESCE(resolved_by, p_resolved_by),
         resolution_note = COALESCE(resolution_note, p_resolution_note),
         outcome_snapshot = COALESCE(outcome_snapshot, '{}'::jsonb) || COALESCE(p_outcome_snapshot, '{}'::jsonb),
         re_resolve_count = CASE WHEN resolved_at IS NULL THEN re_resolve_count
                                 ELSE re_resolve_count + 1 END
   WHERE id = p_handoff_id
   RETURNING *;
$$;

-- 1) Deep merge helper
CREATE OR REPLACE FUNCTION public.jsonb_deep_merge(a jsonb, b jsonb)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  k text;
  v jsonb;
  res jsonb;
BEGIN
  IF a IS NULL THEN a := '{}'::jsonb; END IF;
  IF b IS NULL THEN RETURN a; END IF;

  -- If either side isn't an object, prefer right-hand side (b)
  IF jsonb_typeof(a) <> 'object' OR jsonb_typeof(b) <> 'object' THEN
    RETURN b;
  END IF;

  res := a;
  FOR k, v IN SELECT key, value FROM jsonb_each(b)
  LOOP
    IF res ? k THEN
      res := jsonb_set(res, ARRAY[k], public.jsonb_deep_merge(res->k, v), true);
    ELSE
      res := jsonb_set(res, ARRAY[k], v, true);
    END IF;
  END LOOP;
  RETURN res;
END
$$;

-- 2) Replace handoff_resolve to use deep merge and keep timestamps stable
CREATE OR REPLACE FUNCTION public.handoff_resolve(
  p_handoff_id uuid,
  p_resolved_by uuid,
  p_resolution_note text,
  p_outcome_snapshot jsonb
)
RETURNS SETOF handoffs
LANGUAGE sql
AS $$
  UPDATE handoffs
     SET status = 'resolved',
         resolved_at = COALESCE(resolved_at, now()),
         resolved_by = COALESCE(resolved_by, p_resolved_by),
         resolution_note = COALESCE(resolution_note, p_resolution_note),
         outcome_snapshot = public.jsonb_deep_merge(
             COALESCE(outcome_snapshot, '{}'::jsonb),
             COALESCE(p_outcome_snapshot, '{}'::jsonb)
         ),
         re_resolve_count = CASE WHEN resolved_at IS NULL THEN re_resolve_count
                                 ELSE re_resolve_count + 1 END
   WHERE id = p_handoff_id
   RETURNING *;
$$;
