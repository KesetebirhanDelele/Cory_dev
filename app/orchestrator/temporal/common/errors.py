# app/orchestrator/temporal/common/errors.py
from __future__ import annotations
from typing import Tuple, Optional

# ---- Canonical error classes ------------------------------------------------

class CoryError(Exception):
    code: str = "unknown"
    retryable: bool = False

    def __init__(self, message: str = ""):
        super().__init__(message)

class TimeoutError(CoryError):
    code, retryable = "timeout", True

class ThrottledError(CoryError):
    code, retryable = "throttled", True

class NetworkGlitchError(CoryError):
    code, retryable = "network_glitch", True

class PolicyDeniedError(CoryError):
    code, retryable = "policy_denied", False

class InvalidPayloadError(CoryError):
    code, retryable = "invalid_payload", False

class QuotaExhaustedError(CoryError):
    code, retryable = "quota_exhausted", False

class PermanentFailureError(CoryError):
    code, retryable = "permanent_failure", False

class BouncedError(CoryError):
    code, retryable = "bounced", False


# ---- Helpers used by activities/bridge -------------------------------------

def classify_exception(exc: BaseException) -> Tuple[str, bool]:
    """
    Return (code, retryable) for any exception.
    If it's a CoryError subclass, use its metadata.
    Otherwise, make a best-effort guess.
    """
    if isinstance(exc, CoryError):
        return exc.code, exc.retryable

    # Heuristics for non-Cory exceptions (keep minimal & deterministic)
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()

    if "timeout" in name or "timed out" in msg:
        return "timeout", True
    if "too many requests" in msg or "429" in msg or "rate limit" in msg:
        return "throttled", True
    if any(k in msg for k in ["connection reset", "dns", "ssl", "tls", "socket"]):
        return "network_glitch", True
    if any(k in msg for k in ["invalid", "schema", "payload", "template"]):
        return "invalid_payload", False
    if any(k in msg for k in ["bounce", "bounced", "550"]):
        return "bounced", False

    # Default: permanent failure
    return "permanent_failure", False


def is_retryable(exc: BaseException) -> bool:
    _, retry = classify_exception(exc)
    return retry
