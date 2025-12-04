# scripts/test_email_integration_flow.py
from __future__ import annotations

import os
import smtplib
import ssl
import time
from email.message import EmailMessage

from dotenv import load_dotenv


def _get_smtp_client(host: str, port: int, username: str, password: str, use_tls: bool):
    """Return a connected SMTP client (STARTTLS or SSL)."""
    context = ssl.create_default_context()
    if use_tls:
        server = smtplib.SMTP(host, port)
        server.ehlo()
        server.starttls(context=context)
        server.login(username, password)
        return server
    else:
        # SSL mode (e.g. port 465)
        server = smtplib.SMTP_SSL(host, port, context=context)
        server.login(username, password)
        return server


def _send_email(
    server: smtplib.SMTP,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(body)
    server.send_message(msg)


def main() -> None:
    load_dotenv()

    host = os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("GMAIL_SMTP_PORT", "587"))
    username = os.getenv("GMAIL_USERNAME")
    password = os.getenv("GMAIL_APP_PASSWORD")
    from_email = os.getenv("SMTP_FROM") or username
    to_email = os.getenv("GMAIL_TEST_TO") or username  # send to yourself by default
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    if not username or not password:
        raise SystemExit(
            "❌ Missing GMAIL_USERNAME or GMAIL_APP_PASSWORD in .env. "
            "Please set them before running this script."
        )

    # "Stored data" about the student that Cory will use when replying.
    student_name = os.getenv("TEST_STUDENT_NAME", "Nikhil")
    program = os.getenv("TEST_PROGRAM", "Computer Science")
    start_term = os.getenv("TEST_START_TERM", "Fall 2025")

    print("\n=== Cory Email Integration Flow ===")
    print(f"SMTP Host: {host}")
    print(f"SMTP Port: {port}")
    print(f"From:      {from_email}")
    print(f"To:        {to_email}")
    print(f"TLS:       {use_tls}")
    print("-----------------------------------")
    print("This script will send up to 5 emails, 1 minute apart.")
    print("After each email, you can mark that the student replied.")
    print("If you say 'y', Cory sends a personalized reply and stops.\n")

    # Prepare the 5-touch sequence (slightly different messages each time)
    touches = [
        f"Hi {student_name}, just checking in about your interest in {program}.",
        f"Hi {student_name}, we’d love to help you get started for {start_term}.",
        f"{student_name}, do you have any questions about {program} or next steps?",
        f"Quick reminder, {student_name}: we’re here to help you enroll for {start_term}.",
        f"Last nudge, {student_name} — would you like help finishing your application?",
    ]

    server = _get_smtp_client(host, port, username, password, use_tls)

    try:
        for idx, body in enumerate(touches, start=1):
            subject = f"[Cory Test] Touch {idx}/5 about your {program} interest"

            print(f"📤 Sending touch {idx}/5 to {to_email} ...")
            _send_email(
                server,
                from_email=from_email,
                to_email=to_email,
                subject=subject,
                body=(
                    body
                    + "\n\n"
                    "If you reply to this email, imagine a student saying 'Yes, I’m interested.'"
                ),
            )
            print("✅ Email sent. Check your Gmail inbox.")

            # Ask operator if the student has replied yet
            answer = input("Has the student replied yet? [y/N]: ").strip().lower()
            if answer == "y":
                print("🟢 Student replied — sending Cory’s personalized follow-up...")
                reply_subject = f"[Cory Test] Thanks for your interest in {program}!"
                reply_body = (
                    f"Hi {student_name},\n\n"
                    f"Awesome — thanks for confirming your interest in {program}.\n"
                    f"For {start_term}, we can set up a quick call to walk through "
                    f"requirements and deadlines.\n\n"
                    "Reply with a few times that work for you, or we can schedule a call "
                    "automatically in the real system.\n\n"
                    "— Cory Admissions\n"
                )
                _send_email(
                    server,
                    from_email=from_email,
                    to_email=to_email,
                    subject=reply_subject,
                    body=reply_body,
                )
                print("✅ Cory reply sent. Flow complete.")
                return

            if idx < len(touches):
                print("⏳ No reply yet. Waiting 60 seconds before the next email...\n")
                time.sleep(60)

        print("\n🚩 Reached 5 touches with no student reply. Flow finished without response.")

    finally:
        server.quit()


if __name__ == "__main__":
    main()
