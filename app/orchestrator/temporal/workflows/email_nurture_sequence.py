# app/orchestrator/temporal/workflows/email_nurture_sequence.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, Any, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

# Temporal-safe imports
with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.email_send import email_send
    from app.orchestrator.temporal.activities.email_reply_check import (
        email_reply_check,
    )


@dataclass
class EmailNurtureInput:
    """Input for EmailNurtureWorkflow."""

    enrollment_id: str
    lead: Dict[str, Any]
    organization: Dict[str, Any]
    campaign_id: Optional[str] = None
    to_email: Optional[str] = None
    emails_count: int = 5
    delay_seconds: int = 60
    subject_prefix: str = "[Cory Test] Nurture Email"
    template_name: Optional[str] = None  # if you want templates later


@workflow.defn
class EmailNurtureWorkflow:
    """
    Simple test workflow:

    - Sends up to N emails, `delay_seconds` apart.
    - Before each send, checks Supabase for an inbound email reply.
    - If a reply exists, it stops early and returns "stopped_due_to_reply".
    """

    @workflow.run
    async def run(self, inp: EmailNurtureInput) -> str:
        logger = workflow.logger

        to_email = inp.to_email or inp.lead.get("email")
        if not to_email:
            raise ValueError("EmailNurtureWorkflow requires to_email or lead['email'].")

        logger.info(
            "📧 Starting EmailNurtureWorkflow | enrollment=%s, to=%s, max_emails=%d",
            inp.enrollment_id,
            to_email,
            inp.emails_count,
        )

        for idx in range(1, inp.emails_count + 1):
            # 1️⃣ Check if there is already a reply recorded in Supabase
            reply_result = await workflow.execute_activity(
                email_reply_check,
                {
                    "enrollment_id": inp.enrollment_id,
                    "lookback_minutes": 240,
                },
                schedule_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            if reply_result.get("has_reply"):
                logger.info(
                    "✅ Reply detected for enrollment %s — "
                    "stopping nurture sequence at email #%d",
                    inp.enrollment_id,
                    idx,
                )
                return "stopped_due_to_reply"

            # 2️⃣ No reply yet → send next email
            subject = f"{inp.subject_prefix} {idx} of {inp.emails_count}"
            body = (
                f"Hi {inp.lead.get('first_name', 'there')},\n\n"
                f"This is nurture email {idx} of {inp.emails_count}.\n\n"
                "Cory is testing multi-step email follow-up."
            )

            email_payload = {
                "lead": inp.lead,
                "organization": inp.organization,
                "to": to_email,
                "subject": subject,
                "template": inp.template_name,
                "variables": {},
                "campaign_id": inp.campaign_id,
            }

            logger.info(
                "📨 Sending nurture email #%d/%d to %s",
                idx,
                inp.emails_count,
                to_email,
            )

            await workflow.execute_activity(
                email_send,
                inp.enrollment_id,
                email_payload,
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            # 3️⃣ Wait before next email, unless that was the last one
            if idx < inp.emails_count:
                delay = timedelta(seconds=inp.delay_seconds)
                logger.info(
                    "⏳ Sleeping %s seconds before next email",
                    inp.delay_seconds,
                )
                await workflow.sleep(delay)

        logger.info(
            "🏁 Completed all %d nurture emails with no reply detected "
            "for enrollment %s",
            inp.emails_count,
            inp.enrollment_id,
        )
        return "completed_no_reply"
