# tests/integration/test_activity_retries.py
from datetime import timedelta
from temporalio.common import RetryPolicy

from app.orchestrator.temporal.common.retry_policies import activity_options_for
from app.orchestrator.temporal.common.errors import (
    TimeoutError, ThrottledError, NetworkGlitchError,
    PolicyDeniedError, InvalidPayloadError, PermanentFailureError, BouncedError,
    classify_exception, is_retryable,
)

def test_policy_shapes_per_channel():
    for ch in ["sms", "email", "voice"]:
        opts, rp = activity_options_for(ch)
        assert "start_to_close_timeout" in opts
        assert isinstance(opts["start_to_close_timeout"], timedelta)
        assert isinstance(rp, RetryPolicy)
        assert rp.maximum_attempts >= 3

def test_transient_errors_are_retryable():
    for exc in [TimeoutError(), ThrottledError(), NetworkGlitchError()]:
        code, retry = classify_exception(exc)
        assert retry, f"{code} should be retryable"
        assert is_retryable(exc) is True

def test_non_retryable_errors_fail_fast():
    for exc in [PolicyDeniedError(), InvalidPayloadError(), PermanentFailureError(), BouncedError()]:
        code, retry = classify_exception(exc)
        assert retry is False
        assert is_retryable(exc) is False

def test_non_retryables_are_in_policy_list():
    _, rp = activity_options_for("sms")
    non_retryables = set(rp.non_retryable_error_types or [])
    # Verify policy includes our canonical non-retryables by class name
    for cls in [PolicyDeniedError, InvalidPayloadError, PermanentFailureError, BouncedError]:
        assert cls.__name__ in non_retryables
