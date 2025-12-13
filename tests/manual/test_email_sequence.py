# tests/manual/test_email_sequence.py
"""
Manual end-to-end email test with reply stop.

Behavior:
- Sends up to 5 emails, spaced 60s apart.
- Each email has a unique token in the subject.
- After each send, poll Gmail via IMAP for up to 60s.
- If a reply to that thread is detected, stop sending further emails.

Uses:
- SMTP_* / GMAIL_* env vars from .env
"""

from __future__ import annotations

import asyncio
import os
import smtplib
import ssl
import imaplib
import email
from email.message import EmailMessage
from datetime import datetime, timezone
from typing import Optional

SMTP_HOST = os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("GMAIL_SMTP_PORT", "587"))

USERNAME = os.getenv("GMAIL_USERNAME")
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

FROM_EMAIL = os.getenv("SMTP_FROM") or USERNAME
TO_EMAIL = os.getenv("GMAIL_TEST_TO") or USERNAME  # send to yourself by default

IMAP_HOST = os.getenv("GMAIL_IMAP_HOST", "imap.gmail.com")
IMAP_PORT = 993  # SSL

if not USERNAME or not APP_PASSWORD:
    raise RuntimeError("GMAIL_USERNAME and GMAIL_APP_PASSWORD must be set in .env")


# ---------------------------------------------------------------------------
# SMTP helper
# ---------------------------------------------------------------------------

async def send_smtp_email(to_email: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    def _send():
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(USERNAME, APP_PASSWORD)
            server.send_message(msg)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _send)


# ---------------------------------------------------------------------------
# IMAP helpers – check for reply
# ---------------------------------------------------------------------------

def _search_replies_sync(subject_token: str) -> bool:
    """
    Blocking IMAP search: look for any message whose Subject contains
    'Re:' and the given token. This is crude but good enough for testing.
    """
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        mail.login(USERNAME, APP_PASSWORD)
        mail.select("INBOX")

        # Search for all recent messages that mention our token in Subject
        typ, data = mail.search(None, 'SUBJECT', f'"{subject_token}"')
        if typ != "OK":
            return False

        ids = data[0].split()
        if not ids:
            return False

        # Check if any of these are replies (Subject starts with "Re:")
        for msg_id in ids:
            typ, msg_data = mail.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            subj = msg.get("Subject", "")
            if subj.lower().startswith("re:") and subject_token in subj:
                return True
        return False
    finally:
        try:
            mail.logout()
        except Exception:
            pass


async def wait_for_reply(subject_token: str, timeout: int = 60, poll_interval: int = 10) -> bool:
    """
    Poll IMAP every poll_interval seconds (up to timeout) looking for a reply.

    Returns True if a reply is detected, else False.
    """
    loop = asyncio.get_running_loop()
    deadline = datetime.now(timezone.utc).timestamp() + timeout

    while datetime.now(timezone.utc).timestamp() < deadline:
        has_reply = await loop.run_in_executor(None, _search_replies_sync, subject_token)
        if has_reply:
            return True
        await asyncio.sleep(poll_interval)

    return False


# ---------------------------------------------------------------------------
# Main test sequence
# ---------------------------------------------------------------------------

async def send_sequence():
    print(f"[INFO] Using recipient: {TO_EMAIL}")
    # Unique token for this run so we don't confuse old threads
    token = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    max_emails = 5
    delay_seconds = 60.0

    for i in range(1, max_emails + 1):
        subject_token = f"[Cory Test {token}]"
        subject = f"{subject_token} Nurture Email {i} of {max_emails}"
        body = (
            f"This is Cory test nurture email {i} of {max_emails}.\n\n"
            f"Run token: {token}\n"
            f"Reply to this email (just hit Reply) and I should stop sending "
            f"further emails in this sequence."
        )

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        print(f"[SEND] {now} – Sending email {i}/{max_emails}: {subject}")

        await send_smtp_email(TO_EMAIL, subject, body)
        print(f"[RESULT] {i}/{max_emails}: sent")

        # After each send except the last, wait for a reply
        if i < max_emails:
            print(f"[WAIT] Checking for reply for up to 60s (polling IMAP)...")
            replied = await wait_for_reply(subject_token)
            if replied:
                print(f"[STOP] Reply detected on thread token {subject_token}. Stopping sequence.")
                break
            else:
                print(f"[NO REPLY] No reply detected yet. Sleeping {delay_seconds} seconds before next email...")
                await asyncio.sleep(delay_seconds)
        else:
            print("[DONE] Sent final email; sequence complete.")

    print("[DONE] Script finished.")


if __name__ == "__main__":
    asyncio.run(send_sequence())
