# app/orchestrator/temporal/activities/rag_redact.py
from __future__ import annotations
from typing import Any, Dict
from temporalio import activity
import re


@activity.defn(name="redact_enforce")
async def redact_enforce(draft: Dict[str, Any]) -> Dict[str, Any]:
    """
    Redact PII or sensitive information from the composed answer.

    Expected input:
        {
            "answer": str,
            "citations": [...]
        }

    Returns:
        {
            "answer": str,
            "confidence": float
        }
    """

    answer = draft.get("answer", "")
    if not answer:
        activity.logger.warning("redact_enforce received empty answer")
        return {"answer": "", "confidence": 0.0}

    activity.logger.info("Starting redaction on composed answer")

    # Basic redaction patterns
    pii_patterns = [
        r"\b\d{3}-\d{2}-\d{4}\b",                        # SSN
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",  # Email
        r"\b\d{10}\b",                                   # 10-digit phone
    ]

    redacted_text = answer
    total_replacements = 0

    for pattern in pii_patterns:
        redacted_text, replacements = re.subn(pattern, "[REDACTED]", redacted_text)
        total_replacements += replacements

    if total_replacements > 0:
        activity.logger.info("🔒 Redaction applied (%d replacements)", total_replacements)
    else:
        activity.logger.info("No PII found to redact in answer")

    # NOTE: Assigning confidence can be replaced later with a real scorer
    confidence = draft.get("confidence", 0.85)

    return {
        "answer": redacted_text.strip(),
        "confidence": confidence,
    }
