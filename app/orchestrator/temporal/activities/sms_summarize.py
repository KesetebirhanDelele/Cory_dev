# app/orchestrator/temporal/activities/sms_summarize.py
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

# Optional: if you later want to delegate to the existing conversational agent,
# you can import it here and call it inside this activity instead of (or in
# addition to) the direct LLM call.
try:
    # EXAMPLE ONLY – adjust to your actual module / function names if needed.
    # from app.agents.conversational_response_agent import ConversationalResponseAgent
    ConversationalResponseAgent = None  # type: ignore
except Exception:  # pragma: no cover
    ConversationalResponseAgent = None  # type: ignore


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
SMS_SUMMARIZER_MODEL = os.getenv("CORY_SMS_SUMMARIZER_MODEL", "gpt-4o-mini")


def _ensure_openai_config() -> None:
    if not OPENAI_API_KEY:
        raise ApplicationError(
            "sms_summarize_answer: OPENAI_API_KEY is not set",
            non_retryable=True,
        )


async def _call_openai_chat(
    question: str,
    answer: str,
    history: Optional[List[Dict[str, Any]]] = None,
    max_chars: int = 480,
) -> Dict[str, Any]:
    """
    Call OpenAI Chat Completions to:
      - Tame the RAG answer into SMS-sized, conversational text
      - Classify intent
      - Suggest a next_action

    Returns strict JSON with keys:
      - sms_text: str
      - intent: str
      - next_action: str
    """
    _ensure_openai_config()

    # Simple, opinionated intent + next_action space.
    # You can expand these later if needed.
    intent_options = [
        "general_question",
        "program_info",
        "tuition_financial",
        "registration_help",
        "schedule_timing",
        "career_outcomes",
        "other",
    ]

    next_action_options = [
        "answer_only",           # just reply; nothing else needed
        "offer_call",            # ask if they want a call with an advisor
        "send_link",             # send them a link (e.g., application or FAQ)
        "handoff_to_human",      # escalate to human
        "ask_clarifying_question",
    ]

    system_prompt = (
        "You are Cory, an SMS-based admissions assistant for a college-style "
        "program (here, Colaberry). You receive:\n"
        " - The user's latest question\n"
        " - A knowledge-base answer (RAG output)\n\n"
        "Your job is to:\n"
        "1) Turn the answer into a SHORT, friendly SMS reply.\n"
        f"   - It MUST be <= {max_chars} characters.\n"
        "   - It should sound human, clear, and helpful.\n"
        "   - No markdown formatting, no bullet points, no headings.\n"
        "   - It's OK to mention Colaberry by name.\n\n"
        "2) Infer the user's high-level intent from this fixed list:\n"
        f"   - {', '.join(intent_options)}\n\n"
        "3) Choose the single most appropriate next_action from this list:\n"
        f"   - {', '.join(next_action_options)}\n\n"
        "4) Return ONLY valid JSON with the following shape:\n"
        '{\n'
        '  "sms_text": "short SMS-friendly reply (<= max_chars)",\n'
        '  "intent": "one of the allowed intent strings",\n'
        '  "next_action": "one of the allowed next_action strings"\n'
        '}\n\n'
        "Do NOT include explanations, markdown, or any other keys.\n"
    )

    # Optionally include prior turns into context – for now, keep simple:
    user_content = {
        "question": question,
        "rag_answer": answer,
    }
    if history:
        user_content["history"] = history

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(user_content, ensure_ascii=False),
        },
    ]

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "model": SMS_SUMMARIZER_MODEL,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 256,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            activity.logger.error(
                "sms_summarize_answer: OpenAI error | status=%s body=%s",
                e.response.status_code if e.response else "unknown",
                e.response.text if e.response else "no-body",
            )
            raise ApplicationError(
                f"sms_summarize_answer: OpenAI HTTP error {e.response.status_code if e.response else 'unknown'}",
                non_retryable=False,
            )

        data = resp.json()
        if not isinstance(data, dict):
            raise ApplicationError(
                "sms_summarize_answer: unexpected OpenAI response format",
                non_retryable=False,
            )

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            raise ApplicationError(
                f"sms_summarize_answer: missing choices/message/content ({e})",
                non_retryable=False,
            )

        # The model should return JSON text; parse it defensively
        try:
            parsed = json.loads(content)
        except Exception:
            activity.logger.warning(
                "sms_summarize_answer: model did not return valid JSON, "
                "wrapping raw text as sms_text"
            )
            return {
                "sms_text": str(content)[:max_chars],
                "intent": "other",
                "next_action": "answer_only",
            }

        sms_text = str(parsed.get("sms_text", "")).strip()
        intent = str(parsed.get("intent", "other")).strip() or "other"
        next_action = str(parsed.get("next_action", "answer_only")).strip() or "answer_only"

        # Final safety trims
        if len(sms_text) > max_chars:
            sms_text = sms_text[: max_chars - 3].rstrip() + "..."

        return {
            "sms_text": sms_text,
            "intent": intent,
            "next_action": next_action,
        }


@activity.defn(name="sms_summarize_answer")
async def sms_summarize_answer(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Temporal activity that:
      1) Takes a RAG-generated answer
      2) Produces an SMS-sized, conversational reply
      3) Adds intent + next_action for downstream orchestration

    Expected input:
        {
            "question": str,
            "answer": str,
            "history": Optional[List[Dict[str, Any]]],  # optional
            "max_chars": Optional[int]                  # default ~480
        }

    Returns:
        {
            "sms_text": str,
            "intent": str,
            "next_action": str,
        }
    """
    question = (args.get("question") or "").strip()
    answer = (args.get("answer") or "").strip()
    history: Optional[List[Dict[str, Any]]] = args.get("history")  # type: ignore[assignment]
    max_chars = int(args.get("max_chars") or 480)

    if not question:
        raise ApplicationError(
            "sms_summarize_answer: missing 'question'",
            non_retryable=True,
        )
    if not answer:
        # If RAG returned nothing, we can still respond politely.
        activity.logger.info(
            "sms_summarize_answer: empty 'answer' provided, generating fallback SMS"
        )
        fallback = (
            "I don’t have a clear answer in my notes yet, but I can connect you "
            "with an admissions advisor for more details."
        )
        if len(fallback) > max_chars:
            fallback = fallback[: max_chars - 3].rstrip() + "..."

        return {
            "sms_text": fallback,
            "intent": "other",
            "next_action": "handoff_to_human",
        }

    activity.logger.info("sms_summarize_answer: summarizing RAG answer for SMS")

    # For now, we go directly through OpenAI.
    # If you later want to explicitly reuse the ConversationalResponseAgent,
    # you can plug it in here instead of or alongside this call.
    result = await _call_openai_chat(
        question=question,
        answer=answer,
        history=history,
        max_chars=max_chars,
    )

    activity.logger.info(
        "sms_summarize_answer: done | intent=%s next_action=%s",
        result.get("intent"),
        result.get("next_action"),
    )
    return result
