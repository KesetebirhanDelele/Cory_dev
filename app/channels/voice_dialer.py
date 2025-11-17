# app/channels/voice_dialer.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from app.data.db import (
    init_db_pool,
    fetch_due_actions,
    update_activity,
    insert_activity,
)
from providers.voice import place_call


async def run_voice_dialer() -> None:
    """
    Scan for due voice actions and initiate outbound calls via providers.voice.place_call.

    fetch_due_actions() is expected to return rows with at least:
        org_id, enrollment_id, campaign_id, current_step_id,
        next_channel, next_run_at, contact_phone, org_from_number.
    """
    # Ensure DB pool is ready
    await init_db_pool()

    now = datetime.now(timezone.utc)
    due_actions: List[Dict[str, Any]] = await fetch_due_actions()

    for row in due_actions:
        # This dialer only cares about voice actions
        if row.get("next_channel") != "voice":
            continue

        # Extra guard: only process if actually due
        next_run_at = row.get("next_run_at")
        if next_run_at and next_run_at > now:
            continue

        to_number = row.get("contact_phone")
        from_number = row.get("org_from_number")

        # If we don't have the phone numbers, record a failed activity and skip
        if not to_number or not from_number:
            await insert_activity(
                {
                    "org_id": row["org_id"],
                    "enrollment_id": row["enrollment_id"],
                    "campaign_id": row["campaign_id"],
                    "step_id": row.get("current_step_id"),
                    "attempt_no": 1,
                    "channel": "voice",
                    "status": "failed",
                    "error": "missing_to_or_from_number",
                    "scheduled_at": next_run_at,
                    "sent_at": now.isoformat(),
                }
            )
            continue

        # Create an activity row in "initiated" state
        activity = {
            "org_id": row["org_id"],
            "enrollment_id": row["enrollment_id"],
            "campaign_id": row["campaign_id"],
            "step_id": row.get("current_step_id"),
            "attempt_no": 1,
            "channel": "voice",
            "status": "initiated",
            "scheduled_at": next_run_at,
            "sent_at": now.isoformat(),
        }
        created_activity = await insert_activity(activity)
        activity_id = created_activity["id"]

        try:
            # Kick off the call. The third argument is contextual metadata
            # that the provider/agent can use (e.g. to build prompts, logs, etc.).
            provider_ref = await place_call(
                to_number,
                from_number,
                {
                    "org_id": row["org_id"],
                    "enrollment_id": row["enrollment_id"],
                    "activity_id": activity_id,
                },
            )

            await update_activity(
                activity_id,
                {
                    "status": "sent",
                    "provider_ref": provider_ref,
                },
            )
        except Exception as exc:
            # If the provider call fails, mark the activity as failed
            await update_activity(
                activity_id,
                {
                    "status": "failed",
                    "error": str(exc),
                },
            )
