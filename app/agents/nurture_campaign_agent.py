# app/agents/nurture_campaign_agent.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from app.data.supabase_repo import SupabaseRepo

log = logging.getLogger("cory.nurture.agent")
log.setLevel(logging.INFO)


class NurtureCampaignAgent:
    """
    Ticket 7 Agent: Smart Nurture Campaigns

    Orchestrates a multi-step nurture sequence (e.g., 15 touchpoints)
    by scheduling personalized outbound emails for a given lead +
    nurture campaign in Supabase.

    High-level flow:
    1. Fetch all configured steps for the nurture campaign.
    2. For each step, compute a scheduled time using delay metadata.
    3. Insert rows into the scheduled-email table via SupabaseRepo.
    """

    def __init__(self) -> None:
        self.repo = SupabaseRepo()

    async def run_campaign(
        self,
        lead_id: str,
        campaign_id: str,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Main entry point to schedule all nurture campaign emails for a lead.

        Args:
            lead_id: The lead/contact identifier to nurture.
            campaign_id: The nurture_campaigns.id being executed.
            context: Optional metadata (e.g., registration, program, tags)
                     that can be embedded into templates.

        Returns:
            Dict with a simple status + count of steps scheduled, e.g.:
            {
                "status": "ok",
                "steps_scheduled": 15
            }
        """
        log.info("📨 Running nurture campaign for lead=%s campaign=%s", lead_id, campaign_id)

        # 1) Fetch nurture steps (expected ~15 rows)
        steps: List[Dict[str, Any]] = await self.repo.get_campaign_steps(campaign_id)

        if not steps:
            log.warning("No steps found for nurture campaign %s", campaign_id)
            return {"status": "no_steps", "steps_scheduled": 0}

        # 2) Schedule each email with its configured delay
        results: List[Any] = []
        base_time = datetime.utcnow()
        ctx = context or {}

        for index, step in enumerate(steps):
            # Default pattern: one message per day if delay not specified
            delay_minutes = step.get("delay_minutes", index * 1440)

            scheduled_for = base_time + timedelta(minutes=delay_minutes)

            payload = {
                "lead_id": lead_id,
                "campaign_id": campaign_id,
                "step_id": step["id"],
                "template_id": step["template_id"],
                "scheduled_for": scheduled_for.isoformat(),
                "context": ctx,
            }

            log.info(
                "⏳ Scheduling nurture email for lead=%s step_id=%s at %s",
                lead_id,
                step["id"],
                scheduled_for.isoformat(),
            )

            # This uses the helper you added in SupabaseRepo
            result = await self.repo.schedule_nurture_email(payload)
            results.append(result)

        log.info(
            "✅ Nurture campaign scheduled for lead=%s: %d steps",
            lead_id,
            len(results),
        )
        return {"status": "ok", "steps_scheduled": len(results)}
