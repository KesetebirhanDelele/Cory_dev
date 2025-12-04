from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any

from temporalio import workflow
from temporalio import activity

from app.agents.reengagement_campaign_agent import ReengagementCampaignAgent


# ===============================================================
# Workflow Input Model
# ===============================================================

@dataclass
class ReengagementCampaignInput:
    lead_id: str
    campaign_id: str
    context: Optional[Dict[str, Any]] = None


# ===============================================================
# Activity Wrapper
# ===============================================================

@activity.defn
async def run_reengagement_activity(payload: dict) -> dict:
    agent = ReengagementCampaignAgent()
    return await agent.run_campaign(**payload)


# ===============================================================
# Workflow Definition
# ===============================================================

@workflow.defn
class ReengagementCampaignWorkflow:
    """
    Ticket 8 workflow:
    - receives lead/campaign info
    - invokes ReengagementCampaignAgent inside an activity
    """

    @workflow.run
    async def run(self, inp: ReengagementCampaignInput) -> Dict[str, Any]:
        payload = {
            "lead_id": inp.lead_id,
            "campaign_id": inp.campaign_id,
            "context": inp.context or {},
        }

        result = await workflow.execute_activity(
            run_reengagement_activity,
            payload,
            schedule_to_close_timeout=30,
        )

        return result
