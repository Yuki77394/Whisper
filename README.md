# 🔒 WhisperX

A production-ready Telegram **inline whisper bot**. Send private, self-destructing, one-time, anonymous whispers — text *and* media — straight from Telegram's inline mode.

> Built with **Pyrogram 2.x** + **Motor (async MongoDB)**. Async-first, modular, and built for scale.

---

## ✨ Features

### Core
- **Inline-first UX** – type `@BotUsername @target Hello` from *any* chat.
- **Flexible parser** – recipient-first (`@bot @user message`) *or* message-first (`@bot message @user`).
- **Reply-based recipient** – reply to a user's message then invoke the bot inline.
- **Public whispers** – omit the recipient; anyone can open.
- **Multiple recipients** – `@bot @user1 @user2 Hello everyone`.

### Media support
Photo • Video • Voice • Audio • Document • GIF/Animation • Sticker • Video Note • Albums.

Media is stored as Telegram `file_id` only — no binary blobs in the DB.

### Whisper types
- 🔒 **Private Whisper** (default)
- 👤 **Anonymous Whisper** (hides sender in card; see *Honest limitations* below)
- ⏳ **Timed Whisper** (5m / 10m / 30m / 1h / 24h / 7d)
- 🔥 **One-Time Whisper** (auto-consumed on first open)

### UX
- Clean `/start` screen with **✍️ Use Me** switch-inline button.
- Help page, Settings, Privacy, Language, Whisper History (paginated).
- Advanced `/create` wizard (recipient → message → media → expiry → one-time → anonymous → confirm).
- `/cancel` aborts the wizard.

### Admin
- `/stats`, `/users`, `/broadcast`, `/ban`, `/unban`, `/logs`, `/maintenance`, `/settings`.
- All admins configured via `OWNER_ID` + `ADMIN_IDS` env vars.
- Every whisper logged to a private `LOG_GROUP_ID` supergroup.
- `METADATA_ONLY_LOGS=true` strips message content from logs.

### Performance & security
- Async Pyrogram + Motor, non-blocking.
- MongoDB indexes for every hot query path.
- Background cleanup worker marks expired whispers + purges content.
- Callback validation: whisper must exist, not be expired, user must be authorised, one-time consumed correctly.
- Rate-limit per user per minute (Mongo-backed, shared across workers).
- Duplicate-callback guard.
- FloodWait handled by Pyrogram.
- Whisper IDs are 96-bit random hex — unguessable.

---

## 🧱 Project structure

```
whisper_bot/
├── bot.py                  # Entry point
├── config.py               # Env-driven config
├── database/
│   ├── mongo.py            # Connection + indexes
│   ├── users.py            # users / bans collections
│   ├── whispers.py         # whispers / whisper_access collections
│   └── history.py          # history projection collection
├── handlers/
│   ├── start.py            # /start, /help, nav callbacks
│   ├── inline.py           # inline query handler
│   ├── callbacks.py        # whisper open / history nav
│   ├── commands.py         # /create wizard, /history, /privacy, /cancel
│   └── admin.py            # admin-only commands
├── services/
│   ├── parser.py           # robust input parser (both orderings)
│   ├── whisper.py          # whisper orchestration
│   ├── media.py            # file_id extraction + re-send
│   ├── logger.py           # log-group writer
│   └── cleanup.py          # background expiry worker
├── keyboards/
│   ├── start.py            # main menu
│   ├── help.py             # help nav
│   └── settings.py         # privacy / language / history / create / whisper cards
├── utils/
│   ├── helpers.py
│   ├── security.py         # callback signing, rate limit, dup guard
│   └── formatting.py       # all user-facing strings
├── requirements.txt
├── .env.example
├── Dockerfile
└── README.md
```

---

## 🚀 Quick start (local)

### 1. Prerequisites
- Python **3.10+**
- A **MongoDB** instance (local or Atlas)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- `API_ID` + `API_HASH` from https://my.telegram.org

### 2. Enable inline mode
In [@BotFather](https://t.me/BotFather):
1. `/setinline` → pick your bot → send any placeholder (e.g. `Send a private whisper…`).
2. *(Optional)* `/setinlinefeedback` → Enable — so the bot can see which result was actually sent (used for analytics).

### 3. Configure
```bash
git clone https://github.com/Yuki77394/Whisper.git
cd Whisper
cp .env.example .env
# edit .env
```

### 4. Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

---

## 🐳 Docker

```bash
docker build -t whisperx .
docker run -d --name whisperx --env-file .env --restart unless-stopped whisperx
```

For a full stack (bot + Mongo), use this `docker-compose.yml`:

```yaml
version: "3.9"
services:
  mongo:
    image: mongo:7
    restart: unless-stopped
    volumes:
      - mongo-data:/data/db
  bot:
    build: .
    restart: unless-stopped
    env_file: .env
    environment:
      MONGO_URI: mongodb://mongo:27017
      MONGO_DB_NAME: whisperx
    depends_on:
      - mongo
volumes:
  mongo-data:
```

```bash
docker compose up -d --build
docker compose logs -f bot
```

---

## ☁️ Heroku deployment

WhisperX ships with all the files Heroku needs:
- `Procfile` — declares a `worker` dyno running `python bot.py`
- `runtime.txt` — pins Python 3.11.9
- `app.json` — Heroku app manifest for one-click deploy + review apps
- `heroku.yml` — optional Docker-based deployment manifest
- `Aptfile` — optional system packages (only needed if you extend deps)
- `bot.py` auto-detects Heroku (`DYNO` env var) and uses an **in-memory session** to survive dyno restarts (Heroku's filesystem is ephemeral)

> **Why a `worker` dyno and not `web`?** Telegram bots use outbound long-polling — no inbound HTTP. A `web` dyno expects you to bind to `$PORT` within 60s, which would crash the bot.

### ⚠️ Important: Heroku + MongoDB

Heroku **no longer hosts** a native MongoDB add-on (the old `mLab` add-on was retired). You must use an external **MongoDB Atlas** cluster:

1. Create a free cluster at https://cloud.mongodb.com
2. Add a database user
3. Allow access from anywhere (`0.0.0.0/0`) — or just Heroku's NAT ranges if you prefer
4. Copy the `mongodb+srv://...` connection string into `MONGO_URI`

### ⚠️ Important: dyno type

Free `eco` dynos sleep after 30 min of inactivity and **will drop** the bot's long-polling connection. For a production bot use at least **Eco** ($5/mo for 1000 hours) or **Basic** ($7/dyno-month). The `app.json` defaults to `eco`.

### Option A — One-click deploy (fastest)

[![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/Yuki77394/Whisper)

Click the button, fill in the env vars in the Heroku web UI, and you're done. The app will boot, connect to your MongoDB Atlas, and start polling.

### Option B — Heroku CLI (recommended for power users)

```bash
# 1. Install Heroku CLI: https://devcenter.heroku.com/articles/heroku-cli
# 2. Login and create an app
heroku login
heroku create whisperx-your-suffix

# 3. Add the Heroku git remote and push
cd Whisper
heroku git:remote -a whisperx-your-suffix
git push heroku main

# 4. Set config vars (NEVER use a .env file on Heroku — it's ignored)
heroku config:set API_ID=1234567
heroku config:set API_HASH=your_api_hash
heroku config:set BOT_TOKEN=123456789:ABCDefghIJKLmnopQRSTuvwxYZ
heroku config:set MONGO_URI="mongodb+srv://user:pass@cluster0.xxxx.mongodb.net"
heroku config:set MONGO_DB_NAME=whisperx
heroku config:set OWNER_ID=123456789
heroku config:set LOG_GROUP_ID=-1001234567890
heroku config:set METADATA_ONLY_LOGS=false
heroku config:set WORKERS=4

# 5. Scale the worker dyno (this is what actually starts the bot)
heroku ps:scale worker=1

# 6. Watch the logs
heroku logs --tail
```

You should see something like:
```
2026-08-09T04:45:01.000000+00:00 app[worker.1]: Heroku detected — using in-memory session (no file persisted).
2026-08-09T04:45:02.000000+00:00 app[worker.1]: MongoDB connected & indexed: whisperx
2026-08-09T04:45:02.000000+00:00 app[worker.1]: Logged in as @WhisperXBot (id=123456789)
2026-08-09T04:45:02.000000+00:00 app[worker.1]: WhisperX is up.
```

### Option C — Docker on Heroku (advanced)

If you prefer to deploy via the `Dockerfile`:

```bash
heroku stack:set container -a whisperx-your-suffix
heroku container:push worker -a whisperx-your-suffix
heroku container:release worker -a whisperx-your-suffix
heroku ps:scale worker=1
heroku logs --tail
```

The `heroku.yml` file in this repo handles the rest.

### Heroku troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `Crashed` status within 60s of boot | You scaled `web` instead of `worker`. Run `heroku ps:scale worker=1 web=0`. |
| `MongoDB connection failed` | `MONGO_URI` is wrong or your Atlas IP allowlist is missing `0.0.0.0/0`. |
| Bot silent after first deploy | Inline mode is off in @BotFather — run `/setinline` on your bot. |
| Dyno sleeps every 30 min | You're on a free dyno. Upgrade to Eco ($5/mo) — `heroku dyno:type eco`. |
| `R10 (Boot timeout)` error | `web` dyno is being scaled. Make sure only `worker` is running. |
| Bot loses session every restart | Normal on Heroku — bot uses in-memory session by design. |
| Token in plain text in logs | Make sure `METADATA_ONLY_LOGS=true` if your logs are visible to others. |
| Need to update code | `git push heroku main` — Heroku auto-rebuilds and restarts. |

### Updating the bot on Heroku

```bash
git add .
git commit -m "your change"
git push origin main          # push to GitHub
git push heroku main          # push to Heroku (auto-redeploys)
heroku logs --tail            # watch the new version boot
```

---

## ⚙️ Environment variables

| Variable | Required | Description |
|---|---|---|
| `API_ID` | ✅ | Telegram API ID |
| `API_HASH` | ✅ | Telegram API hash |
| `BOT_TOKEN` | ✅ | Bot token from BotFather |
| `MONGO_URI` | ✅ | MongoDB connection string |
| `MONGO_DB_NAME` |  | DB name (default `whisperx`) |
| `LOG_GROUP_ID` |  | Private supergroup id (`-100…`) for logs |
| `OWNER_ID` | ✅ | Your Telegram user id |
| `ADMIN_IDS` |  | Comma-separated admin ids |
| `SUPPORT_CHAT` |  | `@supportchat` link |
| `UPDATE_CHANNEL` |  | `@updates` link |
| `METADATA_ONLY_LOGS` |  | `true` strips content from logs |
| `DEFAULT_EXPIRY_SECONDS` |  | Default whisper lifetime |
| `INLINE_CACHE_SECONDS` |  | Telegram-side inline cache TTL |
| `CLEANUP_INTERVAL_SECONDS` |  | Background sweeper interval |
| `RATE_LIMIT_PER_MINUTE` |  | Per-user inline query cap |
| `WORKERS` |  | Pyrogram worker count |
| `MAX_WHISPER_LENGTH` |  | Hard cap on text length |

---

## 🗄️ MongoDB indexes

Created automatically on startup by `database/mongo.py`:

| Collection | Index |
|---|---|
| `users` | `user_id` (unique) · `username_lower` · `created_at` |
| `whispers` | `whisper_id` (unique) · `sender_id` · `recipient_ids` · `status` · `expires_at` · `(sender_id, created_at)` |
| `whisper_access` | `(whisper_id, user_id)` (unique) · `whisper_id` · `user_id` |
| `history` | `(user_id, created_at)` · `whisper_id` |
| `settings` | `user_id` (unique) |
| `bans` | `user_id` (unique) |
| `stats` | `day` (unique) |
| `rate_limits` | `(user_id, bucket_minute)` (unique) · `expires_at` (TTL) |
| `create_state` | `user_id` (unique) · `updated_at` |

---

## 🎛 Command list

### User commands (private chat)
| Command | Description |
|---|---|
| `/start` | Welcome screen |
| `/help` | Help page |
| `/create` | Advanced whisper wizard |
| `/history` | Your whisper history |
| `/privacy` | Privacy settings |
| `/settings` | Bot settings |
| `/language` | Change language |
| `/cancel` | Cancel current creation |

### Admin commands
| Command | Description |
|---|---|
| `/stats` | Global bot statistics |
| `/users [page]` | Paginated user list |
| `/broadcast` | Reply to a message to broadcast |
| `/ban <id> [reason]` | Ban a user (or reply to them) |
| `/unban <id>` | Lift a ban |
| `/logs` | Toggle metadata-only logging |
| `/maintenance` | Toggle maintenance mode |
| `/settings` | Current settings |

### Inline usage (any chat)
```
@BotUsername @recipient Hello
@BotUsername Hello @recipient
@BotUsername Hello           ← public whisper
```

---

## 🔐 Admin configuration

1. Find your Telegram user id (e.g. via [@userinfobot](https://t.me/userinfobot)).
2. Add it to `.env`:
   ```env
   OWNER_ID=123456789
   ADMIN_IDS=123456789,987654321
   ```
3. Create a private supergroup for logs, add the bot as admin, then forward any message from it to [@userinfobot](https://t.me/userinfobot) to retrieve the `-100…` id:
   ```env
   LOG_GROUP_ID=-1001234567890
   ```
4. Restart the bot.

---

## ⚠️ Honest Telegram limitations

This bot does **not** claim features Telegram cannot technically deliver:

- ❌ **No screenshot detection** — Telegram bots cannot detect screenshots.
- ❌ **No perfect anonymity** — Telegram can still expose the bot itself; if a recipient reports the bot, Telegram can identify the underlying account.
- ❌ **Protected content is not un-copyable** — `protect_content` only disables *forwarding* inside Telegram. A user can still photograph their screen.
- ❌ **Inline media albums** — Telegram's inline mode does not support media-group results. Albums are supported in the `/create` wizard instead.
- ⚠️ **`file_id` rotation** — Telegram may rotate a bot's `file_id`s after ~1 week. Long-lived media whispers may fail to re-send; the bot falls back gracefully to a text notice.

---

## 🛠 Troubleshooting

### Bot doesn't respond to inline queries
1. Did you run `/setinline` in @BotFather? If not, inline mode is off.
2. Wait ~1 minute after enabling — Telegram caches inline availability.
3. Check the bot is running and Mongo is reachable.

### `MongoDB connection failed`
- Verify `MONGO_URI` — for Atlas, ensure your IP is allowlisted.
- For local Docker: ensure the `mongo` service is up (`docker compose ps`).

### Whisper opens show "media could not be delivered"
- The `file_id` has expired (Telegram rotates them after ~1 week).
- Workaround: sender should re-create the whisper.

### `FloodWait` errors in logs
- Pyrogram auto-sleeps the required amount. No action needed.
- If recurring, lower `RATE_LIMIT_PER_MINUTE`.

### `/broadcast` is slow
- Intentional: we throttle at 0.05s/user to avoid FloodWait.
- For 10k+ users, split into batches and run overnight.

### Bot can't open logs in supergroup
- Add the bot as **admin** with **post messages** permission in the log group.
- Verify `LOG_GROUP_ID` starts with `-100`.

### Callback button shows "❌ Invalid request"
- Whisper id didn't match the 24-hex format (corrupted callback data).
- Usually means a stale button on an old message — send a new whisper.

### `Missing required environment variables`
- Re-check `.env`. All variables marked ✅ in the table above are mandatory.

---

## 🧪 Development notes

- The codebase is fully async; never call blocking I/O inside handlers.
- All user-facing strings live in `utils/formatting.py` and `handlers/start.py` (welcome/help text) — easy to localise.
- To add a new language: extend `language_kb()` and replace strings via a dict lookup (English is wired up by default).
- The `/create` state machine is DB-backed (`create_state` collection) so it survives restarts.
- The cleanup worker runs every 5 min by default — tune via `CLEANUP_INTERVAL_SECONDS`.

---

## 📜 License

MIT — see `LICENSE` (add your own if you fork).

---

## 🤝 Credits

Built with [Pyrogram](https://pyrogram.org) and [Motor](https://motor.readthedocs.io).
