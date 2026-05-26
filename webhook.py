#!/usr/bin/env python3
"""
Webhook server for receiving Chime payment notifications from external services.
Can be used with Zapier, IFTTT, or custom integrations.

Run this alongside the bot for webhook-based payment detection.
"""
import asyncio
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from database import add_payment, init_db
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DEFAULT_TAG

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def send_telegram_message(text: str):
    """Send a message to the configured Telegram chat."""
    import telegram
    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="HTML")


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
            amount = float(data.get("amount", 0))
            sender = data.get("sender", "Unknown")
            tag = data.get("tag", DEFAULT_TAG)

            if amount <= 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Invalid amount"}')
                return

            payment = add_payment(tag, amount, sender)

            from bot import format_payment_message
            msg = format_payment_message(payment)

            asyncio.run(send_telegram_message(msg))

            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "payment": payment}).encode())
            logger.info("Webhook payment: $%.2f from %s", amount, sender)

        except Exception as e:
            logger.error("Webhook error: %s", e)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status": "Chime Monitor Webhook Active"}')

    def log_message(self, format, *args):
        logger.info(format, *args)


def main():
    init_db()
    port = 8080
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    logger.info("Webhook server running on port %d", port)
    logger.info("POST /webhook with JSON: {\"amount\": 7.00, \"sender\": \"Adam K.\", \"tag\": \"Evelyn\"}")
    server.serve_forever()


if __name__ == "__main__":
    main()
