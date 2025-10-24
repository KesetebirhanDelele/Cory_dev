from __future__ import annotations
import asyncio, json, os
from typing import Any, Dict
from temporalio import activity

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_PROJECT_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

def _sb_headers():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase REST not configured")
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": "return=representation",
    }

async def _http_post(path: str, body: Any, timeout=10):
    from urllib.request import Request, urlopen
    def _do():
        data = json.dumps(body).encode("utf-8")
        req = Request(f"{SUPABASE_URL}{path}", data=data, method="POST")
        for k, v in _sb_headers().items():
            req.add_header(k, v)
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8") or "null")
    return await asyncio.to_thread(_do)

@activity.defn(name="route")
async def route(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    args = {"answer": str, "confidence": float, "threshold": float, "inbound_msg_id": str}
    If confidence >= threshold -> write to 'outbox' (idempotency key: ans:{id})
    else -> create a 'handoffs' row (or just log if REST not configured).
    """
    answer = str(args.get("answer", ""))
    confidence = float(args.get("confidence", 0.0))
    threshold = float(args.get("threshold", 0.8))
    inbound_id = str(args.get("inbound_msg_id") or "")
    if not inbound_id:
        raise activity.ApplicationError("route: missing inbound_msg_id", non_retryable=True)

    idempotency_key = f"ans:{inbound_id}"

    if confidence >= threshold:
        # try REST outbox; if not configured, just return
        try:
            # your schema may differ; this is a simple example
            payload = [{
                "idempotency_key": idempotency_key,
                "channel": "reply",
                "payload": {"text": answer, "confidence": confidence},
                "status": "pending"
            }]
            await _http_post("/rest/v1/outbox", payload)
            return {"sent": True, "route": "outbox", "idempotency_key": idempotency_key}
        except Exception as e:
            # fall back to log-only for dev
            activity.logger.warning("route(outbox) failed: %s; returning as not-sent (dev)", e)
            return {"sent": False, "route": "outbox-local", "idempotency_key": idempotency_key}
    else:
        # create a handoff task (or log)
        try:
            payload = [{
                "inbound_msg_id": inbound_id,
                "reason": "confidence_below_threshold",
                "payload": {"proposed_answer": answer, "confidence": confidence, "threshold": threshold},
                "status": "open"
            }]
            await _http_post("/rest/v1/handoffs", payload)
            return {"sent": False, "route": "handoff", "idempotency_key": idempotency_key}
        except Exception as e:
            activity.logger.warning("route(handoff) failed: %s; returning as log-only (dev)", e)
            return {"sent": False, "route": "handoff-local", "idempotency_key": idempotency_key}
