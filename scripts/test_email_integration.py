# scripts/test_email_integration.py
from __future__ import annotations

"""
Ad-hoc integration test for outbound email using Gmail SMTP.

What it does:
- Looks up a registration by id in Supabase
- Reads the `email` column
- Sends 5 emails, 1 minute apart, to that address via Gmail

Prereqs:
- Supabase env vars set (SUPABASE_URL, SUPABASE_SERVICE_ROLE / *_KEY, SUPABASE_SCHEMA)
- A row in `registrations` with your Gmail in the `email` column
- Gmail app password (NOT your normal password)

Usage (from repo root, venv active):

    export TEST_REGISTRATION_ID=<your_registration_id>
    export GMAIL_SMTP_USER="<your_gmail_address>"
    export GMAIL_SMTP_PASS="<your_app_password>"

    python scripts/test_email_integration.py

On Windows PowerShell:

    $env:TEST_REGISTRATION_ID="<id>"
    $env:GMAIL_SMTP_USER="<you@gmail.com>"
    $env:GMAIL_SMTP_PASS="<app-password>"

    python scripts/test_email_integration.py
"""

import asyncio
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

import httpx

from app.data.supabase_repo import _cfg, _headers  # reuse existing helpers


# -------------------------------------------------------------
# Supabase helpers (read email address from registrations)
# -------------------------------------------------------------
async def get_registration_email(registration_id: str) -> Optional[str]:
    """Fetch the `email` field from registrations for the given id."""
    url, key, schema = _cfg()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{url}/rest/v1/registrations"
            f"?id=eq.{registration_id}&select=email",
            headers={**_headers(key), "Accept-Profile": schema},
        )

    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None

    email = rows[0].get("email")
    return email


# -------------------------------------------------------------
# Gmail SMTP sender
# -------------------------------------------------------------
def send_email_smtp(to_email: str, subject: str, body: str) -> None:
    """
    Send a single email via Gmail SMTP.

    Requires:
      - GMAIL_SMTP_USER
      - GMAIL_SMTP_PASS  (Gmail app password)
    """
    user = os.environ["GMAIL_SMTP_USER"]
    password = os.environ["GMAIL_SMTP_PASS"]

    host = os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("GMAIL_SMTP_PORT", "587"))

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)


# -------------------------------------------------------------
# Main integration flow
# -------------------------------------------------------------
async def main() -> None:
    registration_id = os.environ.get("TEST_REGISTRATION_ID")
    if not registration_id:
        raise SystemExit(
            "TEST_REGISTRATION_ID env var is required. "
            "Set it to the registrations.id that contains your Gmail."
        )

    print(f"[email-integration] Looking up registration {registration_id}...")
    email = await get_registration_email(registration_id)

    if not email:
        raise SystemExit(
            f"No email found for registrations.id={registration_id}. "
            "Check that the row exists and has an `email` column populated."
        )

    print(f"[email-integration] Will send test emails to: {email}")

    # Send 5 emails, 1 minute apart
    for i in range(1, 6):
        subject = f"Cory Test Email #{i}"
        body = (
            f"Hi from Cory test #{i}.\n\n"
            f"This is an automated integration test email.\n"
            f"Registration id: {registration_id}\n"
        )

        print(f"[email-integration] Sending email {i}/5...")
        # run blocking SMTP in a thread to keep asyncio happy
        await asyncio.to_thread(send_email_smtp, email, subject, body)
        print(f"[email-integration] Email {i} sent.")

        if i < 5:
            print("[email-integration] Sleeping 60s before next email...")
            await asyncio.sleep(60)

    print("[email-integration] Done. Check your Gmail inbox.")


if __name__ == "__main__":
    asyncio.run(main())
