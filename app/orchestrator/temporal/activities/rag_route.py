from __future__ import annotations

from typing import Any, Dict, Optional
import json
import logging

from temporalio import activity

# Re-use the same DB pool helper as the RAG retriever
from app.orchestrator.temporal.activities.rag import _get_pool

log = logging.getLogger("cory.activities.rag_route")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_outbox_and_handoffs(conn) -> None:
    """Create lightweight outbox/handoffs tables if they don't exist (dev only)."""
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS outbox (
            id BIGSERIAL PRIMARY KEY,
            idempotency_key TEXT UNIQUE,
            body JSONB NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        );
        """
    )

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS handoffs (
            id BIGSERIAL PRIMARY KEY,
            inbound_msg_id TEXT,
            reason TEXT,
            payload JSONB,
            created_at TIMESTAMPTZ DEFAULT now()
        );
        """
    )


async def _lookup_campaign_id(
    conn,
    *,
    organization_id: Optional[str],
    category: str,
    kind: str,
) -> Optional[str]:
    """
    Find a campaign.id by organization + settings.category + settings.kind.

    Returns None if not found or org_id missing; we only log in that case.
    """
    if not organization_id:
        log.info(
            "rag_route: cannot resolve campaign_id — missing organization_id "
            "(category=%s kind=%s)",
            category,
            kind,
        )
        return None

    row = await conn.fetchrow(
        """
        SELECT id
        FROM campaigns
        WHERE organization_id = $1
          AND settings->>'category' = $2
          AND settings->>'kind' = $3
        LIMIT 1;
        """,
        organization_id,
        category,
        kind,
    )
    if not row:
        log.info(
            "rag_route: no campaign found for org=%s category=%s kind=%s",
            organization_id,
            category,
            kind,
        )
        return None

    return str(row["id"])


async def _upsert_campaign_enrollment(
    conn,
    *,
    enrollment_id: Optional[str],
    campaign_id: Optional[str],
    campaign_type: str,
    tier: str = "tier1",
) -> None:
    """
    Idempotent insert into campaign_enrollments.

    If we don't have both enrollment_id and campaign_id we just log and skip.
    """
    if not enrollment_id or not campaign_id:
        log.info(
            "rag_route: skip campaign_enrollment — missing enrollment_id or campaign_id "
            "(enrollment_id=%s, campaign_id=%s, type=%s)",
            enrollment_id,
            campaign_id,
            campaign_type,
        )
        return

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
        "rag_route: enrollment_id=%s enrolled into campaign_id=%s campaign_type=%s tier=%s",
        enrollment_id,
        campaign_id,
        campaign_type,
        tier,
    )


# ---------------------------------------------------------------------------
# Main Activity
# ---------------------------------------------------------------------------


@activity.defn(name="route")
async def route(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decide whether to send an automated SMS answer, escalate to a human,
    or enroll the lead into Smart Nurture / Cold Nurture.

    Expected input (superset – some fields may be missing in older callers):

        {
            "answer": str,
            "inbound_msg_id": str,
            "confidence": float,
            "threshold": float,
            "intent": Optional[str],
            "next_action": Optional[str],

            # Optional context for future routing:
            "lead": {...},          # includes "id", "phone", ...
            "enrollment": {...},    # includes "id", "campaign_id", ...
            "organization": {...},  # includes "id"
            "channel": "sms" | "whatsapp" | ...,
        }

    Behavior (high-level):

      - If confidence >= threshold AND next_action != "handoff_to_human"
        AND intent not in ["ready_to_enroll", "needs_human"]:
            → auto answer → write to `outbox` table, return sent=True

      - Else:
            → write a row into `handoffs` (for later processing),
              with reason and JSON payload.

      - Additionally, when we *have* enough context:

          intent == "interested_not_ready"
          or next_action == "enroll_smart_nurture"
              → enroll into Smart Nurture (campaign_type="nurture")

          intent == "not_interested"
          or next_action == "enroll_cold_nurture"
              → enroll into Cold Nurture (campaign_type="reengagement")
    """
    answer = (args.get("answer") or "").strip()
    inbound_msg_id = args.get("inbound_msg_id")
    confidence = float(args.get("confidence", 0.0))
    threshold = float(args.get("threshold", 0.8))

    intent: Optional[str] = args.get("intent") or None
    next_action: Optional[str] = args.get("next_action") or None

    # Optional richer context
    lead: Dict[str, Any] = args.get("lead") or {}
    enrollment: Dict[str, Any] = args.get("enrollment") or {}
    org: Dict[str, Any] = args.get("organization") or {}
    channel: str = (args.get("channel") or "sms").lower()

    enrollment_id: Optional[str] = enrollment.get("id")
    organization_id: Optional[str] = org.get("id")

    if not inbound_msg_id:
        raise activity.ApplicationError(
            "route: missing inbound_msg_id",
            non_retryable=True,
        )

    idempotency_key = f"ans:{inbound_msg_id}"

    log.info(
        "route: start | inbound=%s | conf=%.2f | thresh=%.2f | intent=%s | next_action=%s",
        inbound_msg_id,
        confidence,
        threshold,
        intent,
        next_action,
    )

    # ----------------------------------------------------------------------
    # Decide primary action: auto answer vs handoff
    # ----------------------------------------------------------------------
    must_handoff = (
        confidence < threshold
        or next_action == "handoff_to_human"
        or intent in ("ready_to_enroll", "needs_human")
    )

    # Secondary choices: nurture / reengagement (only if not handing off)
    wants_smart_nurture = (
        not must_handoff
        and (
            intent == "interested_not_ready"
            or next_action == "enroll_smart_nurture"
        )
    )
    wants_cold_nurture = (
        not must_handoff
        and (
            intent == "not_interested"
            or next_action == "enroll_cold_nurture"
        )
    )

    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Make sure helper tables exist (for dev/local)
        await _ensure_outbox_and_handoffs(conn)

        # --------------------------------------------------------------
        # Optional: nurture / reengagement enrollment if we have context
        # --------------------------------------------------------------
        if wants_smart_nurture:
            smart_id = await _lookup_campaign_id(
                conn,
                organization_id=organization_id,
                category="nurture",
                kind="smart_nurture",
            )
            await _upsert_campaign_enrollment(
                conn,
                enrollment_id=enrollment_id,
                campaign_id=smart_id,
                campaign_type="nurture",
                tier="tier1",
            )

        if wants_cold_nurture:
            cold_id = await _lookup_campaign_id(
                conn,
                organization_id=organization_id,
                category="reengagement",
                kind="cold_nurture",
            )
            await _upsert_campaign_enrollment(
                conn,
                enrollment_id=enrollment_id,
                campaign_id=cold_id,
                campaign_type="reengagement",
                tier="tier1",
            )

        # --------------------------------------------------------------
        # 1) High-confidence auto answer → write to outbox
        # --------------------------------------------------------------
        if not must_handoff:
            body = {
                "answer": answer,
                "confidence": confidence,
                "intent": intent,
                "next_action": next_action,
                "channel": channel,
                "lead": lead,
                "enrollment": enrollment,
                "organization": org,
            }

            # IMPORTANT: cast dict to JSON string so asyncpg is happy with ::jsonb
            await conn.execute(
                """
                INSERT INTO outbox (idempotency_key, body)
                VALUES ($1, $2::jsonb)
                ON CONFLICT (idempotency_key) DO NOTHING;
                """,
                idempotency_key,
                json.dumps(body),
            )

            log.info(
                "route: auto-sent answer | inbound=%s | conf=%.2f | intent=%s | next_action=%s",
                inbound_msg_id,
                confidence,
                intent,
                next_action,
            )
            return {"sent": True, "idempotency_key": idempotency_key}

        # --------------------------------------------------------------
        # 2) Otherwise → create a handoff record
        # --------------------------------------------------------------
        reason = "confidence_below_threshold"
        if confidence >= threshold and next_action == "handoff_to_human":
            reason = "model_requested_handoff"
        if intent in ("ready_to_enroll", "needs_human"):
            reason = f"intent_{intent}"

        payload: Dict[str, Any] = {
            "answer": answer,
            "confidence": confidence,
            "intent": intent,
            "next_action": next_action,
            "channel": channel,
            "lead": lead,
            "enrollment": enrollment,
            "organization": org,
        }

        await conn.execute(
            """
            INSERT INTO handoffs (inbound_msg_id, reason, payload)
            VALUES ($1, $2, $3::jsonb);
            """,
            inbound_msg_id,
            reason,
            json.dumps(payload),
        )

        log.info(
            "route: created handoff | inbound=%s | reason=%s | intent=%s | next_action=%s",
            inbound_msg_id,
            reason,
            intent,
            next_action,
        )

        return {"sent": False, "idempotency_key": idempotency_key}
