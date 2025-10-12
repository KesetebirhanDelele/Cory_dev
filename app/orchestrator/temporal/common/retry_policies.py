# from datetime import timedelta

# SMS  = dict(start_to_close_timeout=timedelta(seconds=20), retry_policy={"maximum_attempts": 3, "backoff_coefficient": 2.0})
# EMAIL= dict(start_to_close_timeout=timedelta(seconds=20), retry_policy={"maximum_attempts": 3, "backoff_coefficient": 2.0})
# VOICE= dict(start_to_close_timeout=timedelta(seconds=30), retry_policy={"maximum_attempts": 2, "backoff_coefficient": 2.0})

# app/orchestrator/temporal/common/retry_policies.py
from __future__ import annotations
from datetime import timedelta

# -----------------------------------------------------------------------------
# Minimal, predictable retry configs per channel (keeps your original values)
# -----------------------------------------------------------------------------
SMS   = dict(
    start_to_close_timeout=timedelta(seconds=20),
    retry_policy={"maximum_attempts": 3, "backoff_coefficient": 2.0},
)
EMAIL = dict(
    start_to_close_timeout=timedelta(seconds=20),
    retry_policy={"maximum_attempts": 3, "backoff_coefficient": 2.0},
)
VOICE = dict(
    start_to_close_timeout=timedelta(seconds=30),
    retry_policy={"maximum_attempts": 2, "backoff_coefficient": 2.0},
)

CHANNEL_RETRY = {
    "sms": SMS,
    "email": EMAIL,
    "voice": VOICE,
}

def retry_for(channel: str) -> dict:
    """Helper to fetch the Temporal activity options for a given channel."""
    return CHANNEL_RETRY.get(channel, SMS)

# -----------------------------------------------------------------------------
# Tiny, clear error taxonomy for activities (use only if you need it)
# - Raise TransientError / RateLimitedError to let Temporal retry.
# - Raise NonRetryableError to stop retries immediately.
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
