#!/usr/bin/env python3
"""
Chime Monitor Telegram Bot
Monitors Chime bank payments and sends notifications to a Telegram group.
"""
import asyncio
import logging
from bot import create_app
from email_monitor import email_monitor_loop
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(app):
    """Start email monitoring after the bot is initialized."""
    asyncio.create_task(email_monitor_loop(app))


def main():
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set!")
        print("Please copy .env.example to .env and fill in your credentials.")
        return

    if not TELEGRAM_CHAT_ID:
        print("WARNING: TELEGRAM_CHAT_ID is not set.")
        print("The bot will work but won't auto-send to a group.")
        print("Use /add command in any chat with the bot to add payments.")

    app = create_app()
    app.post_init = post_init

    logger.info("Starting Chime Monitor Bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
