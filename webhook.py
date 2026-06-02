#!/usr/bin/env python3
"""
Webhook server that receives Chime notifications from MacroDroid,
parses them, and sends formatted payment messages to Telegram.
"""
import asyncio
import logging
import os
import time
from urllib.parse import unquote

from flask import Flask, request, jsonify
from database import add_payment, set_balance, init_db, add_tracking_out
from bot import format_payment_message, format_spending_message, parse_chime_sms
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DEFAULT_TAG

# Deduplication cache: key = (tag, amount, sender/merchant) -> timestamp
_dedup_cache = {}
DEDUP_WINDOW_SECONDS = 120  # Ignore duplicate within 2 minutes


import re as _re

def _normalize_id(s: str) -> str:
    """Normalize sender/merchant for dedup: lowercase, strip punctuation & spaces."""
    return _re.sub(r"[^a-z0-9]", "", s.lower())


def _is_duplicate(tag: str, amount: float, identifier: str) -> bool:
    """Check if same payment/spending was processed recently.
    
    Uses (tag, amount) as primary key - same amount to same account
    within 2 minutes is almost certainly a duplicate.
    """
    norm_id = _normalize_id(identifier)
    key = (tag, amount, norm_id)
    # Also check amount-only key (catches name formatting differences)
    key_amount_only = (tag, amount)
    now = time.time()
    # Clean old entries
    expired = [k for k, t in _dedup_cache.items() if now - t > DEDUP_WINDOW_SECONDS]
    for k in expired:
        del _dedup_cache[k]
    # Check if duplicate by amount-only (same tag + same amount within window)
    if key_amount_only in _dedup_cache:
        return True
    if key in _dedup_cache:
        return True
    _dedup_cache[key] = now
    _dedup_cache[key_amount_only] = now
    return False

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
init_db()

def send_telegram_message_sync(text: str):
    """Send a formatted message to the Telegram group."""
    import telegram

    async def _send():
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="HTML",
        )

    asyncio.run(_send())


# Email monitoring disabled - using MacroDroid only
# from email_monitor import start_email_monitor
# start_email_monitor(send_telegram_fn=send_telegram_message_sync)

# Telegram bot command handling via manual update processing
import telegram
from telegram.ext import Application
from bot import create_app

_bot_app = None

def _get_bot_app():
    global _bot_app
    if _bot_app is None:
        _bot_app = create_app()
    return _bot_app


def _process_telegram_update(update_data: dict):
    """Process a Telegram update through the bot handlers."""
    import asyncio

    async def _handle():
        bot_app = _get_bot_app()
        async with bot_app:
            await bot_app.start()
            update = telegram.Update.de_json(update_data, bot_app.bot)
            await bot_app.process_update(update)
            await bot_app.stop()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_handle())
    finally:
        loop.close()


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "Chime Monitor Active"})


@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    """Receive Telegram updates via webhook."""
    update_data = request.get_json(silent=True)
    if not update_data:
        return jsonify({"error": "No data"}), 400
    try:
        _process_telegram_update(update_data)
    except Exception as e:
        logger.error("Error processing Telegram update: %s", e)
    return jsonify({"ok": True})


@app.route("/notify", methods=["GET"])
def notify_get():
    """Handle MacroDroid HTTP GET with notification text as query param.
    
    URL format: /notify?tag=Georgiana+Keel&text=Oh+yeah!+Anthony+K.+sent+you+$20.00.+🤜
    """
    text = request.args.get("text", "")
    if not text:
        return jsonify({"error": "No text provided"}), 400

    tag = request.args.get("tag", DEFAULT_TAG)
    logger.info("Received notification [%s]: %s", tag, text)

    parsed = parse_chime_sms(text)
    if not parsed:
        # Not a recognized Chime notification, send raw text
        try:
            send_telegram_message_sync(f"📱 Chime Notification [{tag}]:\n{text}")
        except Exception as e:
            logger.error("Failed to send raw notification: %s", e)
        return jsonify({"status": "forwarded_raw", "text": text})

    if parsed.get("type") == "spending":
        # Dedup check for spending
        if _is_duplicate(tag, parsed["amount"], parsed.get("merchant", "")):
            logger.info("Duplicate spending ignored [%s]: $%.2f at %s", tag, parsed["amount"], parsed.get("merchant", ""))
            return jsonify({"status": "duplicate_ignored", "type": "spending"})
        # Spending notification - update balance and send formatted message
        set_balance(tag, parsed["new_balance"])
        add_tracking_out(tag, parsed["amount"])
        parsed["tag"] = tag
        msg = format_spending_message(parsed)
        try:
            send_telegram_message_sync(msg)
            logger.info("Spending sent [%s]: $%.2f at %s", tag, parsed["amount"], parsed["merchant"])
        except Exception as e:
            logger.error("Failed to send spending notification: %s", e)
            return jsonify({"error": str(e)}), 500
        return jsonify({"status": "ok", "type": "spending", "amount": parsed["amount"], "merchant": parsed["merchant"]})

    # Dedup check for payment
    if _is_duplicate(tag, parsed["amount"], parsed["sender"]):
        logger.info("Duplicate payment ignored [%s]: $%.2f from %s", tag, parsed["amount"], parsed["sender"])
        return jsonify({"status": "duplicate_ignored", "type": "received"})

    # Payment received
    payment = add_payment(tag, parsed["amount"], parsed["sender"])
    msg = format_payment_message(payment)

    try:
        send_telegram_message_sync(msg)
        logger.info("Formatted payment sent [%s]: $%.2f from %s", tag, parsed["amount"], parsed["sender"])
    except Exception as e:
        logger.error("Failed to send formatted payment: %s", e)
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok", "type": "received", "amount": parsed["amount"], "sender": parsed["sender"]})


@app.route("/notify", methods=["POST"])
def notify_post():
    """Handle POST requests with JSON body.
    
    JSON format: {"text": "Oh yeah! Anthony K. sent you $20.00. 🤜"}
    Or: {"amount": 7.00, "sender": "Adam K.", "tag": "Evelyn"}
    """
    data = request.get_json(silent=True) or {}

    # If raw text is provided, parse it
    if "text" in data:
        text = data["text"]
        parsed = parse_chime_sms(text)
        if not parsed:
            send_telegram_message_sync(f"📱 Chime Notification:\n{text}")
            return jsonify({"status": "forwarded_raw"})

        tag = data.get("tag", DEFAULT_TAG)

        if parsed.get("type") == "spending":
            set_balance(tag, parsed["new_balance"])
            msg = format_spending_message(parsed)
            try:
                send_telegram_message_sync(msg)
            except Exception as e:
                logger.error("Failed to send spending: %s", e)
                return jsonify({"error": str(e)}), 500
            return jsonify({"status": "ok", "type": "spending", "amount": parsed["amount"], "merchant": parsed["merchant"]})

        amount = parsed["amount"]
        sender = parsed["sender"]
    else:
        # Direct amount/sender input
        amount = float(data.get("amount", 0))
        sender = data.get("sender", "Unknown")
        tag = data.get("tag", DEFAULT_TAG)

    if amount <= 0:
        return jsonify({"error": "Invalid amount"}), 400

    payment = add_payment(tag, amount, sender)
    msg = format_payment_message(payment)

    try:
        send_telegram_message_sync(msg)
    except Exception as e:
        logger.error("Failed to send: %s", e)
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok", "type": "received", "amount": amount, "sender": sender})


@app.route("/setbalance", methods=["POST"])
def set_balance_endpoint():
    """Set account balance: {"balance": 2877.72, "tag": "Evelyn"}"""
    from database import set_balance
    data = request.get_json(silent=True) or {}
    balance = float(data.get("balance", 0))
    tag = data.get("tag", DEFAULT_TAG)
    set_balance(tag, balance)
    return jsonify({"status": "ok", "tag": tag, "balance": balance})


@app.route("/settotal", methods=["POST"])
def set_total_endpoint():
    """Set running total: {"total": 2662.72, "tag": "Evelyn"}"""
    from database import set_total
    data = request.get_json(silent=True) or {}
    total = float(data.get("total", 0))
    tag = data.get("tag", DEFAULT_TAG)
    set_total(tag, total)
    return jsonify({"status": "ok", "tag": tag, "total": total})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
