# Installation Guide

Detailed setup instructions for **Taskify** on a local machine or a VPS.

---

## Prerequisites

- Python **3.11** or newer
- A Telegram account
- A bot token from [@BotFather](https://t.me/BotFather)

---

## 1. Clone the repository

```bash
git clone https://github.com/Madeline-exe/taskify.git
cd taskify
```

---

## 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

```bash
# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```

---

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

This installs: `aiogram`, `flask`, `python-dotenv`, `apscheduler`.

---

## 4. Create a Telegram bot

1. Open [@BotFather](https://t.me/BotFather) in Telegram
2. Send `/newbot` and follow the prompts
3. Copy the token (looks like `123456:ABC-DEF...`)

---

## 5. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
BOT_TOKEN=123456:ABC-your-token-here
FLASK_SECRET=change-this-to-a-random-string
ADMIN_TOKEN=your-secret-admin-password
WEB_URL=http://localhost:5000
FLASK_DEBUG=false
PORT=5000
DIGEST_HOUR=9
```

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Token from BotFather (**required**) |
| `FLASK_SECRET` | Random string for Flask session cookies |
| `ADMIN_TOKEN` | Password to access the admin panel at `/admin?token=...` |
| `WEB_URL` | Public URL of the web panel (used in bot's "Web panel" button) |
| `FLASK_DEBUG` | Set to `true` to enable `/dev-login` (development only) |
| `PORT` | Port for the Flask web server |
| `DIGEST_HOUR` | Hour (0-23, Moscow time) for the daily task digest |

---

## 6. Run the bot

```bash
python run_bot.py
```

The bot will start polling Telegram for messages. The scheduler for daily digests and deadline reminders starts automatically.

Press `Ctrl+C` to stop.

---

## 7. Run the web panel

In a **separate terminal** (with the same virtual environment activated):

```bash
python run_web.py
```

Open `http://localhost:5000` in your browser.

---

## 8. Log in to the web panel

1. Open your bot in Telegram and send `/start`
2. Tap the **Web panel** button
3. Click the link the bot sends you

For development, set `FLASK_DEBUG=true` in `.env` and visit `http://localhost:5000/dev-login` to log in without Telegram.

---

## 9. Admin panel

Open in your browser:

```
http://localhost:5000/admin?token=your-secret-admin-password
```

The admin panel shows all registered users.

---

## Production Deployment (VPS)

### Recommended setup

1. **Reverse proxy** -- [nginx](https://nginx.org/) in front of Flask
2. **Process manager** -- `systemd` or [supervisord](http://supervisord.org/) to keep both processes alive
3. **HTTPS** -- [Let's Encrypt](https://letsencrypt.org/) via certbot
4. Set `WEB_URL` to your real domain (e.g. `https://taskify.example.com`)
5. Set `FLASK_DEBUG=false`

### systemd service example

`/etc/systemd/system/taskify-bot.service`:

```ini
[Unit]
Description=Taskify Telegram Bot
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/taskify
ExecStart=/opt/taskify/.venv/bin/python run_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/taskify-web.service`:

```ini
[Unit]
Description=Taskify Web Panel
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/taskify
ExecStart=/opt/taskify/.venv/bin/python run_web.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable taskify-bot taskify-web
sudo systemctl start taskify-bot taskify-web
```

### nginx config example

```nginx
server {
    listen 80;
    server_name taskify.example.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Then add HTTPS with certbot:

```bash
sudo certbot --nginx -d taskify.example.com
```

---

## Database

SQLite database is stored at `database/taskify.db`. It is created automatically on first launch.

**To reset the database**, delete the file and restart both processes:

```bash
rm database/taskify.db
```

After resetting the database, clear your browser cookies for `localhost:5000` (or the session will reference a deleted user).

---

## Troubleshooting

**Bot doesn't respond**
- Check that `BOT_TOKEN` is correct in `.env`
- Make sure the bot is not already running elsewhere (only one polling instance allowed)

**Web panel redirects to login**
- The user must first send `/start` to the bot to register
- If the database was reset, clear browser cookies and log in again

**Deadlines seem off**
- Deadlines are stored in local time. The scheduler runs in `Europe/Moscow` timezone.
- Enter deadlines in `DD-MM-YYYY HH:MM` format in the bot.

**Port already in use**
- Change `PORT` in `.env` or stop the other process using that port
