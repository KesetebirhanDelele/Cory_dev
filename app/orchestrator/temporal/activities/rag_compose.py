# app/orchestrator/temporal/activities/rag_compose.py
from __future__ import annotations
from typing import Any, Dict, List
from temporalio import activity

@activity.defn(name="compose_answer")
async def compose_answer(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compose an AI-style answer from retrieved and redacted content.
    args = {"question": str, "chunks": List[Dict]}
    Returns: {"answer": str, "citations": List[Dict]}
    """
    question: str = args.get("question", "").strip()
    chunks: List[Dict[str, Any]] = args.get("chunks") or []

    if not question:
        raise activity.ApplicationError("compose_answer: missing 'question'", non_retryable=True)

    if not chunks:
        answer = (
            f"Here’s what I can share for: “{question}”. "
            "I don’t have any documents on this yet. Would you like me to hand this to a human?"
        )
        citations: List[Dict[str, Any]] = []
    else:
        top = chunks[:3]
        bulleted = "\n".join(f"- {c.get('content','').strip()[:400]}" for c in top)
        answer = (
            f"Question: “{question}”.\n\n"
            "From our docs, here’s what’s relevant:\n"
            f"{bulleted}\n\n"
            "If anything looks off, we can route to a human."
        )
        citations = [
            {"doc_id": c.get("doc_id"), "preview": (c.get("content","")[:120]).strip()}
            for c in top
        ]

    activity.logger.info("✅ Composed answer for question: %s", question)
    return {"answer": answer, "citations": citations}
