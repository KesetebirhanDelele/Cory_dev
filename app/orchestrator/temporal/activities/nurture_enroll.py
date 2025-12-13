# app/orchestrator/temporal/activities/nurture_enroll.py
from __future__ import annotations

from typing import Any, Dict

import logging
from temporalio import activity

# Re-use the same asyncpg pool helper as other DB-using activities
from app.orchestrator.temporal.activities.rag import _get_pool

log = logging.getLogger("cory.activities.nurture_enroll")

"""
Nurture Enrollment Activity
---------------------------

This activity enrolls an existing enrollment into a *secondary* campaign
(e.g. Smart Nurture with 15 follow-up emails).

It writes to `campaign_enrollments`:

    CREATE TABLE public.campaign_enrollments (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        enrollment_id uuid NOT NULL REFERENCES public.enrollment(id) ON DELETE CASCADE,
        campaign_id uuid NOT NULL REFERENCES public.campaigns(id) ON DELETE CASCADE,
        campaign_type text NOT NULL DEFAULT 'lead',  -- lead | nurture | reengagement
        tier text DEFAULT 'tier1',
        is_active boolean DEFAULT TRUE,
        created_at timestamptz DEFAULT now(),
        updated_at timestamptz DEFAULT now(),
        CONSTRAINT uq_campaign_enrollment
            UNIQUE (enrollment_id, campaign_id, campaign_type)
    );

Usage (from a workflow, for example MissedCallFollowupWorkflow):

    await workflow.execute_activity(
        nurture_enroll,
        args=[{
            "enrollment_id": enrollment_id,
            # Smart Nurture campaign UUID (configured in DB or settings)
            "campaign_id": SMART_NURTURE_CAMPAIGN_ID,
            # Optional overrides:
            # "campaign_type": "nurture",
            # "tier": "tier1",
        }],
        start_to_close_timeout=timedelta(seconds=30),
    )
"""


@activity.defn(name="nurture_enroll")
async def nurture_enroll(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enroll an existing enrollment into a nurture (or other secondary) campaign.

    Expected args:
        {
            "enrollment_id": str,          # required
            "campaign_id": str,            # required (the nurture campaign ID)
            "campaign_type": str = "nurture",
            "tier": str = "tier1",
        }

    Behavior:
      - INSERT into campaign_enrollments
      - ON CONFLICT (enrollment_id, campaign_id, campaign_type):
            set is_active = TRUE and bump updated_at
      - Returns a summary dict for logging / debugging.
    """

    enrollment_id = args.get("enrollment_id")
    campaign_id = args.get("campaign_id") or args.get("nurture_campaign_id")
    campaign_type = args.get("campaign_type") or "nurture"
    tier = args.get("tier") or "tier1"

    if not enrollment_id:
        raise activity.ApplicationError(
            "nurture_enroll: missing enrollment_id",
            non_retryable=True,
        )
    if not campaign_id:
        raise activity.ApplicationError(
            "nurture_enroll: missing campaign_id (nurture campaign)",
            non_retryable=True,
        )

    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Idempotent upsert into campaign_enrollments
        await conn.execute(
            """
            INSERT INTO campaign_enrollments (
                enrollment_id,
                campaign_id,
                campaign_type,
                tier
            )
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (enrollment_id, campaign_id, campaign_type)
            DO UPDATE SET
                is_active = TRUE,
                updated_at = now();
            """,
            enrollment_id,
            campaign_id,
            campaign_type,
            tier,
        )

    log.info(
        "nurture_enroll: enrollment_id=%s enrolled into campaign_id=%s "
        "campaign_type=%s tier=%s",
        enrollment_id,
        campaign_id,
        campaign_type,
        tier,
    )

    return {
        "enrollment_id": enrollment_id,
        "campaign_id": campaign_id,
        "campaign_type": campaign_type,
        "tier": tier,
        "status": "enrolled",
    }
