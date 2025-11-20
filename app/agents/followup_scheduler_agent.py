# app/agents/followup_scheduler_agent.py
"""
FollowUpSchedulerAgent
----------------------------------------------------------
Plans follow-up sequences for leads based on conversation intent.

Key cases:
- callback_requested / voicemail  → SMS (1h) → voice call (2h) → email (after call)
- interested_but_not_ready       → nurture email sequence (handled by NurtureCampaignWorkflow)
- unsure_or_declined             → nurture email (or re-engagement) depending on config

This agent returns a "plan" that Temporal workflows execute.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import timedelta
from typing import List, Dict, Any, Literal, Optional

log = logging.getLogger("cory.followup.agent")
log.setLevel(logging.INFO)


IntentType = Literal[
    "ready_to_enroll",
    "interested_but_not_ready",
    "unsure_or_declined",
    "not_interested",
    "callback_requested",
    "voicemail",
    "unclassified",
]


@dataclass
class FollowupStep:
    """Represents a single scheduled follow-up action."""
    channel: Literal["sms", "voice", "email"]
    delay: timedelta
    reason: str
    template: Optional[str] = None  # name/key of template or campaign step
    meta: Dict[str, Any] | None = None


@dataclass
class FollowupPlan:
    """Structured plan that a Temporal workflow can execute."""
    intent: IntentType
    start_callback_sequence: bool = False
    start_nurture_campaign: bool = False
    start_reengagement_campaign: bool = False
    steps: List[FollowupStep] | None = None


class FollowUpSchedulerAgent:
    """
    Pure decision agent (no IO). Temporal workflows call this to determine
    the next follow-up actions based on the last known intent/outcome.
    """

    def __init__(
        self,
        sms_delay_minutes: int = 60,
        call_delay_minutes: int = 120,
        email_delay_minutes: int = 240,
    ) -> None:
        self.sms_delay = timedelta(minutes=sms_delay_minutes)
        self.call_delay = timedelta(minutes=call_delay_minutes)
        self.email_delay = timedelta(minutes=email_delay_minutes)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def plan_followups(
        self,
        *,
        intent: IntentType,
        last_channel: str,
        outcome: Optional[str] = None,
    ) -> FollowupPlan:
        """
        Decide what to do next given the intent + outcome of the last interaction.

        Args:
            intent: classified intent from ConversationalResponseAgent or voice outcome
            last_channel: "voice", "sms", or "email"
            outcome: optional free-text outcome label ("voicemail", "no_answer", etc.)

        Returns:
            FollowupPlan describing callback/nurture/re-engagement actions.
        """
        log.info(
            "📅 Planning follow-ups | intent=%s last_channel=%s outcome=%s",
            intent,
            last_channel,
            outcome,
        )

        # Normalize voicemail / callback
        if outcome == "voicemail" and intent == "unclassified":
            intent = "voicemail"  # explicit case

        # 1️⃣ Callback / voicemail sequence
        if intent in ("callback_requested", "voicemail"):
            return self._plan_callback_sequence(intent=intent)

        # 2️⃣ Interested but not quite ready → nurture
        if intent == "interested_but_not_ready":
            return FollowupPlan(
                intent=intent,
                start_callback_sequence=False,
                start_nurture_campaign=True,
                start_reengagement_campaign=False,
                steps=[],
            )

        # 3️⃣ Unsure or soft decline → nurture (or reengagement)
        if intent == "unsure_or_declined":
            return FollowupPlan(
                intent=intent,
                start_callback_sequence=False,
                start_nurture_campaign=True,
                start_reengagement_campaign=False,
                steps=[],
            )

        # 4️⃣ Hard no → re-engagement / stop (handled by Ticket 8 / policy)
        if intent == "not_interested":
            return FollowupPlan(
                intent=intent,
                start_callback_sequence=False,
                start_nurture_campaign=False,
                start_reengagement_campaign=True,
                steps=[],
            )

        # 5️⃣ Ready_to_enroll or unclassified → handled elsewhere (appointment/manual review)
        return FollowupPlan(
            intent=intent,
            start_callback_sequence=False,
            start_nurture_campaign=False,
            start_reengagement_campaign=False,
            steps=[],
        )

    # ------------------------------------------------------------------
    # Internal planners
    # ------------------------------------------------------------------
    def _plan_callback_sequence(self, intent: IntentType) -> FollowupPlan:
        """
        Build the standard callback/voicemail sequence:
        - SMS reminder after 1h
        - Voice call after 2h
        - Email follow-up after additional delay
        """
        steps = [
            FollowupStep(
                channel="sms",
                delay=self.sms_delay,
                reason="callback_reminder_sms",
                template="callback_reminder_sms",
            ),
            FollowupStep(
                channel="voice",
                delay=self.call_delay,
                reason="callback_followup_call",
                template="callback_followup_call",
            ),
            FollowupStep(
                channel="email",
                delay=self.call_delay + self.email_delay,
                reason="callback_followup_email",
                template="callback_followup_email",
            ),
        ]
        return FollowupPlan(
            intent=intent,
            start_callback_sequence=True,
            start_nurture_campaign=False,
            start_reengagement_campaign=False,
            steps=steps,
        )

    # ------------------------------------------------------------------
    # Helper: convenience for JSON serialization (e.g., logging to DB)
    # ------------------------------------------------------------------
    @staticmethod
    def plan_to_dict(plan: FollowupPlan) -> Dict[str, Any]:
        def step_to_dict(step: FollowupStep) -> Dict[str, Any]:
            d = {
                "channel": step.channel,
                "delay_seconds": int(step.delay.total_seconds()),
                "reason": step.reason,
                "template": step.template,
                "meta": step.meta or {},
            }
            return d

        return {
            "intent": plan.intent,
            "start_callback_sequence": plan.start_callback_sequence,
            "start_nurture_campaign": plan.start_nurture_campaign,
            "start_reengagement_campaign": plan.start_reengagement_campaign,
            "steps": [step_to_dict(s) for s in (plan.steps or [])],
        }
