# app/orchestrator/temporal/activities/rag_compose.py
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from temporalio import activity
from temporalio.exceptions import ApplicationError


def _normalize_metadata(raw: Any) -> Dict[str, Any]:
    """
    Make sure metadata is always a dict.

    Handles:
    - dict (already good)
    - JSON string (e.g. '{"topic": "programs"}')
    - plain string (ignored)
    - None
    """
    if isinstance(raw, dict):
        return raw

    if raw is None:
        return {}

    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        # Try to parse JSON; if it fails, just ignore.
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    # Anything else → ignore
    return {}


def _any_in(text: str, needles: List[str]) -> bool:
    text = text.lower()
    return any(n in text for n in needles)


def _score_chunk(chunk: Dict[str, Any], question: str) -> float:
    """
    Heuristic scoring to pick the most relevant chunks for the question.

    Uses:
    - vector rank (if present)
    - question/topic-specific keyword boosts
    - lexical overlap between question and chunk content
    - lightweight use of metadata (topic/section), but safely
    """
    q = (question or "").lower()
    content = str(chunk.get("content", "") or "").lower()

    meta = _normalize_metadata(chunk.get("metadata"))
    topic = str(meta.get("topic", "") or "").lower()
    section = str(meta.get("section", "") or "").lower()

    score = 0.0

    # 1) If vector search provided a rank, use it as a base signal
    base_rank = chunk.get("rank")
    if base_rank is not None:
        try:
            score += float(base_rank)
        except (TypeError, ValueError):
            pass

    # 2) Intent-specific boosts

    # Registration / how to get started
    if _any_in(q, ["register", "registration", "enroll", "enrollment", "apply", "application", "get started"]):
        if _any_in(content, ["register", "registration", "enroll", "enrollment", "apply", "application"]):
            score += 5.0
        if _any_in(topic + " " + section, ["registration", "how_to_register"]):
            score += 3.0

    # Cost / tuition / payment
    if _any_in(q, ["cost", "price", "tuition", "pay", "payment", "fee", "fees"]):
        if _any_in(content, ["tuition", "cost", "price", "payment", "installment", "pay", "fees"]):
            score += 5.0
        if _any_in(topic + " " + section, ["tuition", "financial", "financial_aid"]):
            score += 3.0

    # Programs / classes / courses
    if _any_in(q, ["class", "classes", "course", "courses", "program", "programs", "bootcamp", "training"]):
        if _any_in(
            content,
            [
                "program",
                "programs",
                "bootcamp",
                "course",
                "courses",
                "training",
                "data analytics",
                "data science",
            ],
        ):
            score += 3.0
        if _any_in(topic + " " + section, ["programs", "programs_overview"]):
            score += 2.0

    # Data / analytics / BI tooling
    if _any_in(
        q,
        [
            "data analytics",
            "data science",
            "analytics",
            "power bi",
            "powerbi",
            "sql",
            "python",
            "tableau",
            "bi",
        ],
    ):
        if _any_in(
            content,
            [
                "data analytics",
                "data science",
                "power bi",
                "sql",
                "python",
                "tableau",
                "data visualization",
            ],
        ):
            score += 3.0

    # 3) General lexical overlap between question and chunk content
    q_tokens = set(re.findall(r"\w+", q))
    c_tokens = set(re.findall(r"\w+", content))
    if q_tokens and c_tokens:
        overlap = len(q_tokens & c_tokens)
        # Cap to avoid giant scores
        score += min(overlap, 20) * 0.2

    # 4) Light bonus for overlap with metadata topic/section
    meta_text = f"{topic} {section}"
    m_tokens = set(re.findall(r"\w+", meta_text))
    if q_tokens and m_tokens:
        m_overlap = len(q_tokens & m_tokens)
        score += min(m_overlap, 10) * 0.3

    return score


@activity.defn(name="compose_answer")
async def compose_answer(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compose an answer based on the user's question and retrieved chunks.

    Expected input:
        {
            "question": str,
            "chunks": List[Dict]
        }

    Returns:
        {
            "answer": str,
            "citations": List[Dict]
        }
    """
    # --- Extract and validate ---
    question: str = (args.get("question") or "").strip()
    chunks: List[Dict[str, Any]] = args.get("chunks") or []

    if not question:
        raise ApplicationError("compose_answer: missing 'question'", non_retryable=True)

    # --- No RAG docs found ---
    if not chunks:
        activity.logger.info("⚠️ No chunks provided — returning fallback answer")
        answer = (
            "I don’t have enough information in my knowledge base to answer that yet. "
            "A team member will follow up with more details."
        )
        return {"answer": answer, "citations": []}

    # --- Rank chunks by relevance to the question ---
    ranked_chunks = sorted(
        chunks,
        key=lambda c: _score_chunk(c, question),
        reverse=True,
    )

    top = ranked_chunks[:3]

    # Collect clean snippets from chunk content
    snippets: List[str] = [
        str(c.get("content", "")).strip()
        for c in top
        if c.get("content")
    ]

    if not snippets:
        # Extremely defensive fallback
        activity.logger.warning(
            "compose_answer: chunks present but no usable content; falling back"
        )
        answer = (
            "I’m not able to extract a clear answer from the available documents. "
            "A team member will follow up with more details."
        )
        return {"answer": answer, "citations": []}

    # ✅ Just return stitched content, no boilerplate question header
    answer = "\n\n".join(snippets)

    citations = [
        {
            "doc_id": c.get("doc_id"),
            "title": c.get("title"),
            "source": c.get("source"),
            "preview": str(c.get("content", "")).strip()[:120],
            "metadata": _normalize_metadata(c.get("metadata")),
        }
        for c in top
    ]

    activity.logger.info("✅ Composed answer for question: %s", question)
    return {"answer": answer, "citations": citations}
