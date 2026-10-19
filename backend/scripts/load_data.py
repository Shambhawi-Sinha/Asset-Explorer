"""
scripts/load_data.py — Pre-warm and compatibility script

Run by entrypoint.sh before Gunicorn starts.
Verifies Oracle connectivity and pre-warms the connection pool.

If this script fails (exception, sys.exit), entrypoint.sh aborts startup,
preventing the load balancer from routing traffic to a degraded container.
"""

import sys
import logging

logging.basicConfig(level=logging.INFO, format="[load_data] %(message)s")
logger = logging.getLogger(__name__)


def verify_oracle_connectivity():
    """Verify Oracle ADB is reachable with mTLS wallet."""
    from app.core.db import query_to_dicts
    rows = query_to_dicts("SELECT 1 AS TEST FROM DUAL")
    if not rows or rows[0].get("TEST") != 1:
        raise RuntimeError("Oracle connectivity check returned unexpected result")
    logger.info("Oracle ADB connectivity: OK")


def verify_required_views():
    """Check that required DB views exist (fail fast before serving traffic)."""
    from app.core.db import query_to_dicts
    views = ["SUBSTATION_HEALTH_VW", "WORK_ORDER_SUMMARY_VW"]
    for view in views:
        query_to_dicts(f"SELECT COUNT(*) AS CNT FROM {view} WHERE ROWNUM = 1")
        logger.info(f"View {view}: accessible")


def main():
    import os
    mock_mode = os.getenv("MOCK_MODE", "false").lower() == "true"
    if mock_mode:
        logger.info("Mock mode — skipping Oracle checks")
        return

    try:
        verify_oracle_connectivity()
        verify_required_views()
        logger.info("All pre-flight checks passed — ready to serve")
    except Exception as exc:
        logger.error(f"Pre-flight check failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
