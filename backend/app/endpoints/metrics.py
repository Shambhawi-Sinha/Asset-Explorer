"""
endpoints/metrics.py — GET /api/metrics/{asset_id}

Returns time-series health metric data for an individual transformer.
Loaded when a user drills into a specific asset in the Asset List tab.

Each metric endpoint returns a time series — React renders each as a
trend chart in the asset drill-down view (5 chart panels per asset).

Endpoints:
  GET /api/metrics/{asset_id}/thermal   — FAA + hotspot over time
  GET /api/metrics/{asset_id}/overload  — overload severity over time
  GET /api/metrics/{asset_id}/tap       — tap changer stress over time
  GET /api/metrics/{asset_id}/winding   — winding temperature over time
  GET /api/metrics/{asset_id}/workorders — work order timeline

All 5 called in parallel by React with Promise.all.
"""

import os
import json
import pathlib
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["metrics"])

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"


class MetricPoint(BaseModel):
    timestamp: str
    value: float


class WorkOrderRecord(BaseModel):
    wo_id: str
    created_date: str
    wo_type: str                         # PREVENTIVE | CORRECTIVE | EMERGENCY
    description: str
    failure_code: Optional[str] = None
    completion_date: Optional[str] = None
    is_open_emergency: bool = False


@router.get("/metrics/{asset_id}/thermal", response_model=List[MetricPoint])
def get_thermal(asset_id: str):
    """Thermal Aging Factor (FAA) time series for one transformer."""
    if MOCK_MODE:
        return _mock_metric_series(asset_id, "thermal_aging_factor")
    return _query_metric(asset_id, "THERMAL_AGING_FACTOR")


@router.get("/metrics/{asset_id}/overload", response_model=List[MetricPoint])
def get_overload(asset_id: str):
    """Overload Severity time series."""
    if MOCK_MODE:
        return _mock_metric_series(asset_id, "overload_severity")
    return _query_metric(asset_id, "OVERLOAD_SEVERITY")


@router.get("/metrics/{asset_id}/tap", response_model=List[MetricPoint])
def get_tap(asset_id: str):
    """Tap Changer Stress (daily TPOSC ops) time series."""
    if MOCK_MODE:
        return _mock_metric_series(asset_id, "tap_changer_stress")
    return _query_metric(asset_id, "TAP_CHANGER_STRESS")


@router.get("/metrics/{asset_id}/winding", response_model=List[MetricPoint])
def get_winding(asset_id: str):
    """Mean Winding Temperature time series."""
    if MOCK_MODE:
        return _mock_metric_series(asset_id, "mean_winding_temp")
    return _query_metric(asset_id, "MEAN_WINDING_TEMP")


@router.get("/metrics/{asset_id}/workorders", response_model=List[WorkOrderRecord])
def get_workorders(asset_id: str):
    """Work order timeline for one transformer, most recent first."""
    if MOCK_MODE:
        return _mock_workorders(asset_id)
    return _query_workorders(asset_id)


# ---------------------------------------------------------------------------
# Live Oracle queries
# ---------------------------------------------------------------------------

def _query_metric(asset_id: str, column: str) -> List[MetricPoint]:
    from app.core.db import query_to_dicts
    sql = f"""
        SELECT TO_CHAR(READING_DATE, 'YYYY-MM-DD') AS TIMESTAMP,
               {column} AS VALUE
        FROM ASSET_METRIC_HISTORY
        WHERE ASSET_ID = :asset_id
          AND READING_DATE >= TRUNC(SYSDATE) - 90
          AND {column} IS NOT NULL
        ORDER BY READING_DATE
    """
    try:
        rows = query_to_dicts(sql, {"asset_id": asset_id})
        return [MetricPoint(timestamp=r["TIMESTAMP"], value=float(r["VALUE"])) for r in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Metric query failed: {exc}")


def _query_workorders(asset_id: str) -> List[WorkOrderRecord]:
    from app.core.db import query_to_dicts
    sql = """
        SELECT
            WO_ID,
            TO_CHAR(CREATED_DATE, 'YYYY-MM-DD') AS CREATED_DATE,
            WO_TYPE,
            DESCRIPTION,
            FAILURE_CODE,
            TO_CHAR(COMPLETION_DATE, 'YYYY-MM-DD') AS COMPLETION_DATE
        FROM WORK_ORDERS
        WHERE ASSET_ID = :asset_id
        ORDER BY CREATED_DATE DESC
    """
    try:
        rows = query_to_dicts(sql, {"asset_id": asset_id})
        return [
            WorkOrderRecord(
                wo_id=r["WO_ID"],
                created_date=r["CREATED_DATE"],
                wo_type=r["WO_TYPE"],
                description=r["DESCRIPTION"],
                failure_code=r.get("FAILURE_CODE"),
                completion_date=r.get("COMPLETION_DATE"),
                is_open_emergency=(r["WO_TYPE"] == "EMERGENCY" and not r.get("COMPLETION_DATE")),
            )
            for r in rows
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Work order query failed: {exc}")


# ---------------------------------------------------------------------------
# Mock data helpers
# ---------------------------------------------------------------------------

def _mock_metric_series(asset_id: str, metric_key: str) -> List[MetricPoint]:
    """Generate 90-day mock time series for one metric."""
    from datetime import date, timedelta
    import math, hashlib

    # Deterministic seed per asset+metric so same asset always shows same trend
    seed = int(hashlib.md5(f"{asset_id}{metric_key}".encode()).hexdigest()[:8], 16)
    base_values = {
        "thermal_aging_factor": (1.0, 0.5),
        "overload_severity":    (0.85, 0.1),
        "tap_changer_stress":   (20.0, 5.0),
        "mean_winding_temp":    (75.0, 8.0),
    }
    base, amplitude = base_values.get(metric_key, (50.0, 10.0))
    today = date.today()
    points = []
    for i in range(90):
        day = today - timedelta(days=89 - i)
        # Slight upward trend + seasonal sine + noise
        noise = math.sin(seed + i * 0.3) * amplitude * 0.5
        trend = i * (amplitude * 0.003)
        value = round(max(0, base + trend + noise), 3)
        points.append(MetricPoint(timestamp=str(day), value=value))
    return points


def _mock_workorders(asset_id: str) -> List[WorkOrderRecord]:
    path = pathlib.Path(__file__).parents[3] / "sample_data" / "work_orders.json"
    with open(path) as f:
        all_wos = json.load(f)

    asset_wos = [wo for wo in all_wos if wo["asset_id"] == asset_id]
    return [
        WorkOrderRecord(
            wo_id=wo["wo_id"],
            created_date=wo["created_date"],
            wo_type=wo["wo_type"],
            description=wo["description"],
            failure_code=wo.get("failure_code"),
            completion_date=wo.get("completion_date"),
            is_open_emergency=(wo["wo_type"] == "EMERGENCY" and not wo.get("completion_date")),
        )
        for wo in sorted(asset_wos, key=lambda x: x["created_date"], reverse=True)
    ]
