# app/agents/reengagement_campaign_agent.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from app.data.supabase_repo import SupabaseRepo

log = logging.getLogger("cory.reengagement.agent")
log.setLevel(logging.INFO)


class ReengagementCampaignAgent:
    """
    Ticket 8 Agent:
    Schedules long-tail re-engagement touches (email/SMS/etc.) for dormant leads.
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
        Main entry point to schedule long-term re-engagement touches.
        """

        log.info(f"🔁 Running re-engagement campaign for lead={lead_id}")

        # 1. Fetch re-engagement steps (could be 10–20 touches)
        steps: List[Dict[str, Any]] = await self.repo.get_reengagement_steps(
            campaign_id
        )

        if not steps:
            log.warning(
                f"No re-engagement steps found for campaign {campaign_id}"
            )
            return {"status": "no_steps"}

        results: List[Dict[str, Any]] = []
        base_time = datetime.utcnow()

        for index, step in enumerate(steps):
            # Typical re-engagement is slow drip: default every 3 days
            delay_minutes = step.get(
                "delay_minutes",
                index * 3 * 24 * 60,  # 3 days per step by default
            )

            scheduled_for = base_time + timedelta(minutes=delay_minutes)

            payload = {
                "lead_id": lead_id,
                "campaign_id": campaign_id,
                "step_id": step["id"],
                "template_id": step["template_id"],
                "scheduled_for": scheduled_for.isoformat(),
                "context": context or {},
            }

            log.info(
                "📬 Scheduling re-engagement step %s for %s",
                step["id"],
                scheduled_for,
            )

            # ✅ Use the correct repo helper name
            result = await self.repo.schedule_reengagement_message(payload)
            results.append(result)

        return {
            "status": "ok",
            "steps_scheduled": len(results),
        }
