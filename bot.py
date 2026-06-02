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
from database import init_db, add_payment, get_account, set_balance, set_total, get_recent_payments, start_tracking, stop_tracking, add_tracking_out
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
        f"💳 Account Balance: ${new_balance:,.2f}"
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
        "<b>Commands:</b>\n"
        "/balance Georgiana Keel - View balance\n"
        "/setbalance 43 Georgiana Keel - Set balance\n"
        "/settotal 0 Georgiana Keel - Reset total\n"
        "/history Georgiana Keel - Recent payments\n\n"
        "<b>Just type:</b>\n"
        "<code>update 43 Georgiana</code> - Update balance\n"
        "<code>st Georgiana</code> - Start fund out tracking\n"
        "<code>stop Georgiana</code> - Stop &#38; show total out",
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
    """Show balance: /balance [tag name]"""
    tag = " ".join(context.args) if context.args else DEFAULT_TAG
    account = get_account(tag)
    await update.message.reply_text(
        f"🏦 <b>Account Info - {tag}</b>\n\n"
        f"💰 Total Received: ${account['total']:,.2f}\n"
        f"💳 Account Balance: ${account['balance']:,.2f}",
        parse_mode="HTML",
    )


async def set_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set balance: /setbalance <amount> [tag name]
    Examples: /setbalance 43 Georgiana Keel
              /setbalance 128
    """
    if not context.args:
        await update.message.reply_text(
            "Usage: /setbalance <amount> [tag name]\n"
            "Example: /setbalance 43 Georgiana Keel"
        )
        return
    try:
        amount = float(context.args[0].replace("$", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return
    # Join remaining args as tag name (supports multi-word names)
    tag = " ".join(context.args[1:]) if len(context.args) > 1 else DEFAULT_TAG
    set_balance(tag, amount)
    account = get_account(tag)
    await update.message.reply_text(
        f"✅ <b>Balance Updated</b>\n\n"
        f"👤 Account: {tag}\n"
        f"💳 New Balance: ${amount:,.2f}\n"
        f"💰 Total: ${account['total']:,.2f}",
        parse_mode="HTML",
    )


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
# Payment received formats:
#   "Oh yeah! Anthony K. sent you $20.00. 🤜"
#   "YAAAS! Daniel J. sent you $75.00. 🎉"
#   "Woot! Jannette P. sent you $25.00. 💥"
#   "Hooray! Skip S. sent you $40.00. 😁"
# Spending format:
#   "You spent $180.00. Your new Chime account balance is $13.71 after your purchase at Crypto.Com."
CHIME_PATTERN = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z]\.?)?)\s+sent\s+you\s+\$\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)
CHIME_SPENT_PATTERN = re.compile(
    r"You\s+spent\s+\$\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)
CHIME_BALANCE_PATTERN = re.compile(
    r"balance\s+is\s+\$\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)
CHIME_PURCHASE_PATTERN = re.compile(
    r"purchase\s+at\s+(.+?)\.?\s*$",
    re.IGNORECASE,
)
# Fallback: any "$amount" pattern
SMS_AMOUNT_PATTERN = re.compile(r"\$\s*([\d,]+\.?\d*)")
SMS_SENDER_PATTERN = re.compile(
    r"(?:from|sent by|paid by|received from)\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)?)",
    re.IGNORECASE,
)


def format_spending_message(spending: dict) -> str:
    amount = spending["amount"]
    merchant = spending["merchant"]
    new_balance = spending["new_balance"]
    tag = spending.get("tag", "")

    lines = ["💸 <b>Chime Out</b>\n"]
    if tag:
        lines.append(f"👤 Tag: {tag}")
    if amount > 0:
        lines.append(f"💵 Amount Spent: ${amount:,.2f}")
    lines.append(f"🏪 Purchase at: {merchant}")
    lines.append(f"💳 New Balance: ${new_balance:,.2f}")

    return "\n".join(lines)


def parse_chime_sms(text: str) -> dict | None:
    """Parse a Chime notification text to extract payment info.
    
    Handles all known Chime notification formats:
    - "Oh yeah! Anthony K. sent you $20.00. 🤜"
    - "YAAAS! Muhamadou T. sent you $3.71. 🎉"
    - "Woot! Jannette P. sent you $25.00. 💥"
    - "Hooray! Skip S. sent you $40.00. 😁"
    - "Cowabunga! Anthony G. sent you $35.00. 🐄"
    - "You spent $180.00 ... balance is $13.71 ... purchase at Crypto.Com."
    - "Your new Chime account balance is $115.91 after your purchase at Crypto.com."
    """
    # Check for spending notification (full format: "You spent $X...")
    spent_match = CHIME_SPENT_PATTERN.search(text)
    if spent_match:
        amount = float(spent_match.group(1).replace(",", ""))
        balance_match = CHIME_BALANCE_PATTERN.search(text)
        new_balance = float(balance_match.group(1).replace(",", "")) if balance_match else 0.0
        purchase_match = CHIME_PURCHASE_PATTERN.search(text)
        merchant = purchase_match.group(1).strip() if purchase_match else "Unknown"
        return {"type": "spending", "amount": amount, "new_balance": new_balance, "merchant": merchant}

    # Check for spending notification (body only: "Your new Chime account balance is $X after your purchase at Y")
    balance_match = CHIME_BALANCE_PATTERN.search(text)
    purchase_match = CHIME_PURCHASE_PATTERN.search(text)
    if balance_match and purchase_match:
        new_balance = float(balance_match.group(1).replace(",", ""))
        merchant = purchase_match.group(1).strip()
        return {"type": "spending", "amount": 0.0, "new_balance": new_balance, "merchant": merchant}

    # Try primary Chime format: "Name sent you $amount"
    chime_match = CHIME_PATTERN.search(text)
    if chime_match:
        sender = chime_match.group(1).strip()
        amount = float(chime_match.group(2).replace(",", ""))
        return {"type": "received", "amount": amount, "sender": sender}

    # Fallback: look for keywords + amount (but NOT balance notifications)
    lower = text.lower()
    if "balance" in lower and "purchase" in lower:
        return None
    is_chime = any(kw in lower for kw in [
        "oh yeah", "yaaas", "woot", "hooray", "sent you",
        "cowabunga", "payment", "received", "deposit", "direct pay",
    ])
    has_amount = SMS_AMOUNT_PATTERN.search(text)
    if not is_chime or not has_amount:
        return None

    amount = float(has_amount.group(1).replace(",", ""))
    sender_match = SMS_SENDER_PATTERN.search(text)
    sender = sender_match.group(1).strip() if sender_match else "Unknown"

    return {"type": "received", "amount": amount, "sender": sender}


# Pattern for natural language balance update: "update 43 Georgiana" or "update balance 128 Georgiana Keel"
UPDATE_BALANCE_PATTERN = re.compile(
    r"(?:update|set|change)\s*(?:balance|bal)?\s*\$?\s*([\d,]+\.?\d*)\s*(.*)",
    re.IGNORECASE,
)

# Pattern for start/stop tracking: "st Georgiana" or "stop Imelda"
ST_PATTERN = re.compile(r"^st\s+(.+)", re.IGNORECASE)
STOP_PATTERN = re.compile(r"^stop\s+(.+)", re.IGNORECASE)

# Known tags for matching
KNOWN_TAGS = ["Georgiana Keel", "Imelda Villanueva"]


def _detect_tag_from_text(text: str) -> str:
    """Detect account tag from text by matching first names."""
    for tag in KNOWN_TAGS:
        first_name = tag.split()[0]
        if first_name.lower() in text.lower():
            return tag
    return DEFAULT_TAG


async def sms_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle forwarded SMS, plain text Chime notifications, and natural language balance updates."""
    text = update.message.text or ""
    if not text:
        return

    # Check for "st <name>" - start tracking
    st_match = ST_PATTERN.match(text.strip())
    if st_match:
        tag = _detect_tag_from_text(st_match.group(1))
        start_tracking(tag)
        await update.message.reply_text(
            f"▶️ <b>Tracking Started</b>\n\n"
            f"👤 Account: {tag}\n"
            f"📊 Fund out tracking চালু হয়েছে।\n\n"
            f"Stop করতে লিখুন: <code>stop {tag.split()[0]}</code>",
            parse_mode="HTML",
        )
        return

    # Check for "stop <name>" - stop tracking
    stop_match = STOP_PATTERN.match(text.strip())
    if stop_match:
        tag = _detect_tag_from_text(stop_match.group(1))
        result = stop_tracking(tag)
        if not result.get("active"):
            await update.message.reply_text(
                f"⚠️ {tag} এর tracking চালু ছিল না।",
                parse_mode="HTML",
            )
            return
        await update.message.reply_text(
            f"⏹️ <b>Tracking Stopped</b>\n\n"
            f"👤 Account: {tag}\n"
            f"💸 Total Fund Out: ${result['total_out']:,.2f}\n"
            f"🔢 Transactions: {result['transactions']}\n"
            f"🕐 Started: {result['started_at'][:16]}",
            parse_mode="HTML",
        )
        return

    # Check for natural language balance update
    update_match = UPDATE_BALANCE_PATTERN.match(text.strip())
    if update_match:
        try:
            amount = float(update_match.group(1).replace(",", ""))
        except ValueError:
            return
        tag_text = update_match.group(2).strip()
        tag = _detect_tag_from_text(tag_text) if tag_text else DEFAULT_TAG
        set_balance(tag, amount)
        account = get_account(tag)
        await update.message.reply_text(
            f"✅ <b>Balance Updated</b>\n\n"
            f"👤 Account: {tag}\n"
            f"💳 New Balance: ${amount:,.2f}\n"
            f"💰 Total: ${account['total']:,.2f}",
            parse_mode="HTML",
        )
        return

    # Try Chime notification parsing
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
