# app/orchestrator/temporal/activities/rag_route.py
from __future__ import annotations

from typing import Any, Dict
import json  # NEW: for JSON serialization

from temporalio import activity

# Re-use the same DB pool helper as the RAG retriever
from app.orchestrator.temporal.activities.rag import _get_pool


@activity.defn(name="route")
async def route(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decide whether to send an automated answer or create a handoff.

    Expected input:
        {
            "answer": str,
            "inbound_msg_id": str,
            "confidence": float,
            "threshold": float,
            "intent": Optional[str],
            "next_action": Optional[str],
        }

    Behavior:
      - If confidence >= threshold AND next_action != "handoff_to_human":
          → write to outbox and return sent=True
      - Else:
          → create a handoff row with intent / next_action in payload
    """
    answer = (args.get("answer") or "").strip()
    inbound_msg_id = args.get("inbound_msg_id")
    confidence = float(args.get("confidence", 0.0))
    threshold = float(args.get("threshold", 0.8))

    intent = args.get("intent")  # may be None
    next_action = args.get("next_action")  # may be None

    if not inbound_msg_id:
        raise activity.ApplicationError(
            "route: missing inbound_msg_id",
            non_retryable=True,
        )

    key = f"ans:{inbound_msg_id}"

    # Decide if we must escalate, even if confidence is high
    must_handoff = (next_action == "handoff_to_human") or (confidence < threshold)

    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Ensure tables exist (idempotent in dev)
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

        if not must_handoff:
            # High-confidence auto answer → record in outbox
            body = {
                "answer": answer,
                "confidence": confidence,
                "intent": intent,
                "next_action": next_action,
            }
            await conn.execute(
                """
                INSERT INTO outbox (idempotency_key, body)
                VALUES ($1, $2::jsonb)
                ON CONFLICT (idempotency_key) DO NOTHING;
                """,
                key,
                json.dumps(body),  # send JSON string, matches ::jsonb cast
            )
            activity.logger.info(
                "route: auto-sent answer | inbound=%s | confidence=%.2f | intent=%s",
                inbound_msg_id,
                confidence,
                intent,
            )
            return {"sent": True, "idempotency_key": key}

        # Otherwise → create a handoff with rich payload
        reason = "confidence_below_threshold"
        if next_action == "handoff_to_human" and confidence >= threshold:
            reason = "model_requested_handoff"

        payload: Dict[str, Any] = {
            "answer": answer,
            "confidence": confidence,
        }
        # Only include these if present
        if intent is not None:
            payload["intent"] = intent
        if next_action is not None:
            payload["next_action"] = next_action

        await conn.execute(
            """
            INSERT INTO handoffs (inbound_msg_id, reason, payload)
            VALUES ($1, $2, $3::jsonb);
            """,
            inbound_msg_id,
            reason,
            json.dumps(payload),  # send JSON string here too
        )

        activity.logger.info(
            "route: created handoff | inbound=%s | reason=%s | intent=%s | next_action=%s",
            inbound_msg_id,
            reason,
            intent,
            next_action,
        )

        return {"sent": False, "idempotency_key": key}
