import imaplib
import email
import re
import time
import logging
import asyncio
from email.header import decode_header
from database import add_payment
from config import (
    EMAIL_ADDRESS,
    EMAIL_PASSWORD,
    EMAIL_IMAP_SERVER,
    EMAIL_IMAP_PORT,
    EMAIL_POLL_INTERVAL,
    DEFAULT_TAG,
)

logger = logging.getLogger(__name__)

# Patterns to extract payment info from Chime emails
AMOUNT_PATTERN = re.compile(r"\$\s*([\d,]+\.?\d*)")
SENDER_PATTERN = re.compile(
    r"(?:from|sent by|paid by|received from)\s+([A-Z][a-z]+(?:\s+[A-Z]\.?))",
    re.IGNORECASE,
)


def parse_chime_email(msg) -> dict | None:
    subject = ""
    for part_bytes, charset in decode_header(msg["Subject"] or ""):
        if isinstance(part_bytes, bytes):
            subject += part_bytes.decode(charset or "utf-8", errors="replace")
        else:
            subject += part_bytes

    # Only process Chime payment emails
    if "chime" not in subject.lower() and "payment" not in subject.lower():
        sender_email = msg.get("From", "")
        if "chime" not in sender_email.lower():
            return None

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode("utf-8", errors="replace")
            elif content_type == "text/html" and not body:
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode("utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")

    full_text = subject + " " + body

    amount_match = AMOUNT_PATTERN.search(full_text)
    if not amount_match:
        return None

    amount = float(amount_match.group(1).replace(",", ""))

    sender_match = SENDER_PATTERN.search(full_text)
    sender = sender_match.group(1).strip() if sender_match else "Unknown"

    return {"amount": amount, "sender": sender, "tag": DEFAULT_TAG}


def connect_imap():
    mail = imaplib.IMAP4_SSL(EMAIL_IMAP_SERVER, EMAIL_IMAP_PORT)
    mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    return mail


def check_new_emails(mail, seen_ids: set) -> list:
    mail.select("INBOX")
    _, data = mail.search(None, "UNSEEN")
    new_payments = []

    for email_id in data[0].split():
        if email_id in seen_ids:
            continue
        seen_ids.add(email_id)

        _, msg_data = mail.fetch(email_id, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                payment_info = parse_chime_email(msg)
                if payment_info:
                    payment = add_payment(
                        payment_info["tag"],
                        payment_info["amount"],
                        payment_info["sender"],
                    )
                    new_payments.append(payment)
                    logger.info(
                        "New payment detected: $%.2f from %s",
                        payment_info["amount"],
                        payment_info["sender"],
                    )

    return new_payments


async def email_monitor_loop(app):
    """Background loop that monitors email for Chime payment notifications."""
    from config import TELEGRAM_CHAT_ID
    from bot import send_payment_notification

    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        logger.warning(
            "Email credentials not configured. Email monitoring disabled. "
            "You can still add payments manually via /add command."
        )
        return

    seen_ids = set()
    logger.info("Starting email monitor for %s", EMAIL_ADDRESS)

    while True:
        try:
            mail = connect_imap()
            # Mark all existing as seen on first run
            mail.select("INBOX")
            _, data = mail.search(None, "ALL")
            for eid in data[0].split():
                seen_ids.add(eid)

            logger.info("Email monitor connected. Watching for new Chime payments...")

            while True:
                try:
                    new_payments = check_new_emails(mail, seen_ids)
                    for payment in new_payments:
                        await send_payment_notification(app, payment)
                except imaplib.IMAP4.abort:
                    logger.warning("IMAP connection lost, reconnecting...")
                    break
                except Exception as e:
                    logger.error("Error checking emails: %s", e)

                await asyncio.sleep(EMAIL_POLL_INTERVAL)

        except Exception as e:
            logger.error("Failed to connect to email: %s", e)
            await asyncio.sleep(60)  # Wait before retrying
