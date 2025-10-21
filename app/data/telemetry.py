from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Database access abstraction (supports both get_pool and db_manager)
# -----------------------------------------------------------------------------

try:
    from .db import get_pool  # type: ignore
    _HAS_POOL = True
except Exception:
    _HAS_POOL = False


# -----------------------------------------------------------------------------
# Telemetry timeline API
# -----------------------------------------------------------------------------

async def get_telemetry_timeline(
    project_id: UUID,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """
    Retrieve telemetry events for a project.
    Uses either asyncpg pool or db_manager based on runtime configuration.
    """
    if _HAS_POOL:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT occurred_at, event_pk, event_kind::text, project_id,
                       provider_id, provider_ref, direction, payload
                FROM telemetry_timeline(
                    $1,
                    COALESCE($2, '-infinity'),
                    COALESCE($3, 'infinity'),
                    $4
                )
                """,
                project_id, since, until, limit,
            )
            return [dict(r) for r in rows]
    else:
        from .db import db_manager  # type: ignore
        query = """
            SELECT occurred_at, event_pk, event_kind::text, project_id,
                   provider_id, provider_ref, direction, payload
            FROM telemetry_timeline(
                $1,
                COALESCE($2, '-infinity'),
                COALESCE($3, 'infinity'),
                $4
            )
        """
        rows = await db_manager.execute_query(query, str(project_id), since, until, limit)
        return [dict(r) for r in rows]


# -----------------------------------------------------------------------------
# Policy / Guard Decision Logging (C2.1)
# -----------------------------------------------------------------------------

async def log_decision_to_audit(lead_id: str, channel: str, reason: str):
    """
    Record a policy-guard decision or violation.
    Logged in JSON format via the configured structured logger.

    Optionally, if a telemetry or audit table exists,
    this function can insert the event there.
    """
    logger.info(
        "PolicyDecision",
        extra={
            "lead_id": lead_id,
            "channel": channel,
            "decision": reason,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )

    # Optional: persist to telemetry / audit DB table
    try:
        if _HAS_POOL:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_log (lead_id, channel, reason, created_at)
                    VALUES ($1, $2, $3, NOW())
                    """,
                    lead_id, channel, reason,
                )
        else:
            from .db import db_manager  # type: ignore
            query = """
                INSERT INTO audit_log (lead_id, channel, reason, created_at)
                VALUES ($1, $2, $3, NOW())
            """
            await db_manager.execute_query(query, lead_id, channel, reason)
    except Exception as e:
        # Safe fail — do not interrupt guard or send workflows
        logger.warning("AuditInsertFailed", extra={"lead_id": lead_id, "error": str(e)})
