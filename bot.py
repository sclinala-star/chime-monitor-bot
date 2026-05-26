import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
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
    return app
