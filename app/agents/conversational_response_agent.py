# app/agents/conversational_response_agent.py
"""
ConversationalResponseAgent
----------------------------------------------------------
- Classifies message intent into a shared set:
    - ready_to_enroll
    - interested_but_not_ready
    - unsure_or_declined
    - not_interested
    - callback_requested
    - unclassified
- Generates empathetic, contextual replies
- Returns a structured object:
    {
      "intent": "...",
      "response_message": "...",
      "next_action": "..."
    }
- Used by VoiceConversationAgent and inbound text workflows.
"""

import os
import json
import logging
from typing import Dict, Any, Optional

from dotenv import load_dotenv

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore

# ---------------------------------------------------------------------
# 🔧 Environment & Logging Setup
# ---------------------------------------------------------------------
load_dotenv()
logger = logging.getLogger("cory.conversational.agent")
logger.setLevel(logging.INFO)

ALLOWED_INTENTS = [
    "ready_to_enroll",
    "interested_but_not_ready",
    "unsure_or_declined",
    "not_interested",
    "callback_requested",
    "unclassified",
]

DEFAULT_NEXT_ACTION = {
    "ready_to_enroll": "schedule_appointment",
    "interested_but_not_ready": "start_nurture_campaign",
    "unsure_or_declined": "start_nurture_campaign",
    "not_interested": "stop_outreach",
    "callback_requested": "schedule_callback",
    "unclassified": "manual_review",
}


class ConversationalResponseAgent:
    """
    Handles inbound message conversations across channels
    (SMS, Email, WhatsApp, Voice transcripts), performs classification,
    and returns structured response objects for automation workflows.
    """

    def __init__(self) -> None:
        # --- OpenAI setup (optional) ---
        api_key = os.getenv("OPENAI_API_KEY")
        if OpenAI is not None and api_key:
            self.openai = OpenAI(api_key=api_key)
            self.use_llm = True
        else:
            if not api_key:
                logger.warning(
                    "OPENAI_API_KEY not set; ConversationalResponseAgent will use rule-based mode only."
                )
            self.openai = None
            self.use_llm = False

    # ------------------------------------------------------------------
    # 🔍 Public API
    # ------------------------------------------------------------------
    async def classify_message(self, text: str, channel: str = "sms") -> Dict[str, Any]:
        """
        Classify free-form text (e.g., SMS reply or call transcript) into intent and next_action.

        Returns:
            {
              "intent": "<one of ALLOWED_INTENTS>",
              "response_message": "<empathetic reply>",
              "next_action": "<system action string>"
            }
        """
        text = (text or "").strip()
        if not text:
            intent = "unclassified"
            return {
                "intent": intent,
                "response_message": "I’m here whenever you’re ready with questions about enrollment.",
                "next_action": DEFAULT_NEXT_ACTION[intent],
            }

        # 1️⃣ First pass: deterministic rule-based classification
        rule_result = self._rule_based_classify(text)

        # 2️⃣ Optional LLM refinement if configured
        if not self.use_llm:
            return rule_result

        try:
            llm_result = await self._llm_classify(text=text, channel=channel)
            intent = self._normalize_intent(llm_result.get("intent"))

            if intent in ALLOWED_INTENTS:
                response_message = (
                    llm_result.get("response_message") or rule_result["response_message"]
                )
                next_action = llm_result.get("next_action") or DEFAULT_NEXT_ACTION[intent]
                return {
                    "intent": intent,
                    "response_message": response_message,
                    "next_action": next_action,
                }
        except Exception as e:  # noqa: BLE001
            logger.exception("LLM classification failed; falling back to rule-based result: %s", e)

        return rule_result

    # ------------------------------------------------------------------
    # 🧩 Rule-based classifier (deterministic, testable)
    # ------------------------------------------------------------------
    def _rule_based_classify(self, text: str) -> Dict[str, Any]:
        """
        Simple keyword-based classifier that never calls the LLM.
        This guarantees a valid result even in offline/dev environments.
        """
        lowered = text.lower()

        # Ready to enroll / wants to apply / wants to be admitted
        if any(
            kw in lowered
            for kw in [
                "ready to enroll",
                "ready to apply",
                "i want to enroll",
                "get admitted",
                "register now",
                "i want to get admitted",
            ]
        ):
            intent = "ready_to_enroll"
            response = (
                "That’s wonderful! I can help you with the next steps to enroll. "
                "Would you like to schedule a quick call or handle everything online?"
            )

        # Callback requested / phone follow-up
        elif any(
            kw in lowered
            for kw in [
                "call me back",
                "call me later",
                "can you call",
                "give me a call",
                "phone call",
                "reach me by phone",
            ]
        ):
            intent = "callback_requested"
            response = (
                "Thanks for letting me know! I can arrange a callback. "
                "Is there a specific day and time that works best for you?"
            )

        # Not interested / stop outreach
        elif any(
            kw in lowered
            for kw in [
                "not interested",
                "no longer interested",
                "stop contacting",
                "please stop",
                "do not contact",
                "dont contact",
                "unsubscribe",
            ]
        ):
            intent = "not_interested"
            response = (
                "Thanks for telling me. I’ll update your preferences and stop outreach. "
                "If you change your mind in the future, we’ll be glad to help."
            )

        # Interested but not ready yet (needs time, later, thinking)
        elif any(
            kw in lowered
            for kw in [
                "not ready",
                "maybe later",
                "need more time",
                "still deciding",
                "thinking about it",
                "later this year",
            ]
        ):
            intent = "interested_but_not_ready"
            response = (
                "No problem at all—this is an important decision. "
                "Would it help if I sent you a few more details "
                "about the program and your options?"
            )

        # Unsure / declined / has concerns
        elif any(
            kw in lowered
            for kw in [
                "not sure",
                "unsure",
                "i don't know",
                "i dont know",
                "have some concerns",
                "on the fence",
                "hesitant",
            ]
        ):
            intent = "unsure_or_declined"
            response = (
                "I understand—there can be a lot to consider. "
                "What questions or concerns do you have about the program or enrollment process?"
            )

        else:
            intent = "unclassified"
            response = (
                "Thanks for your message. I want to make sure I understand you correctly—"
                "could you share a bit more about where you are in your decision to enroll?"
            )

        next_action = DEFAULT_NEXT_ACTION[intent]
        return {
            "intent": intent,
            "response_message": response,
            "next_action": next_action,
        }

    # ------------------------------------------------------------------
    # 🤖 LLM helper (optional)
    # ------------------------------------------------------------------
    async def _llm_classify(self, text: str, channel: str = "sms") -> Dict[str, Any]:
        """
        Ask the LLM to classify the message into one of ALLOWED_INTENTS
        and suggest a response + next_action. Returns parsed JSON.
        """
        if not self.openai:
            raise RuntimeError("OpenAI client not configured")

        system_prompt = (
            "You are an admissions assistant helping classify student messages.\n"
            "Your job is to:\n"
            "1. Decide the student's intent using ONLY one of these values:\n"
            f"   {', '.join(ALLOWED_INTENTS)}\n"
            "2. Write a short, friendly response in the same style as a human admissions counselor.\n"
            "3. Suggest a next_action for the system to take, such as:\n"
            "- schedule_appointment\n"
            "- start_nurture_campaign\n"
            "- schedule_callback\n"
            "- stop_outreach\n"
            "- manual_review\n\n"
            "Respond ONLY with a JSON object with keys: intent, response_message, next_action."
        )

        user_prompt = f"Channel: {channel}\nStudent message:\n{text}"

        resp = self.openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=200,
        )

        raw = (resp.choices[0].message.content or "").strip()

        # If the model wraps JSON in ```json blocks, strip them
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()

        try:
            parsed = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to parse LLM JSON, raw=%r error=%s", raw[:200], e)
            return {}

        return parsed

    # ------------------------------------------------------------------
    # 🧹 Utility
    # ------------------------------------------------------------------
    def _normalize_intent(self, intent: Optional[str]) -> str:
        """Normalize LLM-returned intent into the allowed set."""
        if not intent:
            return "unclassified"
        normalized = intent.strip().lower()

        if normalized in ALLOWED_INTENTS:
            return normalized

        if "ready" in normalized and "enroll" in normalized:
            return "ready_to_enroll"
        if "not ready" in normalized or "later" in normalized:
            return "interested_but_not_ready"
        if "callback" in normalized or "call back" in normalized:
            return "callback_requested"
        if "not interested" in normalized:
            return "not_interested"
        if "unsure" in normalized or "decline" in normalized:
            return "unsure_or_declined"

        return "unclassified"
