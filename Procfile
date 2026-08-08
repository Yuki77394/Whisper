# ──────────────────────────────────────────────────────────────
#  WhisperX – Heroku process declaration
#
#  A Telegram bot uses long-polling (no inbound HTTP), so we run
#  as a `worker` dyno, NOT a `web` dyno. Never scale a `web` dyno
#  for this bot — it would crash on boot because nothing binds
#  to $PORT.
# ──────────────────────────────────────────────────────────────
worker: python bot.py
