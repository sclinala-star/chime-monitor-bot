import logging
import re
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from database import init_db, add_payment, get_account, set_balance, set_total, get_recent_payments
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DEFAULT_TAG

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def format_payment_message(payment: dict) -> str:
    tag = payment["tag"]
    amount = payment["amount"]
    sender = payment["sender"]
    prev_total = payment["previous_total"]
    new_total = payment["new_total"]
    prev_balance = payment["previous_balance"]
    new_balance = payment["new_balance"]

    msg = (
        f"💰 <b>Chime Payment Received!</b>\n"
        f"\n"
        f"👤 Tag: {tag}\n"
        f"💵 New Payment: ${amount:,.2f}\n"
        f"🚢 Sent by: {sender}\n"
        f"\n"
        f"💰 Previous Total: ${prev_total:,.2f}\n"
        f"🏦 New Total: ${prev_total:,.2f} + ${amount:,.2f} = ${new_total:,.2f}\n"
        f"\n"
        f"💳 Account Balance: ${prev_balance:,.2f} + ${amount:,.2f} = ${new_balance:,.2f}"
    )
    return msg


async def send_payment_notification(app: Application, payment: dict, chat_id: str = None):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not target_chat:
        logger.error("No chat ID configured")
        return
    msg = format_payment_message(payment)
    await app.bot.send_message(
        chat_id=target_chat,
        text=msg,
        parse_mode="HTML",
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏦 <b>Chime Monitor Bot</b>\n\n"
        "Commands:\n"
        "/add &lt;amount&gt; &lt;sender&gt; [tag] - Add a payment\n"
        "/balance - View current balance\n"
        "/setbalance &lt;amount&gt; [tag] - Set account balance\n"
        "/settotal &lt;amount&gt; [tag] - Set running total\n"
        "/history [tag] - View recent payments\n"
        "/help - Show this help message",
        parse_mode="HTML",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_command(update, context)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a payment: /add <amount> <sender name> [tag]"""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /add <amount> <sender name> [tag]\n"
            "Example: /add 7.00 Adam K.\n"
            "Example: /add 10.00 Michelle M. Evelyn"
        )
        return

    try:
        amount = float(context.args[0].replace("$", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("Invalid amount. Use a number like 7.00")
        return

    remaining_args = context.args[1:]

    # Check if last argument could be a tag (single word, no period)
    # If there are 3+ args and the last doesn't end with a period, treat it as tag
    tag = DEFAULT_TAG
    sender_parts = remaining_args

    if len(remaining_args) >= 2:
        # Check if last word is a tag identifier
        last_word = remaining_args[-1]
        if not last_word.endswith(".") and last_word[0].isupper() and len(last_word) > 1:
            # Could be a tag - check if second to last ends with period (name ending)
            if remaining_args[-2].endswith("."):
                tag = last_word
                sender_parts = remaining_args[:-1]

    sender = " ".join(sender_parts)

    payment = add_payment(tag, amount, sender)

    msg = format_payment_message(payment)
    await update.message.reply_text(msg, parse_mode="HTML")

    # Also send to the configured chat if different from current
    chat_id = str(update.effective_chat.id)
    if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode="HTML",
        )


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tag = context.args[0] if context.args else DEFAULT_TAG
    account = get_account(tag)
    await update.message.reply_text(
        f"🏦 <b>Account Info - {tag}</b>\n\n"
        f"💰 Total Received: ${account['total']:,.2f}\n"
        f"💳 Account Balance: ${account['balance']:,.2f}",
        parse_mode="HTML",
    )


async def set_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setbalance <amount> [tag]")
        return
    try:
        amount = float(context.args[0].replace("$", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return
    tag = context.args[1] if len(context.args) > 1 else DEFAULT_TAG
    set_balance(tag, amount)
    await update.message.reply_text(f"Balance for {tag} set to ${amount:,.2f}")


async def set_total_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /settotal <amount> [tag]")
        return
    try:
        amount = float(context.args[0].replace("$", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return
    tag = context.args[1] if len(context.args) > 1 else DEFAULT_TAG
    set_total(tag, amount)
    await update.message.reply_text(f"Total for {tag} set to ${amount:,.2f}")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tag = context.args[0] if context.args else DEFAULT_TAG
    payments = get_recent_payments(tag)
    if not payments:
        await update.message.reply_text(f"No payments found for {tag}.")
        return
    lines = [f"📋 <b>Recent Payments - {tag}</b>\n"]
    for p in payments:
        lines.append(
            f"• ${p['amount']:,.2f} from {p['sender']} ({p['created_at'][:10]})"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# Patterns for parsing Chime notifications
# Format: "Oh yeah! Anthony K. sent you $20.00. 🤜"
CHIME_PATTERN = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z]\.?)?)\s+sent\s+you\s+\$\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)
# Fallback: any "$amount" pattern
SMS_AMOUNT_PATTERN = re.compile(r"\$\s*([\d,]+\.?\d*)")
SMS_SENDER_PATTERN = re.compile(
    r"(?:from|sent by|paid by|received from)\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)?)",
    re.IGNORECASE,
)


def parse_chime_sms(text: str) -> dict | None:
    """Parse a Chime notification text to extract payment info.
    
    Handles formats like:
    - "Oh yeah! Anthony K. sent you $20.00. 🤜"
    - "You received $X from Name"
    """
    # Try primary Chime format: "Name sent you $amount"
    chime_match = CHIME_PATTERN.search(text)
    if chime_match:
        sender = chime_match.group(1).strip()
        amount = float(chime_match.group(2).replace(",", ""))
        return {"amount": amount, "sender": sender}

    # Fallback: look for keywords + amount
    lower = text.lower()
    is_chime = any(kw in lower for kw in [
        "oh yeah", "sent you", "chime", "payment", "received", "deposit", "direct pay",
    ])
    has_amount = SMS_AMOUNT_PATTERN.search(text)
    if not is_chime or not has_amount:
        return None

    amount = float(has_amount.group(1).replace(",", ""))
    sender_match = SMS_SENDER_PATTERN.search(text)
    sender = sender_match.group(1).strip() if sender_match else "Unknown"

    return {"amount": amount, "sender": sender}


async def sms_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle forwarded SMS or plain text messages containing Chime payment info."""
    text = update.message.text or ""
    if not text:
        return

    parsed = parse_chime_sms(text)
    if not parsed:
        return

    tag = DEFAULT_TAG
    payment = add_payment(tag, parsed["amount"], parsed["sender"])
    msg = format_payment_message(payment)
    await update.message.reply_text(msg, parse_mode="HTML")

    # Also send to the configured group
    chat_id = str(update.effective_chat.id)
    if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode="HTML",
        )


def create_app() -> Application:
    init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("setbalance", set_balance_command))
    app.add_handler(CommandHandler("settotal", set_total_command))
    app.add_handler(CommandHandler("history", history_command))
    # Handle forwarded SMS / plain text messages with Chime payment info
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, sms_handler))
    return app
