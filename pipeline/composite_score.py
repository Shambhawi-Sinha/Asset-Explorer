"""
composite_score.py — Weighted composite health score (0–100)
=============================================================
Combines the five normalised sub-metrics from health_metrics.py into a single
0-100 health index and assigns a risk band (GREEN / AMBER / RED).

Weighting rationale (based on IEC 60076-7 and IEEE C57.91 risk studies):
  - FAA thermal aging (30%)   — dominant predictor of insulation end-of-life
  - Hotspot temperature (25%) — direct insulation stress; short-term failure risk
  - Overload severity  (20%)  — sustained overload accelerates all failure modes
  - Winding resistance (10%)  — leading indicator of inter-winding faults
  - Tap changer stress (10%)  — mechanical wear; most-frequent corrective WO cause
  - Load-temp sensitivity (5%)— sensor/cooling anomaly; lowest direct impact

Risk bands:
  GREEN  > 70   — Healthy; standard inspection schedule
  AMBER  40–70  — Degraded; increase monitoring frequency
  RED    < 40   — Critical; immediate intervention required
"""

from dataclasses import dataclass
from typing import Literal

from health_metrics import MetricResult


# ── Weights — must sum to 1.0 ─────────────────────────────────────────────────

WEIGHTS = {
    "faa":         0.30,
    "hotspot":     0.25,
    "overload":    0.20,
    "winding":     0.10,
    "tap":         0.10,
    "sensitivity": 0.05,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"


# ── Thresholds ────────────────────────────────────────────────────────────────

BAND_THRESHOLDS = {"GREEN": 70.0, "AMBER": 40.0}   # Lower bound of each band

RiskBand = Literal["GREEN", "AMBER", "RED"]


# ── Score dataclass ───────────────────────────────────────────────────────────

@dataclass
class HealthScore:
    asset_id: str
    composite_score: float          # 0–100 (100 = perfect health)
    risk_band: RiskBand
    # Sub-metric contributions (each × weight × 100 for display)
    faa_contribution:         float
    hotspot_contribution:     float
    overload_contribution:    float
    tap_contribution:         float
    winding_contribution:     float
    sensitivity_contribution: float


# ── Core calculation ──────────────────────────────────────────────────────────

def composite_health_score(metrics: MetricResult) -> HealthScore:
    """
    Compute weighted composite health score from normalised sub-metrics.

    Each normalised metric is in [0, 1] where 1 = worst condition.
    We invert to a health direction: health_component = (1 - metric_norm) × weight.
    Final score = sum of health components × 100.

    Args:
        metrics: MetricResult from health_metrics.calculate_metrics_for_asset()

    Returns:
        HealthScore with composite 0-100 score and risk band.
    """
    components = {
        "faa":         (1.0 - metrics.faa_normalised)         * WEIGHTS["faa"],
        "hotspot":     (1.0 - metrics.hotspot_normalised)     * WEIGHTS["hotspot"],
        "overload":    (1.0 - metrics.overload_normalised)    * WEIGHTS["overload"],
        "winding":     (1.0 - metrics.winding_normalised)     * WEIGHTS["winding"],
        "tap":         (1.0 - metrics.tap_normalised)         * WEIGHTS["tap"],
        "sensitivity": (1.0 - metrics.sensitivity_normalised) * WEIGHTS["sensitivity"],
    }

    raw_score = sum(components.values())           # 0–1, health direction
    score_100 = round(max(min(raw_score * 100.0, 100.0), 0.0), 1)

    band: RiskBand = _assign_band(score_100)

    return HealthScore(
        asset_id=metrics.asset_id,
        composite_score=score_100,
        risk_band=band,
        faa_contribution=components["faa"] * 100,
        hotspot_contribution=components["hotspot"] * 100,
        overload_contribution=components["overload"] * 100,
        tap_contribution=components["tap"] * 100,
        winding_contribution=components["winding"] * 100,
        sensitivity_contribution=components["sensitivity"] * 100,
    )


def _assign_band(score: float) -> RiskBand:
    """Classify into GREEN / AMBER / RED based on thresholds."""
    if score >= BAND_THRESHOLDS["GREEN"]:
        return "GREEN"
    if score >= BAND_THRESHOLDS["AMBER"]:
        return "AMBER"
    return "RED"


# ── Batch helpers ─────────────────────────────────────────────────────────────

def score_all(metrics_list: list[MetricResult]) -> list[HealthScore]:
    """Score an entire fleet. Results are sorted worst-first."""
    scores = [composite_health_score(m) for m in metrics_list]
    return sorted(scores, key=lambda s: s.composite_score)


def band_summary(scores: list[HealthScore]) -> dict[str, int]:
    """Count assets per band — used by GET /api/fleet."""
    counts: dict[str, int] = {"GREEN": 0, "AMBER": 0, "RED": 0}
    for s in scores:
        counts[s.risk_band] += 1
    return counts


if __name__ == "__main__":
    # Smoke test with TXF-001 metrics
    from health_metrics import calculate_metrics_for_asset

    m = calculate_metrics_for_asset(
        asset_id="TXF-001",
        load_mva=111.6,
        rated_mva=90.0,
        ambient_temp_c=18.2,
        top_oil_rise_c=55.0,
        tap_ops=42.0,
        winding_resistance_delta_pct=4.8,
    )
    score = composite_health_score(m)
    print(f"Asset:      {score.asset_id}")
    print(f"Score:      {score.composite_score}")
    print(f"Band:       {score.risk_band}")
    print(f"  FAA:      {score.faa_contribution:.1f}/30")
    print(f"  Hotspot:  {score.hotspot_contribution:.1f}/25")
    print(f"  Overload: {score.overload_contribution:.1f}/20")
    print(f"  Winding:  {score.winding_contribution:.1f}/10")
    print(f"  Tap:      {score.tap_contribution:.1f}/10")
    print(f"  Sensitivity: {score.sensitivity_contribution:.1f}/5")
