# app/orchestrator/temporal/activities/rag_compose.py
from __future__ import annotations
from typing import Any, Dict, List
from temporalio import activity


@activity.defn(name="compose_answer")
async def compose_answer(query: str, inbound_id: str, threshold: float) -> Dict[str, Any]:
    """
    Activity: Compose an answer to a user's query.
    This version aligns with the AnswerWorkflow call signature:
        compose_answer(query, inbound_id, threshold)

    Args:
        query: The question or prompt to answer.
        inbound_id: The inbound message or request ID.
        threshold: Matching threshold (float) for retrieval relevance.

    Returns:
        dict: {"answer": str, "citations": List[Dict]}
    """

    # --- Simulate chunk retrieval ---
    # In production, you'd pull RAG chunks or retrieve docs based on inbound_id.
    chunks: List[Dict[str, Any]] = [
        {"doc_id": "doc1", "content": "Office hours are 9am–5pm, Monday to Friday."},
        {"doc_id": "doc2", "content": "Refunds are processed within 7 business days."},
        {"doc_id": "doc3", "content": "Contact admissions@cory.ai for urgent queries."},
    ]

    question = query.strip()
    if not question:
        raise activity.ApplicationError("compose_answer: missing query text", non_retryable=True)

    # --- Generate an answer from mock docs ---
    top = chunks[:3]
    bulleted = "\n".join(f"- {c.get('content','').strip()[:400]}" for c in top)
    answer = (
        f"Question: “{question}”.\n\n"
        "Here’s what we found from the knowledge base:\n"
        f"{bulleted}\n\n"
        "If anything looks off, I can escalate this to a human advisor."
    )

    citations = [
        {"doc_id": c.get("doc_id"), "preview": (c.get("content", '')[:120]).strip()}
        for c in top
    ]

    return {"answer": answer, "citations": citations}
