# app/channels/providers/mail_reader.py

import imaplib
import email
from email.header import decode_header, make_header
from datetime import datetime, timezone
import os
import logging
from typing import Optional

from app.data.db_pg import supabase  # Supabase client


logger = logging.getLogger(__name__)


def _get_env(name: str, default: Optional[str] = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing env var {name}")
    return value


def connect_imap() -> imaplib.IMAP4_SSL:
    host = _get_env("IMAP_HOST")
    port = int(os.environ.get("IMAP_PORT", "993"))
    username = _get_env("IMAP_USERNAME")
    password = _get_env("IMAP_PASSWORD")

    imap = imaplib.IMAP4_SSL(host, port)
    imap.login(username, password)
    return imap


def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value or ""


def _get_plain_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                return payload.decode(
                    part.get_content_charset() or "utf-8",
                    errors="ignore",
                )
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            return payload.decode(
                msg.get_content_charset() or "utf-8",
                errors="ignore",
            )
    return ""


async def _insert_inbound_interaction(from_email: str, msg: email.message.Message):
    """
    Map from incoming email -> lead row in Supabase -> insert into interactions.

    Note: we only require lead.id. current_campaign_id is optional and may not
    exist in all schemas, so we do NOT select it explicitly.
    """

    # 1) Find matching lead by email in Supabase
    try:
        # Case-insensitive match on email
        lead_resp = (
            supabase.table("leads")
            .select("id")  # do NOT request current_campaign_id (column may not exist)
            .ilike("email", from_email)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.exception("Supabase error while looking up lead: %s", e)
        return

    # supabase-py returns .data attribute
    lead_data = getattr(lead_resp, "data", None) or []
    if not lead_data:
        logger.info(
            "Inbound email from unknown address %s; no matching lead found",
            from_email,
        )
        return

    lead = lead_data[0]
    lead_id = lead["id"]

    # Optional campaign_id – only use if your leads table actually has it
    campaign_id = lead.get("current_campaign_id")

    # 2) Extract message details
    message_id = msg.get("Message-ID")
    in_reply_to = msg.get("In-Reply-To")
    subject = _decode_header(msg.get("Subject"))
    body = _get_plain_body(msg)

    if not message_id:
        # Fallback to a pseudo-external id
        message_id = f"{from_email}|{subject}|{datetime.now(timezone.utc).isoformat()}"

    # 3) Insert into interactions table in Supabase
    interaction_payload = {
        "lead_id": lead_id,
        "campaign_id": campaign_id,
        "channel": "email",
        "direction": "inbound",
        "status": "completed",
        "content": body,
        "metadata": {
            "subject": subject,
            "in_reply_to": in_reply_to,
            "message_id": message_id,
            "from_email": from_email,
        },
        "external_id": message_id,
    }

    try:
        # Upsert on external_id so we don't double-insert the same message
        supabase.table("interactions").upsert(
            interaction_payload, on_conflict="external_id"
        ).execute()
        logger.info(
            "Stored inbound email for lead %s (campaign=%s) subject=%s",
            lead_id,
            campaign_id,
            subject,
        )
    except Exception as e:
        logger.exception("Supabase error while inserting interaction: %s", e)


async def poll_once():
    """Run a single IMAP poll and store any new messages into Supabase."""
    imap = connect_imap()
    try:
        imap.select("INBOX")

        # Search for unseen messages
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            logger.error("IMAP search failed: %s", status)
            return

        ids = data[0].split()
        if not ids:
            return

        for msg_id in ids:
            res, msg_data = imap.fetch(msg_id, "(RFC822)")
            if res != "OK":
                logger.error("IMAP fetch failed for id %s: %s", msg_id, res)
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            from_header = msg.get("From", "")
            from_email = email.utils.parseaddr(from_header)[1]

            await _insert_inbound_interaction(from_email, msg)

            # Mark as seen so we don't process again
            imap.store(msg_id, "+FLAGS", "\\Seen")

    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()
