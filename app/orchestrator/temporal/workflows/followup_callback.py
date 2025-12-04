# app/orchestrator/temporal/workflows/followup_callback.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from temporalio import workflow

from app.agents.followup_scheduler_agent import FollowUpSchedulerAgent
from app.agents.voice_conversation_agent import VoiceConversationAgent
from app.data.supabase_repo import SupabaseRepo
from app.orchestrator.temporal.activities.sms_send import sms_send  # adjust to your actual name
from app.orchestrator.temporal.activities.email_send import email_send
from app.orchestrator.temporal.activities.voice_start import voice_start  # adjust


@dataclass
class CallbackFollowupInput:
    enrollment_id: str
    registration_id: str
    campaign_step_id: str
    org_id: str
    project_id: str
    phone: str
    email: str
    intent: str  # e.g. "callback_requested" or "voicemail"


@workflow.defn
class CallbackFollowupWorkflow:
    """
    Orchestrates the callback / voicemail sequence:
      SMS (1h) → voice call (2h) → email (later)
    Uses FollowUpSchedulerAgent for timing, VoiceConversationAgent for the call.
    """

    def __init__(self) -> None:
        self.scheduler = FollowUpSchedulerAgent()
        # These objects are for type hints; real calls happen via activities.
        self.supabase = SupabaseRepo()

    @workflow.run
    async def run(self, inp: CallbackFollowupInput) -> None:
        # Build a plan from the intent
        plan = self.scheduler.plan_followups(
            intent=inp.intent, last_channel="voice", outcome="voicemail"
        )

        if not plan.start_callback_sequence or not plan.steps:
            # Nothing to do; maybe nurture/reengagement is handled elsewhere
            return

        # Execute each step using Temporal timers + activities
        for step in plan.steps:
            # 1) Sleep for the configured delay
            await workflow.sleep(step.delay)

            if step.channel == "sms":
                await workflow.execute_activity(
                    sms_send,
                    {
                        "project_id": inp.project_id,
                        "enrollment_id": inp.enrollment_id,
                        "to": inp.phone,
                        "template_key": step.template,
                    },
                    schedule_to_close_timeout=timedelta(minutes=5),
                )

            elif step.channel == "voice":
                # Reuse the existing voice_start activity which internally
                # calls VoiceConversationAgent and Synthflow
                await workflow.execute_activity(
                    voice_start,
                    {
                        "org_id": inp.org_id,
                        "enrollment_id": inp.enrollment_id,
                        "phone": inp.phone,
                        "registration_id": inp.registration_id,
                        "campaign_step_id": inp.campaign_step_id,
                    },
                    schedule_to_close_timeout=timedelta(minutes=15),
                )

            elif step.channel == "email":
                await workflow.execute_activity(
                    email_send,
                    {
                        "project_id": inp.project_id,
                        "enrollment_id": inp.enrollment_id,
                        "to": inp.email,
                        "template_key": step.template,
                    },
                    schedule_to_close_timeout=timedelta(minutes=5),
                )
