# app/orchestrator/temporal/workflows/nurture_campaign_workflow.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional

from temporalio import workflow, activity

from app.agents.nurture_campaign_agent import NurtureCampaignAgent


# ===============================================================
# Workflow Input Model
# ===============================================================

@dataclass
class NurtureCampaignInput:
    """
    Payload for starting a Smart Nurture Campaign workflow.

    Attributes:
        lead_id: The lead/contact we’re nurturing.
        campaign_id: ID of the nurture_campaigns row to execute.
        context: Optional extra context (program, registration, tags, etc.)
    """
    lead_id: str
    campaign_id: str
    context: Optional[Dict[str, Any]] = None


# ===============================================================
# Activity Wrapper
# ===============================================================

@activity.defn
async def run_nurture_campaign_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runs NurtureCampaignAgent inside a Temporal activity so that
    DB / network IO is off the workflow thread.
    """
    agent = NurtureCampaignAgent()
    return await agent.run_campaign(
        lead_id=payload["lead_id"],
        campaign_id=payload["campaign_id"],
        context=payload.get("context") or {},
    )


# ===============================================================
# Workflow Definition
# ===============================================================

@workflow.defn
class NurtureCampaignWorkflow:
    """
    Ticket 7 workflow:

    - Accepts lead + nurture campaign id (+ optional context)
    - Delegates to NurtureCampaignAgent via an activity
    - Returns a summary of how many steps were scheduled
    """

    @workflow.run
    async def run(self, inp: NurtureCampaignInput) -> Dict[str, Any]:
        payload = {
            "lead_id": inp.lead_id,
            "campaign_id": inp.campaign_id,
            "context": inp.context or {},
        }

        result = await workflow.execute_activity(
            run_nurture_campaign_activity,
            payload,
            schedule_to_close_timeout=300,  # 5 minutes is plenty
        )

        return result
