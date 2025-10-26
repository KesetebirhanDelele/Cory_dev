# app/orchestrator/temporal/activities/rag_redact.py
from __future__ import annotations
from typing import Any, Dict, List
from temporalio import activity
import re


@activity.defn(name="redact_enforce")
async def redact_enforce(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Apply redaction policies to retrieved text chunks.
    Removes or masks PII or sensitive terms before composition.

    Args:
        chunks: List of document chunk dictionaries.

    Returns:
        List of redacted chunks (same structure).
    """
    if not chunks:
        activity.logger.info("No chunks received for redaction.")
        return []

    activity.logger.info("Starting redaction | total_chunks=%d", len(chunks))

    redacted_chunks: List[Dict[str, Any]] = []
    total_replacements = 0

    # Simple redaction rules — expand these as policies evolve
    pii_patterns = [
        r"\b\d{3}-\d{2}-\d{4}\b",  # SSN pattern
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email
        r"\b\d{10}\b",  # Plain 10-digit numbers
    ]

    for c in chunks:
        text = c.get("content", "")
        original_text = text

        for pattern in pii_patterns:
            text, replacements = re.subn(pattern, "[REDACTED]", text)
            total_replacements += replacements

        if text != original_text:
            activity.logger.debug("Redacted content in doc_id=%s", c.get("doc_id"))

        redacted_chunks.append({
            "doc_id": c.get("doc_id"),
            "content": text.strip(),
            "score": c.get("score", 0)
        })

    activity.logger.info(
        "Redaction complete | total_chunks=%d | total_replacements=%d",
        len(redacted_chunks),
        total_replacements
    )

    return redacted_chunks
