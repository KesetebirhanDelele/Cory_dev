from __future__ import annotations
import re
from typing import Any, Dict, List
from temporalio import activity

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d[\s\-\.()]*){7,}")  # rough mask for dev

def _mask(text: str) -> tuple[str, List[str]]:
    log: List[str] = []
    def _do(regex, label):
        nonlocal text, log
        def repl(m):
            log.append(f"{label}: {m.group(0)}")
            return "[REDACTED]"
        text = regex.sub(repl, text)
    _do(EMAIL_RE, "email")
    _do(PHONE_RE, "phone")
    return text, log

@activity.defn(name="redact_enforce")
async def redact_enforce(draft: Dict[str, Any]) -> Dict[str, Any]:
    """
    Input: {"answer": str, "citations": [...]}
    Output: {"answer": str, "citations": [...], "confidence": float, "redaction_log": [...]}
    """
    if not isinstance(draft, dict) or "answer" not in draft:
        raise activity.ApplicationError("redact_enforce: bad input", non_retryable=True)

    answer = str(draft["answer"])
    redacted, log = _mask(answer)

    # naive confidence: more sources -> higher confidence
    cites = draft.get("citations") or []
    n = max(0, min(3, len(cites)))
    confidence = {0: 0.35, 1: 0.6, 2: 0.75, 3: 0.88}[n]

    out = dict(draft)
    out.update({"answer": redacted, "confidence": confidence, "redaction_log": log})
    return out
