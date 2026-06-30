# Always-on Job Assistant: runs the single-process `serve` loop (scheduled
# collect + weekly summary + live Telegram button/command handling) against a
# persistent SQLite volume. See DEPLOY.md.
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so this layer caches across code changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Preferences are baked into the image; the database lives on a mounted volume.
COPY config ./config
VOLUME ["/data"]

# Secrets come from the environment (NOT baked in):
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  (required)
#   IMAP_USERNAME, IMAP_PASSWORD          (optional, for the LinkedIn email source)
CMD ["python", "-m", "job_assistant.cli", "--db", "/data/jobs.db", "serve"]
