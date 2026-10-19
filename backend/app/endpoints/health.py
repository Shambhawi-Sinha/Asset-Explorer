"""
endpoints/health.py — GET /health

Liveness/readiness probe. Used by:
  - Docker HEALTHCHECK
  - OCI Load Balancer health check (must return 200 before traffic cutover)
  - Azure DevOps pipeline — waits for 200 after deploy before draining old instance

In live mode: verifies Oracle DB connectivity with SELECT 1 FROM DUAL.
In mock mode: returns healthy without a DB call.
"""

import os
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"


class HealthResponse(BaseModel):
    status: str
    db: str
    mode: str


@router.get("/health", response_model=HealthResponse)
def health_check():
    if MOCK_MODE:
        return HealthResponse(status="healthy", db="mock", mode="mock")

    db_status = "ok"
    try:
        from app.core.db import query_to_dicts
        query_to_dicts("SELECT 1 FROM DUAL")
    except Exception as exc:
        db_status = f"error: {exc}"

    overall = "healthy" if db_status == "ok" else "degraded"
    return HealthResponse(status=overall, db=db_status, mode="live")
