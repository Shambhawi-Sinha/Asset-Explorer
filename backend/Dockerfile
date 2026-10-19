# ──────────────────────────────────────────────────────────────────────
# Backend Dockerfile — Python/Gunicorn multi-stage build
# ──────────────────────────────────────────────────────────────────────
#
# Stage 1 (build): Install dependencies using uv (fast package manager).
#   Private package feed credentials passed as BuildKit secrets —
#   NEVER as build args or ENV (those appear in docker history).
#
# Stage 2 (runtime): Minimal Python image, non-root user.
#   entrypoint.sh runs before Gunicorn:
#     OCI Resource Principal → fetch wallet from OCI Vault → verify → start Gunicorn
#
# Key design decisions:
#   - BuildKit secrets for private feed credentials: never in image layers
#   - OCI CLI installed for Resource Principal vault fetch in entrypoint.sh
#   - Non-root 'appuser' (UID 1000) — OCI Container Instances requirement
#   - Wallet NOT in image: fetched at runtime from OCI Vault
#   - Health check: GET /health (verifies Oracle connectivity via SELECT 1 FROM DUAL)
#
# Build:
#   DOCKER_BUILDKIT=1 docker build \
#     --secret id=pip_index_url,env=PRIVATE_FEED_URL \
#     -t asset-explorer-api:latest .
#
# Run (mock mode — no OCI):
#   docker run -e MOCK_MODE=true -p 8000:8000 asset-explorer-api:latest
# ──────────────────────────────────────────────────────────────────────

# ── Stage 1: Build ──────────────────────────────────────────────────
FROM python:3.12-slim AS build

WORKDIR /build

# Install uv (fast Python package manager — replaces pip for install speed)
RUN pip install --no-cache-dir uv==0.3.0

COPY requirements.txt .

# Install dependencies.
# Private package feed URL mounted as BuildKit secret — never in image layer.
# In open-source / mock mode: standard PyPI only, secret not needed.
RUN --mount=type=secret,id=pip_index_url \
    if [ -f /run/secrets/pip_index_url ]; then \
        export PIP_EXTRA_INDEX_URL=$(cat /run/secrets/pip_index_url); \
    fi && \
    uv pip install --system --no-cache -r requirements.txt


# ── Stage 2: Runtime ────────────────────────────────────────────────
FROM python:3.12-slim

# Install OCI CLI (needed by entrypoint.sh for vault wallet fetch)
# Also installs curl for health checks and debugging
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && pip install --no-cache-dir oci-cli==3.43.1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy installed packages from build stage
COPY --from=build /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=build /usr/local/bin /usr/local/bin

WORKDIR /app

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY sample_data/ ./sample_data/

# Create non-root user (OCI Container Instances run as non-root by default)
RUN useradd --uid 1000 --no-create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app

# Make entrypoint executable
RUN chmod +x scripts/entrypoint.sh

USER appuser

# Wallet directory — empty here; populated at runtime by entrypoint.sh
# (wallet files are NEVER baked into the image)
RUN mkdir -p /app/wallet

EXPOSE 8000

# Health check: verifies Oracle connectivity (SELECT 1 FROM DUAL)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

ENTRYPOINT ["scripts/entrypoint.sh"]
