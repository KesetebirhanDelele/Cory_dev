# scripts/test_synthflow_call.py

import asyncio
import logging
import os

from dotenv import load_dotenv
from supabase import create_client

from app.channels.providers.voice import send_voice_call

log = logging.getLogger("cory.scripts.test_synthflow_call")

# We do NOT store this in .env on purpose
TEST_PHONE_LOCAL = "5714782790"  # your local 10-digit number


def _make_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing in environment")
    return create_client(url, key)


async def main() -> None:
    # Load real env (DB + Synthflow keys), but no test data
    load_dotenv()

    supabase = _make_supabase_client()

    # ------------------------------------------------------------------
    # 1) Look up your contact by phone
    # ------------------------------------------------------------------
    candidate_phones = [
        TEST_PHONE_LOCAL,
        f"+1{TEST_PHONE_LOCAL}",
        f"+1-{TEST_PHONE_LOCAL}",
    ]

    log.info("🔎 Looking up contact by phone variants: %s", candidate_phones)

    contact_resp = (
        supabase.table("contact")
        .select("*")
        .in_("phone", candidate_phones)
        .limit(1)
        .execute()
    )

    contacts = contact_resp.data or []
    if not contacts:
        raise RuntimeError(
            f"No contact found with phone in {candidate_phones}. "
            f"Make sure your test record exists in public.contact."
        )

    contact = contacts[0]
    contact_id = contact["id"]
    project_id = contact["project_id"]
    first_name = contact.get("first_name") or ""
    last_name = contact.get("last_name") or ""
    lead_name = (first_name + " " + last_name).strip() or "Test Student"

    # Normalize phone to E.164-ish for Synthflow
    raw_phone = contact.get("phone") or TEST_PHONE_LOCAL
    if raw_phone.startswith("+"):
        to_e164 = raw_phone
    else:
        to_e164 = f"+1{raw_phone}"

    log.info("✅ Found contact %s (%s) with phone %s", lead_name, contact_id, to_e164)

    # ------------------------------------------------------------------
    # 2) Find the most recent enrollment for this contact
    # ------------------------------------------------------------------
    enr_resp = (
        supabase.table("enrollment")
        .select("*")
        .eq("contact_id", contact_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    enrollments = enr_resp.data or []
    if not enrollments:
        raise RuntimeError(f"No enrollment found for contact {contact_id}")

    enrollment = enrollments[0]
    enrollment_id = enrollment["id"]
    campaign_id = enrollment.get("campaign_id")

    log.info(
        "✅ Using enrollment %s (campaign_id=%s, project_id=%s)",
        enrollment_id,
        campaign_id,
        project_id,
    )

    # ------------------------------------------------------------------
    # 3) Resolve organization via campaign (campaigns.organization_id)
    # ------------------------------------------------------------------
    org_id = None
    campaign_name = None
    if campaign_id:
        camp_resp = (
            supabase.table("campaigns")
            .select("id,name,organization_id")
            .eq("id", campaign_id)
            .single()
            .execute()
        )
        if camp_resp.data:
            org_id = camp_resp.data["organization_id"]
            campaign_name = camp_resp.data["name"]

    if not org_id:
        # As a fallback, you *could* hard-code the seed org here,
        # but ideally your enrollment has a campaign_id already.
        raise RuntimeError(
            f"Could not resolve organization_id for campaign_id={campaign_id}. "
            "Check that your enrollment is linked to a campaign."
        )

    log.info("✅ Resolved organization_id=%s (campaign_name=%s)", org_id, campaign_name)

    # ------------------------------------------------------------------
    # 4) Build vars for Synthflow call (no test data in .env)
    # ------------------------------------------------------------------
    vars = {
        "lead_name": lead_name,
        "contact_id": contact_id,
        "project_id": project_id,
        "enrollment_id": enrollment_id,
        "campaign_id": campaign_id,
    }

    if campaign_name:
        vars["reason_for_call"] = f"your interest in our {campaign_name} campaign"

    print(
        f"📞 Initiating Synthflow call to {to_e164} for {lead_name} "
        f"(enrollment={enrollment_id}, org={org_id})"
    )

    result = await send_voice_call(
        org_id=str(org_id),
        enrollment_id=str(enrollment_id),
        to=to_e164,
        vars=vars,
    )

    print("✅ Synthflow call result:")
    print(result)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
