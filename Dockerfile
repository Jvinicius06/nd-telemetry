# Single-stage, single Dockerfile. Plain HTTP, no SSL/TLS.
FROM python:3.12-slim

WORKDIR /app

# Install deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app ./app

# Defaults (override at runtime with -e)
# ND_DISCORD_WEBHOOK: set to a Discord webhook URL to get crash alerts.
# ND_DISCORD_MIN_INTERVAL: per-device throttle (s). ND_DASHBOARD_URL: link base.
ENV ND_DB_PATH=/data/telemetry.db \
    ND_DEVICE_PORT=8080 \
    ND_DASHBOARD_PORT=8081 \
    ND_ADMIN_USER=admin \
    ND_ADMIN_PASS=admin \
    ND_DISCORD_WEBHOOK="" \
    ND_DISCORD_MIN_INTERVAL=60 \
    ND_DASHBOARD_URL="" \
    PYTHONUNBUFFERED=1

# /data holds the SQLite DB (mount a volume to persist)
VOLUME ["/data"]

# 8080 = device ingest API (low cost)   8081 = admin dashboard
EXPOSE 8080 8081

CMD ["python", "-m", "app.main"]
