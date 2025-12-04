# app/orchestrator/temporal/activities/email_send_dev.py
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, Tuple

from temporalio import activity

logger = logging.getLogger("cory.email.dev")

# ---------------------------------------------------------------------------
# Gmail SMTP configuration (set these in your .env)
# ---------------------------------------------------------------------------
SMTP_HOST = os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("GMAIL_SMTP_PORT", "587"))
SMTP_USER = os.getenv("GMAIL_USERNAME") or os.getenv("GMAIL_USER")
SMTP_PASS = os.getenv("GMAIL_APP_PASSWORD")


def _build_email(to_email: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def _send_sync_email(to_email: str, subject: str, body: str) -> None:
    """Blocking SMTP send; called via run_in_executor from the async activity."""
    msg = _build_email(to_email, subject, body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)


async def _send_email_via_gmail(to_email: str, subject: str, body: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _send_sync_email, to_email, subject, body)


def _normalize_args(*args, **kwargs) -> Tuple[str | None, Dict[str, Any]]:
    """
    Support both call styles:

    1) Legacy dev usage:
           email_send("user@example.com", "Subject", "Body")

    2) Activity usage (matches real email_send):
           email_send("enr_123", {"to": "...", "subject": "...", "body": "..."})
    """
    enrollment_id: str | None = None
    payload: Dict[str, Any] = {}

    # Pattern 2: (enrollment_id, payload_dict)
    if len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], dict):
        enrollment_id = args[0]
        payload = args[1]
        return enrollment_id, payload

    # Pattern 1: (recipient, subject, body)
    if len(args) == 3 and all(isinstance(a, str) for a in args):
        recipient, subject, body = args
        payload = {"to": recipient, "subject": subject, "body": body}
        return enrollment_id, payload

    # Fallback to kwargs if present
    enrollment_id = kwargs.get("enrollment_id")
    payload = kwargs.get("payload", {})
    return enrollment_id, payload


@activity.defn(name="email_send")
async def email_send(*args, **kwargs) -> Dict[str, Any]:
    """
    DEV email activity.

    In dev / local environments this is used instead of the Mandrill-backed
    implementation. It sends real emails via Gmail SMTP using your
    GMAIL_USERNAME + GMAIL_APP_PASSWORD.
    """
    enrollment_id, payload = _normalize_args(*args, **kwargs)

    to_email = (
        payload.get("to")
        or payload.get("email")
        or payload.get("recipient")
    )
    subject = payload.get("subject") or "Cory Test Email"
    body = payload.get("body") or payload.get("text") or "Hello from Cory dev."

    if not to_email:
        logger.warning("[EMAIL_DEV] No recipient email in payload: %r", payload)
        return {
            "channel": "email",
            "enrollment_id": enrollment_id,
            "status": "failed",
            "error": "missing_recipient",
            "request": payload,
        }

    # If SMTP creds aren't configured, don't crash – behave like a mock.
    if not (SMTP_USER and SMTP_PASS):
        logger.warning(
            "[EMAIL_DEV] SMTP credentials not set; pretending to send email "
            "to %s (set GMAIL_USERNAME and GMAIL_APP_PASSWORD to send for real).",
            to_email,
        )
        await asyncio.sleep(1)
        return {
            "channel": "email",
            "enrollment_id": enrollment_id,
            "status": "sent",
            "provider": "gmail-dev-mock",
            "request": payload,
        }

    try:
        await _send_email_via_gmail(to_email, subject, body)
        logger.info("[EMAIL_DEV] Sent email to %s subject=%s", to_email, subject)
        return {
            "channel": "email",
            "enrollment_id": enrollment_id,
            "status": "sent",
            "provider": "gmail",
            "request": payload,
        }
    except Exception as e:  # noqa: BLE001
        logger.error("[EMAIL_DEV] Error sending email: %s", e, exc_info=True)
        return {
            "channel": "email",
            "enrollment_id": enrollment_id,
            "status": "failed",
            "provider": "gmail",
            "error": str(e),
            "request": payload,
        }
