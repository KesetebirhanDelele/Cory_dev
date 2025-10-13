-- =============================================================================
-- Cory Admissions - Handoffs / Tasks core schema (Ticket B3.1)
-- Creates types, table, trigger, and indexes for SLA + outcome snapshots.
-- Safe to run multiple times (IF NOT EXISTS used where possible).
-- =============================================================================

BEGIN;

-- --- Extensions (for UUID + some GIN ops) -----------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS btree_gin;  -- helpful for some mixed GIN cases

-- --- Enums -------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'handoff_status') THEN
    CREATE TYPE handoff_status AS ENUM ('open','in_progress','resolved','cancelled');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'handoff_priority') THEN
    CREATE TYPE handoff_priority AS ENUM ('low','normal','high','urgent');
  END IF;
END$$;

-- --- Table -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS handoffs (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id   uuid NOT NULL,
  lead_id           uuid NULL,
  interaction_id    uuid NULL,

  task_type         text NOT NULL,                      -- 'escalation' | 'callback' | 'manual_email' | ...
  source            text NOT NULL DEFAULT 'system',     -- 'system' | '<integration>'
  source_key        text NULL,                          -- idempotency key within source

  title             text NOT NULL,
  description       text NULL,
  priority          handoff_priority NOT NULL DEFAULT 'normal',
  status            handoff_status NOT NULL DEFAULT 'open',

  assigned_to       uuid NULL,

  -- SLA / lifecycle
  sla_due_at        timestamptz NULL,
  first_response_at timestamptz NULL,
  resolved_at       timestamptz NULL,
  resolved_by       uuid NULL,
  resolution_note   text NULL,

  -- Outcome + arbitrary metadata
  outcome_snapshot  jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,

  -- Diagnostics
  re_resolve_count  integer NOT NULL DEFAULT 0,

  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

-- --- updated_at trigger ------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_handoffs_set_updated_at ON handoffs;
CREATE TRIGGER trg_handoffs_set_updated_at
BEFORE UPDATE ON handoffs
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- --- Indexes (filters, SLA queue, JSONB search) ------------------------------
-- Common filters
CREATE INDEX IF NOT EXISTS idx_handoffs_org_status
  ON handoffs (organization_id, status);

CREATE INDEX IF NOT EXISTS idx_handoffs_sla_due
  ON handoffs (sla_due_at);

CREATE INDEX IF NOT EXISTS idx_handoffs_lead_created
  ON handoffs (lead_id, created_at);

CREATE INDEX IF NOT EXISTS idx_handoffs_tasktype
  ON handoffs (task_type);

-- JSONB GIN (use default jsonb_ops for broad querying)
CREATE INDEX IF NOT EXISTS idx_handoffs_outcome_gin
  ON handoffs USING GIN (outcome_snapshot jsonb_ops);

CREATE INDEX IF NOT EXISTS idx_handoffs_metadata_gin
  ON handoffs USING GIN (metadata jsonb_ops);

-- --- Idempotency: only ONE open/in_progress per (org, type, lead, source, key)
-- We implement this with a PARTIAL UNIQUE INDEX (applies only while not resolved/cancelled).
-- COALESCE on nullable identity pieces to make the tuple comparable.
CREATE UNIQUE INDEX IF NOT EXISTS uq_open_handoff_identity
  ON handoffs (
    organization_id,
    task_type,
    COALESCE(lead_id, '00000000-0000-0000-0000-000000000000'::uuid),
    source,
    COALESCE(source_key, '')
  )
  WHERE status IN ('open','in_progress');

COMMIT;

-- =============================================================================
-- Optional: quick sanity queries
-- -- Find overdue open items
-- SELECT * FROM handoffs
--  WHERE status IN ('open','in_progress') AND sla_due_at < now()
--  ORDER BY sla_due_at ASC;
--
-- -- Resolve example (app code normally does this, shown here for reference)
-- UPDATE handoffs
--    SET status='resolved',
--        resolved_at = COALESCE(resolved_at, now()),
--        resolved_by = $1,             -- uuid
--        resolution_note = COALESCE(resolution_note, $2),
--        outcome_snapshot = outcome_snapshot || $3::jsonb,
--        re_resolve_count = CASE WHEN resolved_at IS NULL THEN re_resolve_count
--                                ELSE re_resolve_count + 1 END
--  WHERE id = $4                       -- uuid
-- RETURNING *;
-- =============================================================================
