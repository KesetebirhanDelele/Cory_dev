# app/common/tracing.py
from __future__ import annotations
import logging, uuid
from contextvars import ContextVar
from typing import Optional, Callable

_TRACE_ID: ContextVar[Optional[str]] = ContextVar("_TRACE_ID", default=None)

def new_trace_id() -> str:
    return str(uuid.uuid4())

def get_trace_id() -> Optional[str]:
    return _TRACE_ID.get()

def set_trace_id(value: Optional[str]) -> None:
    _TRACE_ID.set(value)

def _install_logrecord_factory() -> None:
    """Ensure every LogRecord has .trace_id (even for 3rd-party loggers)."""
    old_factory: Callable[..., logging.LogRecord] = logging.getLogRecordFactory()  # type: ignore

    def record_factory(*args, **kwargs) -> logging.LogRecord:  # type: ignore
        record = old_factory(*args, **kwargs)
        # If any handler/formatter expects trace_id, provide a safe default.
        if not hasattr(record, "trace_id"):
            record.trace_id = get_trace_id() or "-"
        return record

    logging.setLogRecordFactory(record_factory)

def setup_logging(level: int = logging.INFO) -> None:
    """Set a format that includes trace_id and install the factory."""
    _install_logrecord_factory()
    fmt = "%(asctime)s %(levelname)s %(name)s [trace=%(trace_id)s]: %(message)s"
    logging.basicConfig(level=level, format=fmt)
