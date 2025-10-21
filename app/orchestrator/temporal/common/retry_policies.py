# app/orchestrator/temporal/common/retry_policies.py
from __future__ import annotations

from datetime import timedelta
from typing import Dict, Tuple

from temporalio.common import RetryPolicy

# -----------------------------------------------------------------------------
# Error taxonomy for activities
# -----------------------------------------------------------------------------

class ActivityError(Exception):
    """Base class for activity errors."""


class TransientError(ActivityError):
    """Retryable: network hiccup / 5xx / intermittent provider issue."""
    pass


class RateLimitedError(ActivityError):
    """Retryable after a delay; Temporal retry/backoff should handle it."""
    def __init__(self, message: str = "rate limited", retry_after_seconds: int = 60):
        super().__init__(message)
        self.retry_after_seconds = int(retry_after_seconds)


class NonRetryableError(ActivityError):
    """Do not retry: invalid recipient, DNC, bad request, permanent failure."""
    pass


# -----------------------------------------------------------------------------
# Channel defaults (central source of truth)
# -----------------------------------------------------------------------------
# stc = start_to_close timeout (seconds)
_DEFAULTS = {
    "sms":   dict(stc=30, initial=1.0, backoff=2.0, max_interval=15.0, max_attempts=4),
    "email": dict(stc=30, initial=2.0, backoff=2.0, max_interval=30.0, max_attempts=3),
    "voice": dict(stc=60, initial=2.0, backoff=2.0, max_interval=20.0, max_attempts=3),
}

# Error types that must NEVER retry (Temporal matches by exception class name)
_NON_RETRYABLE_TYPES = [
    "PolicyDeniedError",
    "InvalidPayloadError",
    "QuotaExhaustedError",
    "PermanentFailureError",
    "BouncedError",
    "NonRetryableError",   # include local taxonomy too
]


def activity_options_for(channel: str) -> Tuple[Dict, RetryPolicy]:
    """
    Returns (**kwargs for workflow.execute_activity**, RetryPolicy) for a given channel.

    Example:
        opts, rp = activity_options_for("sms")
        await workflow.execute_activity(..., retry_policy=rp, **opts)
    """
    c = (channel or "").lower()
    cfg = _DEFAULTS.get(c, _DEFAULTS["sms"])

    rp = RetryPolicy(
        initial_interval=timedelta(seconds=cfg["initial"]),
        backoff_coefficient=cfg["backoff"],
        maximum_interval=timedelta(seconds=cfg["max_interval"]),
        maximum_attempts=cfg["max_attempts"],
        non_retryable_error_types=_NON_RETRYABLE_TYPES,
    )
    opts: Dict = {"start_to_close_timeout": timedelta(seconds=cfg["stc"])}
    return opts, rp


# -----------------------------------------------------------------------------
# Back-compat helper (older call sites may expect a single dict)
# -----------------------------------------------------------------------------

def retry_for(channel: str) -> Dict:
    """
    Back-compat shim: returns a dict with 'start_to_close_timeout' and 'retry_policy'
    so older code can do: execute_activity(..., **retry_for("sms"))
    """
    opts, rp = activity_options_for(channel)
    return {**opts, "retry_policy": rp}
