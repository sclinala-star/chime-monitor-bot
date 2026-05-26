# Chime Monitor Telegram Bot 🏦

A Telegram bot that monitors Chime bank payments and sends formatted notifications to a Telegram group/chat.

## Features

- **Real-time Payment Notifications** - Automatically detect and report Chime payments
- **Running Totals** - Track cumulative payment totals per account tag
- **Account Balance Tracking** - Maintain and display account balance
- **Email Monitoring** - Automatically detect payments from Chime email notifications
- **Webhook Support** - Receive payments via HTTP webhook (Zapier, IFTTT, etc.)
- **Manual Entry** - Add payments manually via `/add` command
- **Multi-Account Support** - Track multiple accounts with tags

## Notification Format

```
💰 Chime Payment Received!

👤 Tag: Evelyn
💵 New Payment: $7.00
🚢 Sent by: Adam K.

💰 Previous Total: $2,662.72
🏦 New Total: $2,662.72 + $7.00 = $2,669.72

💳 Account Balance: $2,877.72 + $7.00 = $2,884.72
```

## Setup

### 1. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **Bot Token**

### 2. Get Your Chat/Group ID

1. Add the bot to your group
2. Send a message in the group
3. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find `"chat":{"id":` - that's your Chat ID

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:
```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
DEFAULT_TAG=YourName
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Run the Bot

```bash
python run.py
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Show welcome message |
| `/add <amount> <sender>` | Add a payment manually |
| `/add <amount> <sender> <tag>` | Add a payment with specific tag |
| `/balance [tag]` | View account balance and total |
| `/setbalance <amount> [tag]` | Set account balance |
| `/settotal <amount> [tag]` | Set running total |
| `/history [tag]` | View recent payments |
| `/help` | Show help |

### Examples

```
/add 7.00 Adam K.
/add 10.00 Michelle M. Evelyn
/balance
/setbalance 2877.72
/settotal 2662.72
/history
```

## Email Monitoring (Optional)

To automatically detect Chime payments from email notifications:

1. Enable IMAP in your email settings
2. For Gmail, create an [App Password](https://myaccount.google.com/apppasswords)
3. Add to `.env`:
```
EMAIL_ADDRESS=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_IMAP_SERVER=imap.gmail.com
```

## Webhook (Optional)

Run the webhook server alongside the bot:

```bash
python webhook.py
```

Send payments via HTTP POST:

```bash
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{"amount": 7.00, "sender": "Adam K.", "tag": "Evelyn"}'
```

Integrate with:
- **Zapier** - Connect Chime to the webhook
- **IFTTT** - Trigger on Chime notification
- **Plaid** - Use Plaid webhooks for payment detection

## Deployment

### Run with systemd (Linux)

Create `/etc/systemd/system/chime-monitor.service`:

```ini
[Unit]
Description=Chime Monitor Telegram Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/chime-monitor-bot
ExecStart=/usr/bin/python3 run.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable chime-monitor
sudo systemctl start chime-monitor
```

### Run with Docker

```bash
docker build -t chime-monitor .
docker run -d --env-file .env chime-monitor
```

## License

MIT
