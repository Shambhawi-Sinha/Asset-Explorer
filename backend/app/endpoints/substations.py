"""
endpoints/substations.py — GET /api/substations

Returns the full list of transformer records with health scores and risk bands.
Loaded by the React Asset List tab (Tab 2).

Performance:
  In production, health scores are precomputed by the offline pipeline and
  stored in SUBSTATION_HEALTH_VW. No real-time metric calculation on request.
  ~2–3s load time for 987 transformers via ThreadPoolExecutor precompute.
"""

import os
import csv
import pathlib
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["substations"])

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"


class TransformerRecord(BaseModel):
    asset_id: str
    substation_id: str
    substation_name: str
    region: Optional[str] = None
    voltage_kv: Optional[float] = None
    rating_mva: Optional[float] = None
    health_score: float                              # 0–100, higher = healthier
    risk_band: str                                   # GREEN | AMBER | RED
    mean_winding_temp: Optional[float] = None        # °C, rolling 24h avg
    hotspot_temp: Optional[float] = None             # °C, IEEE C57.91 model
    thermal_aging_factor: Optional[float] = None     # FAA, IEC 60076-7 (1=normal)
    overload_severity: Optional[float] = None        # MVA_actual / MVA_rated
    tap_changer_stress: Optional[float] = None       # daily TPOSC operations
    load_temp_sensitivity: Optional[float] = None    # Pearson r (load vs temp)
    last_inspection_date: Optional[str] = None
    photo_record_id: Optional[str] = None            # Fulcrum record ID → /api/photo
    open_emergency_wos: Optional[int] = None
    total_work_orders: Optional[int] = None


@router.get("/substations", response_model=List[TransformerRecord])
def get_substations():
    """
    Fetch all transformer records ordered by health score ascending
    (worst first — critical assets appear at top of Asset List tab).
    """
    if MOCK_MODE:
        return _load_mock()
    return _query_oracle()


def _query_oracle() -> List[dict]:
    from app.core.db import query_to_dicts
    sql = """
        SELECT
            v.ASSET_ID,
            v.SUBSTATION_ID,
            v.SUBSTATION_NAME,
            v.REGION,
            v.VOLTAGE_KV,
            v.RATING_MVA,
            v.HEALTH_SCORE,
            v.RISK_BAND,
            v.MEAN_WINDING_TEMP,
            v.HOTSPOT_TEMP,
            v.THERMAL_AGING_FACTOR,
            v.OVERLOAD_SEVERITY,
            v.TAP_CHANGER_STRESS,
            v.LOAD_TEMP_SENSITIVITY,
            TO_CHAR(v.LAST_INSPECTION_DATE, 'YYYY-MM-DD') AS LAST_INSPECTION_DATE,
            v.PHOTO_RECORD_ID,
            w.OPEN_EMERGENCY_WOS,
            w.TOTAL_WORK_ORDERS
        FROM SUBSTATION_HEALTH_VW v
        LEFT JOIN WORK_ORDER_SUMMARY_VW w ON v.ASSET_ID = w.ASSET_ID
        ORDER BY v.HEALTH_SCORE ASC
    """
    try:
        return query_to_dicts(sql)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Oracle query failed: {exc}")


def _load_mock() -> List[dict]:
    path = pathlib.Path(__file__).parents[3] / "sample_data" / "health_scores.csv"
    records = []
    with open(path) as f:
        for row in csv.DictReader(f):
            records.append({
                "asset_id":              row["asset_id"],
                "substation_id":         row["substation_id"],
                "substation_name":       row["substation_name"],
                "region":                row.get("region"),
                "voltage_kv":            float(row["voltage_kv"]) if row.get("voltage_kv") else None,
                "rating_mva":            float(row["rating_mva"]) if row.get("rating_mva") else None,
                "health_score":          float(row["health_score"]),
                "risk_band":             row["risk_band"],
                "mean_winding_temp":     float(row["mean_winding_temp"]) if row.get("mean_winding_temp") else None,
                "hotspot_temp":          float(row["hotspot_temp"]) if row.get("hotspot_temp") else None,
                "thermal_aging_factor":  float(row["thermal_aging_factor"]) if row.get("thermal_aging_factor") else None,
                "overload_severity":     float(row["overload_severity"]) if row.get("overload_severity") else None,
                "tap_changer_stress":    float(row["tap_changer_stress"]) if row.get("tap_changer_stress") else None,
                "load_temp_sensitivity": float(row["load_temp_sensitivity"]) if row.get("load_temp_sensitivity") else None,
                "last_inspection_date":  row.get("last_inspection_date"),
                "photo_record_id":       row.get("photo_record_id"),
                "open_emergency_wos":    int(row["open_emergency_wos"]) if row.get("open_emergency_wos") else 0,
                "total_work_orders":     int(row["total_work_orders"]) if row.get("total_work_orders") else 0,
            })
    return records
