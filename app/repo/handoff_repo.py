from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta
import asyncpg

class HandoffRepo:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # SLA policy could be made data-driven later; for now use task_type defaults
    SLA_DEFAULTS_MIN = {
        "escalation": 60,         # 1 hour
        "callback": 1440,         # 24 hours
        "manual_email": 720,      # 12 hours
        "review_outcome": 240,    # 4 hours
    }

    async def create(
        self,
        *,
        organization_id: UUID,
        title: str,
        task_type: str,
        source: str = "system",
        source_key: Optional[str] = None,
        lead_id: Optional[UUID] = None,
        interaction_id: Optional[UUID] = None,
        description: Optional[str] = None,
        priority: str = "normal",
        assigned_to: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
        explicit_sla_due_at: Optional[datetime] = None
    ) -> dict:
        """Create a handoff. If an equivalent OPEN task exists, return it (idempotent create)."""
        metadata = metadata or {}
        minutes = self.SLA_DEFAULTS_MIN.get(task_type, 1440)
        sla_due_at = explicit_sla_due_at or datetime.utcnow() + timedelta(minutes=minutes)

        sql = """
        WITH existing AS (
          SELECT * FROM handoffs
          WHERE organization_id=$1 AND task_type=$2 AND COALESCE(lead_id,'00000000-0000-0000-0000-000000000000') = COALESCE($3,'00000000-0000-0000-0000-000000000000')
            AND source=$4 AND COALESCE(source_key,'') = COALESCE($5,'')
            AND status IN ('open','in_progress')
          ORDER BY created_at ASC
          LIMIT 1
        ), ins AS (
          INSERT INTO handoffs (
            organization_id, lead_id, interaction_id, task_type, source, source_key,
            title, description, priority, status, assigned_to, sla_due_at, metadata
          )
          SELECT $1,$3,$6,$2,$4,$5,$7,$8,$9,'open',$10,$11,$12
          WHERE NOT EXISTS (SELECT 1 FROM existing)
          RETURNING *
        )
        SELECT * FROM ins
        UNION ALL
        SELECT * FROM existing;
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, organization_id, task_type, lead_id, source, source_key,
                                      interaction_id, title, description, priority, assigned_to, sla_due_at, metadata)
            return dict(row)

    async def mark_first_response(self, *, handoff_id: UUID) -> dict:
        sql = """
        UPDATE handoffs
        SET first_response_at = COALESCE(first_response_at, NOW()),
            status = CASE WHEN status='open' THEN 'in_progress' ELSE status END
        WHERE id=$1
        RETURNING *;
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, handoff_id)
            if not row:
                raise ValueError("Handoff not found")
            return dict(row)

    async def resolve(
        self,
        *,
        handoff_id: UUID,
        resolved_by: UUID,
        resolution_note: Optional[str],
        outcome_snapshot: Dict[str, Any]
    ) -> dict:
        """
        Resolve a handoff. Idempotent: if already resolved, do not change timestamps; do merge snapshot+note.
        """
        # Merge outcome snapshots: latest keys overwrite, track re_resolve_count
        sql = """
        UPDATE handoffs
        SET
          status = 'resolved',
          resolved_at = COALESCE(resolved_at, NOW()),
          resolved_by = COALESCE(resolved_by, $2),
          resolution_note = COALESCE(resolution_note, $3),
          outcome_snapshot = COALESCE(outcome_snapshot, '{}'::jsonb) || $4::jsonb,
          re_resolve_count = CASE WHEN resolved_at IS NULL THEN re_resolve_count
                                  ELSE re_resolve_count + 1 END
        WHERE id=$1
        RETURNING *;
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, handoff_id, resolved_by, resolution_note, outcome_snapshot)
            if not row:
                raise ValueError("Handoff not found")
            return dict(row)

    async def get(self, handoff_id: UUID) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM handoffs WHERE id=$1;", handoff_id)
            return dict(row) if row else None
