#!/bin/bash
# entrypoint.sh — Backend container startup script
#
# Runs BEFORE Gunicorn starts. Fetches wallet from OCI Vault using
# OCI Resource Principal authentication (no hardcoded credentials).
#
# If ANY step fails, the container exits immediately.
# This prevents the OCI load balancer from routing traffic to a container
# that cannot reach the database — fail-fast over silent degradation.
#
# Steps:
#   1. OCI Resource Principal auth → fetch wallet parts from OCI Vault
#   2. Decode and assemble wallet files into /app/wallet/
#   3. Run load_data.py (compatibility/pre-warm script)
#   4. Exec Gunicorn (replaces this process — PID 1)
#
# In local dev / mock mode: skip all OCI steps, go straight to Gunicorn.

set -euo pipefail   # Exit on any error; treat unset vars as errors; fail on pipe errors

WALLET_DIR="${OCI_WALLET_DIR:-/app/wallet}"
MOCK_MODE="${MOCK_MODE:-false}"

log() { echo "[entrypoint] $*" >&2; }

# ──────────────────────────────────────────────────────────────────
# Skip wallet fetch in mock mode (local dev / CI)
# ──────────────────────────────────────────────────────────────────
if [ "$MOCK_MODE" = "true" ]; then
    log "Mock mode — skipping OCI Vault wallet fetch"
else
    log "Starting OCI wallet fetch via Resource Principal..."

    # Verify OCI CLI is available (installed in Dockerfile)
    if ! command -v oci &>/dev/null; then
        log "ERROR: OCI CLI not found — cannot fetch wallet"
        exit 1
    fi

    # Fetch wallet components from OCI Vault using Resource Principal
    # (the OCI Container Instance identity IS the credential — no key file)
    VAULT_ID="${OCI_VAULT_ID:?OCI_VAULT_ID must be set}"
    mkdir -p "$WALLET_DIR"

    log "Fetching ewallet.pem from Vault secret ${OCI_SECRET_EWALLET_OCID}..."
    oci secrets secret-bundle get \
        --secret-id "${OCI_SECRET_EWALLET_OCID:?}" \
        --auth instance_principal \
        --query "data.\"secret-bundle-content\".content" \
        --raw-output \
        | base64 --decode > "${WALLET_DIR}/ewallet.pem"

    log "Fetching tnsnames.ora from Vault..."
    oci secrets secret-bundle get \
        --secret-id "${OCI_SECRET_TNSNAMES_OCID:?}" \
        --auth instance_principal \
        --query "data.\"secret-bundle-content\".content" \
        --raw-output \
        | base64 --decode > "${WALLET_DIR}/tnsnames.ora"

    log "Fetching sqlnet.ora from Vault..."
    oci secrets secret-bundle get \
        --secret-id "${OCI_SECRET_SQLNET_OCID:?}" \
        --auth instance_principal \
        --query "data.\"secret-bundle-content\".content" \
        --raw-output \
        | base64 --decode > "${WALLET_DIR}/sqlnet.ora"

    # Verify all wallet files present
    for f in ewallet.pem tnsnames.ora sqlnet.ora; do
        if [ ! -s "${WALLET_DIR}/${f}" ]; then
            log "ERROR: Wallet file ${f} is missing or empty after fetch"
            exit 1
        fi
    done

    log "Wallet assembled successfully at ${WALLET_DIR}"

    # Run pre-warm / compatibility script
    log "Running load_data.py..."
    python3 scripts/load_data.py || {
        log "ERROR: load_data.py failed — aborting startup"
        exit 1
    }
fi

# ──────────────────────────────────────────────────────────────────
# Start Gunicorn (exec replaces this shell process → PID 1)
# Gunicorn manages UvicornWorker processes for async FastAPI handling
# ──────────────────────────────────────────────────────────────────
WORKERS="${GUNICORN_WORKERS:-2}"
PORT="${PORT:-8000}"

log "Starting Gunicorn on port ${PORT} with ${WORKERS} UvicornWorker(s)..."

exec gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers "${WORKERS}" \
    --bind "0.0.0.0:${PORT}" \
    --timeout 120 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile -
