# app/policy/guards.py
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Dict, Any, Optional


# ----------------------------
# Exceptions & atomic checks
# ----------------------------

class PolicyDenied(Exception):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def check_quiet_hours(now: datetime, start: time = time(21, 0), end: time = time(8, 0)) -> None:
    """
    Deny if current local time is within quiet hours window.
    Window crosses midnight when start >= end (default 21:00–08:00).
    """
    n = now.timetz()
    if start <= end:
        blocked = start <= n <= end
    else:
        # window spans midnight (e.g., 21:00–08:00)
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
    Returns a verdict dict instead of raising, so the workflow can branch:

      { "allow": True }  OR
      {
        "allow": False,
        "reason": "<code>",
        "next_hint": { ... }   # optional structured suggestion
      }

    Inputs (all optional keys handled gracefully):
      enrollment: { "timezone": "America/Chicago", "consent": bool, "labels": ["dnc", ...] }
      step:       { "channel": "sms"|"email"|"voice" }
      policy:     {
                    "quiet_hours": true,
                    "quiet_start": "21:00", "quiet_end": "08:00",
                    "frequency_cap_per_24h": 3,
                    "respect_dnc": true, "dnc_labels": ["dnc","do_not_call"],
                    "default_consent": true
                  }
      context:    {
                    "now": "2025-01-01T12:00:00Z" | datetime,
                    "sent_count_last_24h": 0
                  }
    """

    # --- Resolve "now" deterministically (UTC by default) -------------------
    raw_now: Optional[datetime] = context.get("now")
    if isinstance(raw_now, str):
        # RFC3339/ISO8601; if naive, treat as UTC
        now = datetime.fromisoformat(raw_now.replace("Z", "+00:00"))
    elif isinstance(raw_now, datetime):
        now = raw_now
    else:
        now = datetime.now(timezone.utc)

    # NOTE: If you want true local quiet-hours by contact timezone, integrate a tz lib.
    # For deterministic/no-deps behavior, we treat quiet-hours against the given "now".
    # You can pre-convert "now" to local time in caller if needed.

    # --- Parse policy knobs with defaults -----------------------------------
    quiet_hours_enabled = bool(policy.get("quiet_hours", True))
    quiet_start = _parse_hhmm(policy.get("quiet_start", "21:00"))
    quiet_end = _parse_hhmm(policy.get("quiet_end", "08:00"))
    freq_cap = policy.get("frequency_cap_per_24h", 3)
    respect_dnc = bool(policy.get("respect_dnc", True))
    dnc_labels = set(map(str, policy.get("dnc_labels", ["dnc", "do_not_contact", "do_not_call"])))

    has_consent = bool(enrollment.get("consent", policy.get("default_consent", True)))
    enrollment_labels = set(map(str, enrollment.get("labels", [])))

    sent_last_24h = int(context.get("sent_count_last_24h", 0))

    # --- Evaluate checks (order chosen for best user experience) ------------
    try:
        if respect_dnc:
            check_dnc(dnc_labels, enrollment_labels)

        check_consent(has_consent)

        if quiet_hours_enabled:
            check_quiet_hours(_to_naive_time(now), start=quiet_start, end=quiet_end)

        check_frequency(sent_last_24h, cap=freq_cap)

        # All clear
        return {"allow": True}

    except PolicyDenied as e:
        # Build actionable next-hint
        hint: Dict[str, Any] = {}
        if e.code == "quiet_hours":
            next_time = _next_allowed_time(_to_naive_time(now), quiet_start, quiet_end)
            hint = {"schedule_after": next_time.isoformat()}
        elif e.code == "freq_cap":
            # simple suggestion: retry after 24h window rolls
            hint = {"retry_in_hours": 24}
        elif e.code == "no_consent":
            hint = {"action": "obtain_consent"}
        elif e.code == "dnc":
            hint = {"action": "remove_dnc_or_skip"}

        return {
            "allow": False,
            "reason": e.code,
            "next_hint": hint or None,
        }


# ----------------------------
# Helpers (pure)
# ----------------------------

def _parse_hhmm(s: str) -> time:
    """Parse 'HH:MM' into a time object; fallback to defaults if malformed."""
    try:
        hh, mm = s.split(":")
        return time(int(hh), int(mm))
    except Exception:
        return time(21, 0) if "21" in s else time(8, 0)


def _to_naive_time(dt: datetime) -> datetime:
    """Return a timezone-naive datetime for local time comparisons."""
    if dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _next_allowed_time(now: datetime, start: time, end: time) -> datetime:
    """
    Given quiet hours [start..end], compute the next time outside the window.
    Works whether window crosses midnight or not.
    """
    today = now.date()
    cur_t = now.time()
    if start <= end:
        # e.g., 20:00–22:00 (doesn't cross midnight)
        if start <= cur_t <= end:
            return datetime.combine(today, end) + timedelta(minutes=1)
        return now
    else:
        # e.g., 21:00–08:00 (crosses midnight)
        in_block = (cur_t >= start) or (cur_t <= end)
        if in_block:
            # If before end (after midnight), today at end; else next-day at end
            target_day = today if cur_t <= end else (today + timedelta(days=1))
            return datetime.combine(target_day, end) + timedelta(minutes=1)
        return now
