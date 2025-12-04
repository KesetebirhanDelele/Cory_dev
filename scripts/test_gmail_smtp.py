# scripts/test_gmail_smtp.py
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from dotenv import load_dotenv


def main() -> None:
    # Load environment variables
    load_dotenv()

    host = os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("GMAIL_SMTP_PORT", "587"))

    username = os.getenv("GMAIL_USERNAME")
    password = os.getenv("GMAIL_APP_PASSWORD")
    from_email = os.getenv("SMTP_FROM") or username
    to_email = os.getenv("GMAIL_TEST_TO") or username  # send to yourself

    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    # Validate required fields
    if not username or not password:
        raise SystemExit(
            "❌ Missing GMAIL_USERNAME or GMAIL_APP_PASSWORD in .env.\n"
            "Please update .env with your Gmail app password."
        )

    print("\n=== Gmail SMTP Test ===")
    print(f"SMTP Host: {host}")
    print(f"SMTP Port: {port}")
    print(f"From: {from_email}")
    print(f"To: {to_email}")
    print(f"TLS: {use_tls}")
    print("========================\n")

    # Build email
    msg = EmailMessage()
    msg["Subject"] = "Cory_dev Gmail SMTP Test ✅"
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(
        "Hello!\n\n"
        "This is a test email from your Cory dev environment using Gmail SMTP.\n"
        "If you're reading this, SMTP login + sending works correctly.\n\n"
        "— Cory Dev\n"
    )

    print("📤 Sending email...")

    if use_tls:
        # TLS mode (STARTTLS on port 587)
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.login(username, password)
            server.send_message(msg)
    else:
        # SSL mode (port 465)
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as server:
            server.login(username, password)
            server.send_message(msg)

    print("✅ Email sent! Check your inbox (and spam/promotions).")


if __name__ == "__main__":
    main()
