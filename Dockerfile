# ── Builder stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Build dependencies only (not copied to final image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy project source
COPY ../lanekit .

# Copy & permission entrypoint
COPY docker/app/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Non-root user for security
RUN useradd -m -u 1000 lanekit \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R lanekit:lanekit /app

USER lanekit

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

# Production default – override in dev compose with runserver
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "swimmingclub.asgi:application"]
