"""
endpoints/fleet.py — GET /api/fleet

Returns fleet-wide KPI summary loaded by the Fleet Overview tab (Tab 1).

Parallel computation via ThreadPoolExecutor:
  The fleet summary requires three Oracle queries:
    1. Health band counts (GREEN/AMBER/RED)
    2. Top 5 critical transformers (lowest health score)
    3. Fleet health trend (last 30 days)

  These run in parallel using ThreadPoolExecutor, reducing load time
  from ~4s (sequential) to ~2-3s.
"""

import os
import json
import pathlib
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["fleet"])

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"


class BandCounts(BaseModel):
    green: int
    amber: int
    red: int
    total: int


class TopTransformer(BaseModel):
    asset_id: str
    substation_name: str
    health_score: float
    risk_band: str
    open_emergency_wos: int


class TrendPoint(BaseModel):
    date: str
    avg_health_score: float
    red_count: int


class FleetSummary(BaseModel):
    band_counts: BandCounts
    top_critical: List[TopTransformer]
    health_trend: List[TrendPoint]


@router.get("/fleet", response_model=FleetSummary)
def get_fleet():
    """
    Fleet-wide KPI summary for the Overview tab.
    Uses ThreadPoolExecutor for parallel Oracle queries.
    """
    if MOCK_MODE:
        return _load_mock_fleet()

    executor = _get_executor()
    futures = {
        executor.submit(_query_band_counts):  "band_counts",
        executor.submit(_query_top_critical): "top_critical",
        executor.submit(_query_health_trend): "health_trend",
    }

    results = {}
    for future in as_completed(futures):
        key = futures[future]
        try:
            results[key] = future.result()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Fleet query failed ({key}): {exc}")

    return FleetSummary(
        band_counts=results["band_counts"],
        top_critical=results["top_critical"],
        health_trend=results["health_trend"],
    )


def _get_executor() -> ThreadPoolExecutor:
    from app.core.db import get_executor
    return get_executor()


def _query_band_counts() -> BandCounts:
    from app.core.db import query_to_dicts
    rows = query_to_dicts("""
        SELECT RISK_BAND, COUNT(*) AS CNT
        FROM SUBSTATION_HEALTH_VW
        GROUP BY RISK_BAND
    """)
    counts = {r["RISK_BAND"]: r["CNT"] for r in rows}
    green = counts.get("GREEN", 0)
    amber = counts.get("AMBER", 0)
    red   = counts.get("RED", 0)
    return BandCounts(green=green, amber=amber, red=red, total=green + amber + red)


def _query_top_critical() -> List[TopTransformer]:
    from app.core.db import query_to_dicts
    rows = query_to_dicts("""
        SELECT v.ASSET_ID, v.SUBSTATION_NAME, v.HEALTH_SCORE, v.RISK_BAND,
               NVL(w.OPEN_EMERGENCY_WOS, 0) AS OPEN_EMERGENCY_WOS
        FROM SUBSTATION_HEALTH_VW v
        LEFT JOIN WORK_ORDER_SUMMARY_VW w ON v.ASSET_ID = w.ASSET_ID
        ORDER BY v.HEALTH_SCORE ASC
        FETCH FIRST 5 ROWS ONLY
    """)
    return [
        TopTransformer(
            asset_id=r["ASSET_ID"],
            substation_name=r["SUBSTATION_NAME"],
            health_score=float(r["HEALTH_SCORE"]),
            risk_band=r["RISK_BAND"],
            open_emergency_wos=int(r["OPEN_EMERGENCY_WOS"]),
        )
        for r in rows
    ]


def _query_health_trend() -> List[TrendPoint]:
    from app.core.db import query_to_dicts
    rows = query_to_dicts("""
        SELECT
            TRUNC(SCORE_DATE) AS SCORE_DATE,
            ROUND(AVG(HEALTH_SCORE), 1) AS AVG_HEALTH_SCORE,
            SUM(CASE WHEN RISK_BAND = 'RED' THEN 1 ELSE 0 END) AS RED_COUNT
        FROM HEALTH_SCORE_HISTORY
        WHERE SCORE_DATE >= TRUNC(SYSDATE) - 30
        GROUP BY TRUNC(SCORE_DATE)
        ORDER BY TRUNC(SCORE_DATE)
    """)
    return [
        TrendPoint(
            date=str(r["SCORE_DATE"])[:10],
            avg_health_score=float(r["AVG_HEALTH_SCORE"]),
            red_count=int(r["RED_COUNT"]),
        )
        for r in rows
    ]


def _load_mock_fleet() -> FleetSummary:
    """Aggregate mock data from sample_data/ files."""
    path = pathlib.Path(__file__).parents[3] / "sample_data" / "health_scores.csv"
    import csv
    records = []
    with open(path) as f:
        for row in csv.DictReader(f):
            records.append(row)

    green = sum(1 for r in records if r["risk_band"] == "GREEN")
    amber = sum(1 for r in records if r["risk_band"] == "AMBER")
    red   = sum(1 for r in records if r["risk_band"] == "RED")

    top_critical = sorted(records, key=lambda r: float(r["health_score"]))[:5]

    # Load trend from mock trend file if present, else generate flat
    trend_path = pathlib.Path(__file__).parents[3] / "sample_data" / "health_trend.json"
    if trend_path.exists():
        with open(trend_path) as f:
            trend_raw = json.load(f)
        trend = [TrendPoint(**t) for t in trend_raw]
    else:
        # Generate 30-day flat trend from current mock data
        from datetime import date, timedelta
        avg = round(sum(float(r["health_score"]) for r in records) / len(records), 1) if records else 65.0
        today = date.today()
        trend = [
            TrendPoint(
                date=str(today - timedelta(days=29 - i)),
                avg_health_score=round(avg + (i * 0.1 - 1.5), 1),
                red_count=red,
            )
            for i in range(30)
        ]

    return FleetSummary(
        band_counts=BandCounts(green=green, amber=amber, red=red, total=len(records)),
        top_critical=[
            TopTransformer(
                asset_id=r["asset_id"],
                substation_name=r["substation_name"],
                health_score=float(r["health_score"]),
                risk_band=r["risk_band"],
                open_emergency_wos=int(r.get("open_emergency_wos", 0)),
            )
            for r in top_critical
        ],
        health_trend=trend,
    )
