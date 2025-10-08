# app/data/telemetry.py
from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime

# Your pool/connection helper lives here:
# - If app/data/db.py exposes `get_pool()`, use the first block.
# - If it exposes `db_manager.execute_query(...)`, use the second block and delete the first.

# --- Option A: asyncpg pool style -------------------------------------------
try:
    from .db import get_pool  # type: ignore
    _HAS_POOL = True
except Exception:
    _HAS_POOL = False

async def get_telemetry_timeline(
    project_id: UUID,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    if _HAS_POOL:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT occurred_at, event_pk, event_kind::text, project_id,
                       provider_id, provider_ref, direction, payload
                FROM telemetry_timeline($1, COALESCE($2, '-infinity'), COALESCE($3, 'infinity'), $4)
                """,
                project_id, since, until, limit,
            )
            return [dict(r) for r in rows]
    else:
        # --- Option B: db_manager style --------------------------------------
        from .db import db_manager  # type: ignore
        query = """
            SELECT occurred_at, event_pk, event_kind::text, project_id,
                   provider_id, provider_ref, direction, payload
            FROM telemetry_timeline($1, COALESCE($2, '-infinity'), COALESCE($3, 'infinity'), $4)
        """
        rows = await db_manager.execute_query(query, str(project_id), since, until, limit)
        return [dict(r) for r in rows]
