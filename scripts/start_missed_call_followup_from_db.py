# scripts/start_missed_call_followup_from_db.py
"""
Manually start MissedCallFollowupWorkflow from the latest missed Synthflow call.

Flow:
  1) Find most recent voice message with status='hangup_on_voicemail'
  2) Resolve contact → latest enrollment → campaign → Smart Nurture campaign
  3) Start MissedCallFollowupWorkflow on the campaign/comm task queue
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from supabase import create_client
from temporalio.client import Client

from app.orchestrator.temporal.workflows.missed_call_followup import (
    MissedCallFollowupWorkflow,
)

log = logging.getLogger("cory.scripts.start_missed_call_followup_from_db")

# -------------------------------------------------------------------
# Config helpers
# -------------------------------------------------------------------


def _supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing")
    return create_client(url, key)


TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "localhost:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
CAMPAIGN_QUEUE = os.getenv("TEMPORAL_COMM_TASK_QUEUE", "comm-q")


async def _temporal_client() -> Client:
    log.info(
        "[Temporal] Connecting to %s (namespace=%s)", TEMPORAL_TARGET, TEMPORAL_NAMESPACE
    )
    client = await Client.connect(TEMPORAL_TARGET, namespace=TEMPORAL_NAMESPACE)
    log.info("[Temporal] Connected")
    return client


# -------------------------------------------------------------------
# Lookup helpers
# -------------------------------------------------------------------


def _normalize_phone(phone: str) -> str:
    phone = (phone or "").strip()
    if not phone:
        return ""
    if phone.startswith("+"):
        return phone
    # naive US normalization for test purposes
    return f"+1{phone}"


def _get_latest_missed_voice(sb) -> Dict[str, Any]:
    """Return the most recent VOICE message with status='hangup_on_voicemail'."""
    resp = (
        sb.table("message")
        .select("*")
        .eq("channel", "voice")
        .eq("status", "hangup_on_voicemail")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise RuntimeError("No voice message with status='hangup_on_voicemail' found")
    return rows[0]


def _lookup_contact_for_message(sb, msg: Dict[str, Any]) -> Dict[str, Any]:
    """Infer the contact record from the message content payload."""
    content = msg.get("content") or {}

    # Try to pull phone from raw Synthflow payload
    raw = content.get("raw_payload") or {}
    lead = raw.get("lead") or {}
    phone = lead.get("phone_number")

    # Fallback: sometimes we stuff 'lead_phone' directly in content
    if not phone:
        phone = content.get("lead_phone")

    if not phone:
        raise RuntimeError("Could not infer phone from message.content")

    phone_e164 = _normalize_phone(phone)

    candidates = [
        phone_e164,
        phone_e164.replace("+1", ""),  # local
    ]

    log.info("🔎 Looking up contact by phones: %s", candidates)

    resp = (
        sb.table("contact")
        .select("*")
        .in_("phone", candidates)
        .limit(1)
        .execute()
    )
    contacts = resp.data or []
    if not contacts:
        raise RuntimeError(f"No contact found matching phones {candidates}")

    return contacts[0]


def _lookup_latest_enrollment(sb, contact_id: str) -> Dict[str, Any]:
    resp = (
        sb.table("enrollment")
        .select("*")
        .eq("contact_id", contact_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise RuntimeError(f"No enrollment found for contact_id={contact_id}")
    return rows[0]


def _lookup_campaign(sb, campaign_id: str) -> Dict[str, Any]:
    resp = (
        sb.table("campaigns")
        .select("*")
        .eq("id", campaign_id)
        .single()
        .execute()
    )
    if not resp.data:
        raise RuntimeError(f"Campaign not found id={campaign_id}")
    return resp.data


def _lookup_smart_nurture_campaign(sb, organization_id: str) -> Optional[str]:
    """
    Find Smart Nurture campaign:
      settings->>category = 'nurture'
      settings->>kind     = 'smart_nurture'
    """
    resp = (
        sb.table("campaigns")
        .select("id, settings, organization_id")
        .eq("organization_id", organization_id)
        .filter("settings->>category", "eq", "nurture")
        .filter("settings->>kind", "eq", "smart_nurture")
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        log.warning(
            "[NurtureLookup] No Smart Nurture campaign found for organization_id=%s",
            organization_id,
        )
        return None
    return rows[0]["id"]


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------


async def main() -> None:
    load_dotenv()
    sb = _supabase()

    # 1) Latest missed Synthflow voice message
    msg = _get_latest_missed_voice(sb)
    log.info(
        "📥 Using message id=%s provider_ref=%s status=%s created_at=%s",
        msg.get("id"),
        msg.get("provider_ref"),
        msg.get("status"),
        msg.get("created_at"),
    )

    # 2) Contact / enrollment
    contact = _lookup_contact_for_message(sb, msg)
    contact_id = contact["id"]
    project_id = contact["project_id"]
    full_name = (
        (contact.get("first_name") or "") + " " + (contact.get("last_name") or "")
    ).strip()

    enrollment = _lookup_latest_enrollment(sb, contact_id)
    enrollment_id = enrollment["id"]
    campaign_id = enrollment.get("campaign_id")

    log.info(
        "✅ Contact %s (%s) project=%s => enrollment=%s campaign=%s",
        full_name or "Unknown",
        contact_id,
        project_id,
        enrollment_id,
        campaign_id,
    )

    if not campaign_id:
        raise RuntimeError("Enrollment has no campaign_id, cannot resolve org")

    # 3) Campaign / org / Smart Nurture
    campaign = _lookup_campaign(sb, campaign_id)
    org_id = campaign["organization_id"]
    smart_nurture_id = _lookup_smart_nurture_campaign(sb, org_id)

    # 4) Phone for workflow
    phone = _normalize_phone(contact.get("phone") or "")
    if not phone:
        raise RuntimeError("Contact has no phone; cannot start missed-call followup")

    log.info(
        "☎️  Starting MissedCallFollowupWorkflow for phone=%s, enrollment=%s, "
        "campaign=%s, smart_nurture=%s",
        phone,
        enrollment_id,
        campaign_id,
        smart_nurture_id,
    )

    # 5) Start Temporal workflow
    client = await _temporal_client()

    workflow_id = f"missed-call-manual-{msg.get('id')}"
    handle = await client.start_workflow(
        MissedCallFollowupWorkflow.run,
        args=[
            phone,
            str(enrollment_id),
            str(campaign_id),
            str(smart_nurture_id) if smart_nurture_id else None,
        ],
        id=workflow_id,
        task_queue=CAMPAIGN_QUEUE,
    )

    log.info(
        "🚀 MissedCallFollowupWorkflow started: workflow_id=%s run_id=%s",
        handle.id,
        handle.result_run_id,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
