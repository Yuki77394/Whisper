# ──────────────────────────────────────────────────────────────
#  WhisperX – Docker image
#  Python 3.11-slim + Pyrogram + Motor
# ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Avoid writing .pyc files & force unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps (TgCrypto needs gcc + libc)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Non-root user for safety
RUN useradd -m -u 10001 whisperx && chown -R whisperx:whisperx /app
USER whisperx

# Bot uses long polling
CMD ["python", "bot.py"]
