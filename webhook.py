#!/usr/bin/env python3
"""
Webhook server that receives Chime notifications from MacroDroid,
parses them, and sends formatted payment messages to Telegram.
"""
import asyncio
import logging
import os
from urllib.parse import unquote

from flask import Flask, request, jsonify
from database import add_payment, set_balance, init_db
from bot import format_payment_message, format_spending_message, parse_chime_sms
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DEFAULT_TAG

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


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "Chime Monitor Active"})


@app.route("/notify", methods=["GET"])
def notify_get():
    """Handle MacroDroid HTTP GET with notification text as query param.
    
    URL format: /notify?text=Oh+yeah!+Anthony+K.+sent+you+$20.00.+🤜
    """
    text = request.args.get("text", "")
    if not text:
        return jsonify({"error": "No text provided"}), 400

    logger.info("Received notification: %s", text)

    parsed = parse_chime_sms(text)
    if not parsed:
        # Not a recognized Chime notification, send raw text
        try:
            send_telegram_message_sync(f"📱 Chime Notification:\n{text}")
        except Exception as e:
            logger.error("Failed to send raw notification: %s", e)
        return jsonify({"status": "forwarded_raw", "text": text})

    tag = DEFAULT_TAG

    if parsed.get("type") == "spending":
        # Spending notification - update balance and send formatted message
        set_balance(tag, parsed["new_balance"])
        msg = format_spending_message(parsed)
        try:
            send_telegram_message_sync(msg)
            logger.info("Spending sent: $%.2f at %s", parsed["amount"], parsed["merchant"])
        except Exception as e:
            logger.error("Failed to send spending notification: %s", e)
            return jsonify({"error": str(e)}), 500
        return jsonify({"status": "ok", "type": "spending", "amount": parsed["amount"], "merchant": parsed["merchant"]})

    # Payment received
    payment = add_payment(tag, parsed["amount"], parsed["sender"])
    msg = format_payment_message(payment)

    try:
        send_telegram_message_sync(msg)
        logger.info("Formatted payment sent: $%.2f from %s", parsed["amount"], parsed["sender"])
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
        amount = parsed["amount"]
        sender = parsed["sender"]
        tag = data.get("tag", DEFAULT_TAG)
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

    return jsonify({"status": "ok", "amount": amount, "sender": sender})


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
