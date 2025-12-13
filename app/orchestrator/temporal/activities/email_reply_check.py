# app/orchestrator/temporal/activities/email_reply_check.py
from __future__ import annotations

from typing import Dict, Any

from temporalio import activity

from app.data.supabase_repo import SupabaseRepo


@activity.defn(name="email_reply_check")
async def email_reply_check(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check whether we have an inbound email reply for a given enrollment.

    Expected payload:
      {
        "enrollment_id": "enr-123",
        "lookback_minutes": 120,  # optional
      }

    Returns:
      {"has_reply": bool}
    """
    repo = SupabaseRepo()
    enrollment_id = payload["enrollment_id"]
    lookback = int(payload.get("lookback_minutes", 120))

    has_reply = await repo.has_email_reply_for_enrollment(
        enrollment_id=enrollment_id,
        lookback_minutes=lookback,
    )

    return {"has_reply": has_reply}
