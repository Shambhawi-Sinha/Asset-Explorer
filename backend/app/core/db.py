"""
app/core/db.py — Oracle Autonomous Database connection

Uses mTLS wallet authentication in thin mode (no Instant Client required).
Wallet files are fetched from OCI Vault by entrypoint.sh before Gunicorn
starts — they are never baked into the Docker image.

Authentication path:
  On OCI Container Instance:
    entrypoint.sh → OCI Resource Principal → fetch wallet from Vault
    → assemble wallet dir → start Gunicorn
  Local dev (MOCK_MODE=true):
    No Oracle connection — all data served from sample_data/

Known operational issues:
  - Corporate VM DNS may fail to resolve ADB hostnames (adb.*.oraclecloud.com)
    Fix: set DNS to 8.8.8.8, verify with: Test-NetConnection <host> -Port 1522
  - Wallet path must exactly match OCI_WALLET_DIR env var
  - oracledb thin mode: wallet_location must contain ewallet.pem, not ewallet.p12
"""

import os
import logging
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor

import oracledb

logger = logging.getLogger(__name__)

WALLET_DIR = os.getenv("OCI_WALLET_DIR", "./wallet")
DB_USER    = os.getenv("OCI_DB_USERNAME")
DB_PASS    = os.getenv("OCI_DB_PASSWORD")
DB_DSN     = os.getenv("OCI_DB_DSN")

# Thread pool for parallel metric computation (see endpoints/metrics.py)
_executor = ThreadPoolExecutor(max_workers=int(os.getenv("DB_THREAD_WORKERS", "4")))


def get_connection() -> oracledb.Connection:
    """
    Return an Oracle ADB connection using mTLS wallet (thin mode).

    Required wallet files in OCI_WALLET_DIR:
      ewallet.pem   — SSL certificate
      tnsnames.ora  — connection descriptor
      sqlnet.ora    — wallet location pointer
    """
    return oracledb.connect(
        user=DB_USER,
        password=DB_PASS,
        dsn=DB_DSN,
        wallet_location=WALLET_DIR,
        wallet_password=os.getenv("OCI_WALLET_PASSWORD"),
    )


def query_to_dicts(sql: str, params: Optional[Dict] = None) -> List[Dict]:
    """Execute SQL and return rows as list of dicts with uppercased keys."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            cols = [col[0].upper() for col in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_executor() -> ThreadPoolExecutor:
    """Return the shared thread pool for parallel DB queries."""
    return _executor
