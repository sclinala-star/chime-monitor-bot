import imaplib
import email
import re
import time
import logging
import threading
from email.header import decode_header
from database import add_payment, set_balance
from bot import format_payment_message, format_spending_message, parse_chime_sms
from config import (
    EMAIL_ADDRESS,
    EMAIL_PASSWORD,
    EMAIL_IMAP_SERVER,
    EMAIL_IMAP_PORT,
    EMAIL_POLL_INTERVAL,
    DEFAULT_TAG,
)

# Known account tags for multi-account detection
KNOWN_TAGS = ["Georgiana Keel", "Imelda Villanueva"]

logger = logging.getLogger(__name__)


def decode_email_body(msg) -> str:
    """Extract text body from email message."""
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
                    # Strip HTML tags for plain text parsing
                    html = payload.decode("utf-8", errors="replace")
                    body += re.sub(r"<[^>]+>", " ", html)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")
    return body.strip()


def decode_email_subject(msg) -> str:
    """Decode email subject."""
    subject = ""
    for part_bytes, charset in decode_header(msg["Subject"] or ""):
        if isinstance(part_bytes, bytes):
            subject += part_bytes.decode(charset or "utf-8", errors="replace")
        else:
            subject += part_bytes
    return subject


def detect_tag_from_email(msg) -> str:
    """Detect which account tag this email belongs to based on email body content.
    
    Chime emails typically contain the first name, e.g.:
    'Georgiana, you just received $30.00 from Bryce K.'
    """
    body = decode_email_body(msg)
    subject = decode_email_subject(msg)
    full_text = subject + " " + body

    for tag in KNOWN_TAGS:
        first_name = tag.split()[0]
        if first_name.lower() in full_text.lower():
            return tag
    return DEFAULT_TAG


def is_chime_email(msg) -> bool:
    """Check if email is from Chime."""
    sender = msg.get("From", "").lower()
    subject = decode_email_subject(msg).lower()
    return "chime" in sender or "chime" in subject or "no-reply@chime.com" in sender


def parse_chime_email(msg) -> dict | None:
    """Parse a Chime email to extract payment or spending info."""
    subject = decode_email_subject(msg)
    body = decode_email_body(msg)
    full_text = subject + " " + body

    # Use the same parser as notifications
    parsed = parse_chime_sms(full_text)
    if parsed:
        return parsed

    # Try subject alone
    parsed = parse_chime_sms(subject)
    if parsed:
        return parsed

    # Try body alone
    parsed = parse_chime_sms(body)
    if parsed:
        return parsed

    return None


def connect_imap():
    """Connect to Outlook IMAP server."""
    mail = imaplib.IMAP4_SSL(EMAIL_IMAP_SERVER, EMAIL_IMAP_PORT)
    mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    return mail


def process_email(msg, send_telegram_fn):
    """Process a single Chime email."""
    if not is_chime_email(msg):
        return False

    tag = detect_tag_from_email(msg)
    parsed = parse_chime_email(msg)
    if not parsed:
        # Forward raw subject as notification
        subject = decode_email_subject(msg)
        if subject:
            try:
                send_telegram_fn(f"📧 Chime Email [{tag}]:\n{subject}")
            except Exception as e:
                logger.error("Failed to send raw email notification: %s", e)
        return False

    if parsed.get("type") == "spending":
        set_balance(tag, parsed["new_balance"])
        parsed["tag"] = tag
        msg_text = format_spending_message(parsed)
        try:
            send_telegram_fn(msg_text)
            logger.info("Email spending [%s]: $%.2f at %s", tag, parsed["amount"], parsed["merchant"])
        except Exception as e:
            logger.error("Failed to send spending from email: %s", e)
        return True

    # Payment received
    payment = add_payment(tag, parsed["amount"], parsed["sender"])
    msg_text = format_payment_message(payment)
    try:
        send_telegram_fn(msg_text)
        logger.info("Email payment [%s]: $%.2f from %s", tag, parsed["amount"], parsed["sender"])
    except Exception as e:
        logger.error("Failed to send payment from email: %s", e)
    return True


def email_monitor_loop(send_telegram_fn):
    """Background loop that monitors Outlook for Chime emails."""
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        logger.warning("Email credentials not configured. Email monitoring disabled.")
        return

    logger.info("Starting email monitor for %s via %s", EMAIL_ADDRESS, EMAIL_IMAP_SERVER)
    seen_uids = set()

    while True:
        try:
            mail = connect_imap()
            mail.select("INBOX")

            # Mark all existing emails as seen on first connection
            _, data = mail.search(None, "ALL")
            if data[0]:
                for uid in data[0].split():
                    seen_uids.add(uid)
            logger.info("Email monitor connected. %d existing emails marked. Watching for new Chime emails...", len(seen_uids))

            while True:
                try:
                    mail.noop()  # Keep connection alive
                    mail.select("INBOX")
                    _, data = mail.search(None, "UNSEEN")

                    if data[0]:
                        for email_id in data[0].split():
                            if email_id in seen_uids:
                                continue
                            seen_uids.add(email_id)

                            _, msg_data = mail.fetch(email_id, "(RFC822)")
                            for response_part in msg_data:
                                if isinstance(response_part, tuple):
                                    msg = email.message_from_bytes(response_part[1])
                                    process_email(msg, send_telegram_fn)

                except imaplib.IMAP4.abort:
                    logger.warning("IMAP connection lost, reconnecting...")
                    break
                except Exception as e:
                    logger.error("Error checking emails: %s", e)

                time.sleep(EMAIL_POLL_INTERVAL)

        except Exception as e:
            logger.error("Failed to connect to email: %s", e)
            time.sleep(60)


def start_email_monitor(send_telegram_fn):
    """Start email monitoring in a background thread."""
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        logger.info("Email monitoring disabled - no credentials configured.")
        return None

    thread = threading.Thread(
        target=email_monitor_loop,
        args=(send_telegram_fn,),
        daemon=True,
        name="email-monitor",
    )
    thread.start()
    logger.info("Email monitor thread started.")
    return thread
