# app/policy/guards_budget.py
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.6

import os
# ---- LLM spend caps (defaults; override via env) ----
# (keep/define any other channel budgets you use here, e.g.)
LLM_DAILY_BUDGET_CENTS = int(os.getenv("LLM_DAILY_BUDGET_CENTS", "500"))
EMAIL_DAILY_BUDGET_CENTS = int(os.getenv("EMAIL_DAILY_BUDGET_CENTS", "0"))
SMS_DAILY_BUDGET_CENTS   = int(os.getenv("SMS_DAILY_BUDGET_CENTS", "0"))
VOICE_DAILY_BUDGET_CENTS = int(os.getenv("VOICE_DAILY_BUDGET_CENTS", "0"))

# ----------------------------
# Exceptions & atomic checks
# ----------------------------

class PolicyDenied(Exception):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def check_quiet_hours(now: datetime, start: time = time(21, 0), end: time = time(8, 0)) -> None:
    """Deny if current local time is within quiet hours window."""
    n = now.timetz()
    if start <= end:
        blocked = start <= n <= end
    else:
        blocked = (n >= start) or (n <= end)
    if blocked:
        raise PolicyDenied("quiet_hours", "Sending blocked during quiet hours")


def check_consent(has_consent: bool) -> None:
    if not has_consent:
        raise PolicyDenied("no_consent", "Missing contact consent")


def check_frequency(sent_last_24h: int, cap: int = 3) -> None:
    if cap is not None and sent_last_24h >= cap:
        raise PolicyDenied("freq_cap", "Frequency cap reached")


def check_dnc(dnc_labels: set[str], enrollment_labels: set[str]) -> None:
    if dnc_labels and (dnc_labels & enrollment_labels):
        raise PolicyDenied("dnc", "Recipient is on do-not-contact list")


# ----------------------------
# Orchestrator-facing API
# ----------------------------

def pre_send_decision(
    *,
    enrollment: Dict[str, Any],
    step: Dict[str, Any],
    policy: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deterministic policy gate used by CampaignWorkflow before sending.
    Returns a verdict dict instead of raising so the workflow can branch.
    """
    raw_now: Optional[datetime] = context.get("now")
    if isinstance(raw_now, str):
        now = datetime.fromisoformat(raw_now.replace("Z", "+00:00"))
    elif isinstance(raw_now, datetime):
        now = raw_now
    else:
        now = datetime.now(timezone.utc)

    quiet_hours_enabled = bool(policy.get("quiet_hours", True))
    quiet_start = _parse_hhmm(policy.get("quiet_start", "21:00"))
    quiet_end = _parse_hhmm(policy.get("quiet_end", "08:00"))
    freq_cap = policy.get("frequency_cap_per_24h", 3)
    respect_dnc = bool(policy.get("respect_dnc", True))
    dnc_labels = set(map(str, policy.get("dnc_labels", ["dnc", "do_not_contact", "do_not_call"])))

    has_consent = bool(enrollment.get("consent", policy.get("default_consent", True)))
    enrollment_labels = set(map(str, enrollment.get("labels", [])))
    sent_last_24h = int(context.get("sent_count_last_24h", 0))

    try:
        if respect_dnc:
            check_dnc(dnc_labels, enrollment_labels)
        check_consent(has_consent)
        if quiet_hours_enabled:
            check_quiet_hours(_to_naive_time(now), start=quiet_start, end=quiet_end)
        check_frequency(sent_last_24h, cap=freq_cap)
        return {"allow": True}
    except PolicyDenied as e:
        hint: Dict[str, Any] = {}
        if e.code == "quiet_hours":
            next_time = _next_allowed_time(_to_naive_time(now), quiet_start, quiet_end)
            hint = {"schedule_after": next_time.isoformat()}
        elif e.code == "freq_cap":
            hint = {"retry_in_hours": 24}
        elif e.code == "no_consent":
            hint = {"action": "obtain_consent"}
        elif e.code == "dnc":
            hint = {"action": "remove_dnc_or_skip"}

        return {"allow": False, "reason": e.code, "next_hint": hint or None}


# ----------------------------
# Async convenience for activities
# ----------------------------

async def evaluate_policy_guards(
    db, lead: Dict[str, Any], org: Dict[str, Any], channel: str
) -> Tuple[bool, str]:
    """
    Async helper called by Temporal activities (SMS/Email/Voice).

    Fetches count of recent sends and applies pre_send_decision logic.
    Returns (allowed, reason).
    """
    # --- Fetch recent send count from interactions table --------------------
    q = """
        SELECT COUNT(*) AS cnt
        FROM interactions
        WHERE lead_id = $1 AND channel = $2
          AND created_at > (NOW() - INTERVAL '24 hours')
    """
    sent_last_24h = 0
    result = None
    try:
        maybe_result = await db.execute_query(q, lead.get("id"), channel)
        # If fake_query was defined as async def returning a list, this is fine.
        # If it returns a coroutine (common pytest mock pitfall), await it.
        if callable(maybe_result):
            maybe_result = await maybe_result
        result = maybe_result

        if result:
            first = result[0]
            if isinstance(first, dict):
                lower_keys = {k.lower(): v for k, v in first.items()}
                sent_last_24h = int(lower_keys.get("cnt", 0) or lower_keys.get("count", 0) or 0)
            elif hasattr(first, "_asdict"):
                lower_keys = {k.lower(): v for k, v in first._asdict().items()}
                sent_last_24h = int(lower_keys.get("cnt", 0))
    except Exception as e:
        logger.debug("PolicyGuardDBFallback", extra={"error": str(e)})
        sent_last_24h = 0

    # 🔍 Debug diagnostic
    logger.debug(
        "TEST_DEBUG_SENT_LAST_24H",
        extra={"lead_id": lead.get("id"), "sent_last_24h": sent_last_24h, "raw_result": str(result)}
    )

    # --- Resolve policy and enrollment context ------------------------------
    policy = org.get("policy") or org  # support nested or flat org dicts
    enrollment = {
        "consent": lead.get("metadata", {})
        .get("communication_consent", {})
        .get("accepted_terms", True),
        "labels": lead.get("metadata", {}).get("labels", []),
        "timezone": lead.get("timezone", org.get("timezone", "America/New_York")),
    }
    step = {"channel": channel}
    context = {"sent_count_last_24h": sent_last_24h, "now": datetime.utcnow().isoformat()}

    # --- Evaluate via core deterministic logic ------------------------------
    verdict = pre_send_decision(enrollment=enrollment, step=step, policy=policy, context=context)

    # --- Structured result ---------------------------------------------------
    if verdict.get("allow"):
        logger.debug(
            "PolicyAllow",
            extra={"lead_id": lead.get("id"), "channel": channel, "sent_last_24h": sent_last_24h},
        )
        return True, "allowed"

    reason = verdict.get("reason", "unknown")
    logger.info(
        "PolicyBlocked",
        extra={
            "lead_id": lead.get("id"),
            "channel": channel,
            "reason": reason,
            "hint": verdict.get("next_hint"),
            "sent_last_24h": sent_last_24h,
        },
    )
    return False, reason

# ----------------------------
# Helpers (pure)
# ----------------------------

def _parse_hhmm(s: str) -> time:
    try:
        hh, mm = s.split(":")
        return time(int(hh), int(mm))
    except Exception:
        return time(21, 0) if "21" in s else time(8, 0)


def _to_naive_time(dt: datetime) -> datetime:
    if dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _next_allowed_time(now: datetime, start: time, end: time) -> datetime:
    today = now.date()
    cur_t = now.time()
    if start <= end:
        if start <= cur_t <= end:
            return datetime.combine(today, end) + timedelta(minutes=1)
        return now
    else:
        in_block = (cur_t >= start) or (cur_t <= end)
        if in_block:
            target_day = today if cur_t <= end else (today + timedelta(days=1))
            return datetime.combine(target_day, end) + timedelta(minutes=1)
        return now

__all__ = [
    "LLM_DAILY_BUDGET_CENTS",
    "EMAIL_DAILY_BUDGET_CENTS",
    "SMS_DAILY_BUDGET_CENTS",
    "VOICE_DAILY_BUDGET_CENTS",
    "CONFIDENCE_THRESHOLD",
]
