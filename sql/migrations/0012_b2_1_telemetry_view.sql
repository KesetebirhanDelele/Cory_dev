-- 0012_b2_1_telemetry_view.sql  (revised for dev_nexus core schema)
-- 1) Enum for view type tag (optional but handy)
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t
    JOIN pg_namespace n ON n.oid=t.typnamespace
    WHERE n.nspname='public' AND t.typname='telemetry_event_kind'
  ) THEN
    CREATE TYPE telemetry_event_kind AS ENUM ('message','event');
  END IF;
END $$;

-- 2) Unified read-only view (uses only columns that exist)
CREATE OR REPLACE VIEW telemetry_view AS
  SELECT
    m.created_at                                 AS occurred_at,
    m.id                                         AS event_pk,
    'message'::telemetry_event_kind              AS event_kind,
    m.project_id,
    m.provider_id,
    m.provider_ref,
    m.direction::text                            AS direction,
    m.payload                                    AS payload
  FROM dev_nexus.message m
UNION ALL
  SELECT
    e.created_at                                 AS occurred_at,
    e.id                                         AS event_pk,
    'event'::telemetry_event_kind                AS event_kind,
    e.project_id,
    e.provider_id,
    e.provider_ref,
    e.direction::text                            AS direction,
    jsonb_build_object('type', e.type, 'data', e.data) AS payload
  FROM dev_nexus.event e;

COMMENT ON VIEW telemetry_view IS 'Unified append-only telemetry from message/event tables.';

-- 3) Hard block any DML on the view (append via base tables only)
CREATE OR REPLACE FUNCTION telemetry_view_block_write()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'telemetry_view is append-only/read-only; % not allowed', TG_OP
    USING ERRCODE = '25P02';
END $$;

DROP TRIGGER IF EXISTS telemetry_view_no_insert ON telemetry_view;
DROP TRIGGER IF EXISTS telemetry_view_no_update ON telemetry_view;
DROP TRIGGER IF EXISTS telemetry_view_no_delete ON telemetry_view;

CREATE TRIGGER telemetry_view_no_insert
  INSTEAD OF INSERT ON telemetry_view
  FOR EACH ROW EXECUTE FUNCTION telemetry_view_block_write();

CREATE TRIGGER telemetry_view_no_update
  INSTEAD OF UPDATE ON telemetry_view
  FOR EACH ROW EXECUTE FUNCTION telemetry_view_block_write();

CREATE TRIGGER telemetry_view_no_delete
  INSTEAD OF DELETE ON telemetry_view
  FOR EACH ROW EXECUTE FUNCTION telemetry_view_block_write();

-- 4) Ordered timeline helper (time, then pk)
CREATE OR REPLACE FUNCTION telemetry_timeline(
  _project_id uuid,
  _since timestamptz DEFAULT '-infinity',
  _until timestamptz DEFAULT 'infinity',
  _limit int DEFAULT 1000
)
RETURNS TABLE (
  occurred_at timestamptz,
  event_pk uuid,
  event_kind telemetry_event_kind,
  project_id uuid,
  provider_id uuid,
  provider_ref text,
  direction text,
  payload jsonb
)
LANGUAGE sql STABLE AS $$
  SELECT *
  FROM telemetry_view
  WHERE project_id = _project_id
    AND occurred_at >= _since
    AND occurred_at <= _until
  ORDER BY occurred_at, event_pk
  LIMIT _limit
$$;