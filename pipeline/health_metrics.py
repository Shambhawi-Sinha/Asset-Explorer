"""
health_metrics.py — Per-asset health metric calculations
=========================================================
Implements the five sub-metrics used in the composite health score:

  1. FAA Thermal Aging Acceleration Factor  (IEC 60076-7)
  2. Hotspot Temperature                    (IEEE C57.91)
  3. Overload Severity Ratio
  4. Tap Changer Stress (TPOSC daily ops)
  5. Load–Temperature Sensitivity (Pearson r)

These run as a batch pipeline (typically nightly via Azure DevOps scheduled
pipeline or as an on-demand re-score). Results are written back to Oracle ADB
via the SUBSTATION_HEALTH_VW backing table.
"""

import math
import pandas as pd
import numpy as np
from typing import Optional
from dataclasses import dataclass


# ── Constants ────────────────────────────────────────────────────────────────

# IEC 60076-7: Reference winding hotspot temperature at rated conditions
THETA_H_REF = 98.0          # °C  (reference hotspot; 98°C per IEC 60076-7 §7.2)
THETA_A_REF = 20.0          # °C  (reference ambient)

# IEEE C57.91 hotspot model constants
DELTA_THETA_TO_R = 55.0     # °C  (rated top-oil rise)
DELTA_THETA_H_R  = 30.0     # °C  (rated hotspot rise over top oil)
N_EXPONENT       = 0.9      # IEC loading guide exponent (0.8–1.0)
M_EXPONENT       = 0.8      # IEC hotspot exponent (0.8)

# FAA numerator constant  (activation energy / Boltzmann constant, normalised)
# from IEC 60076-7 equation (3):  FAA = exp[15000/383 − 15000/(273+θ_H)]
FAA_NUMERATOR = 15000.0
THETA_REF_KELVIN = 383.0    # = 110°C + 273

# Operational thresholds
TPOSC_WARNING  = 20         # ops/day — elevated wear
TPOSC_CRITICAL = 30         # ops/day — high wear
SENSITIVITY_WARNING  = 0.7  # Pearson r — warning
SENSITIVITY_CRITICAL = 0.85 # Pearson r — critical


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class MetricResult:
    """Normalised metric value (0–1 where 1 = worst)."""
    asset_id: str
    faa_factor: float            # Raw FAA value (>1 = aging faster than reference)
    faa_normalised: float        # 0–1 score component
    hotspot_temp: float          # °C
    hotspot_normalised: float    # 0–1
    overload_ratio: float        # MVA_actual / MVA_rated
    overload_normalised: float   # 0–1
    tap_ops_daily: float         # TPOSC operations per day
    tap_normalised: float        # 0–1
    winding_resistance_delta: float   # % deviation from factory test
    winding_normalised: float    # 0–1
    load_temp_sensitivity: float # Pearson r
    sensitivity_normalised: float    # 0–1


# ── Metric 1: FAA Thermal Aging ───────────────────────────────────────────────

def faa_factor(hotspot_temp_c: float) -> float:
    """
    IEC 60076-7 Ageing Acceleration Factor.

    FAA = exp(15000/383 − 15000/(273+θ_H))

    FAA=1 at reference hotspot 110°C (383K); >1 means faster ageing.
    At 120°C ≈ 3.6×; at 130°C ≈ 12.5× reference ageing rate.

    Args:
        hotspot_temp_c: Current winding hotspot temperature in °C.

    Returns:
        FAA value (float ≥ 0).
    """
    theta_h_k = 273.0 + hotspot_temp_c
    return math.exp(FAA_NUMERATOR / THETA_REF_KELVIN - FAA_NUMERATOR / theta_h_k)


def normalise_faa(faa: float, max_faa: float = 20.0) -> float:
    """Clip and normalise FAA to [0, 1]. FAA=1 → 0.05; FAA=20 → 1.0."""
    return min(max(faa / max_faa, 0.0), 1.0)


# ── Metric 2: Hotspot Temperature ────────────────────────────────────────────

def hotspot_temperature(
    ambient_temp_c: float,
    top_oil_rise_c: float,
    load_ratio: float,
) -> float:
    """
    IEEE C57.91 hotspot temperature model.

    θ_H = θ_A  +  Δθ_TO_R × K^(2N)  +  Δθ_H_R × K^(2M)

    Where:
        K = load ratio (per-unit; K=1 at rated load)
        N = thermal exponent for top-oil rise (0.9 for ONAN)
        M = thermal exponent for hotspot rise over top oil (0.8)

    Args:
        ambient_temp_c:   Measured ambient temperature (°C).
        top_oil_rise_c:   Rated top-oil temperature rise over ambient (°C).
        load_ratio:       Per-unit load (MVA_actual / MVA_rated).

    Returns:
        Winding hotspot temperature estimate (°C).
    """
    k = max(load_ratio, 0.01)   # Avoid 0^0
    delta_to = top_oil_rise_c * (k ** (2 * N_EXPONENT))
    delta_h  = DELTA_THETA_H_R * (k ** (2 * M_EXPONENT))
    return ambient_temp_c + delta_to + delta_h


def normalise_hotspot(temp_c: float, critical_c: float = 120.0) -> float:
    """Normalise hotspot temp. ≤80°C → 0; ≥120°C → 1."""
    return min(max((temp_c - 80.0) / (critical_c - 80.0), 0.0), 1.0)


# ── Metric 3: Overload Severity ───────────────────────────────────────────────

def overload_ratio(load_mva: float, rated_mva: float) -> float:
    """
    Per-unit loading ratio (K = load_mva / rated_mva).
    K > 1.0 = overloaded; K > 1.2 = severe overload.
    """
    if rated_mva <= 0:
        return 0.0
    return load_mva / rated_mva


def normalise_overload(ratio: float, critical: float = 1.2) -> float:
    """0.8 → 0; 1.2 → 1."""
    return min(max((ratio - 0.8) / (critical - 0.8), 0.0), 1.0)


# ── Metric 4: Tap Changer Stress ──────────────────────────────────────────────

def tap_ops_per_day(operations: pd.Series, timestamps: pd.Series) -> float:
    """
    Compute daily average OLTC operations from a timestamped event series.
    Each row in `operations` is a tap-change event.

    Args:
        operations:  Series of tap position values (NaN = unchanged).
        timestamps:  Corresponding UTC timestamps.

    Returns:
        Average tap-change operations per day.
    """
    df = pd.DataFrame({'ts': pd.to_datetime(timestamps), 'pos': operations})
    df = df.dropna(subset=['pos'])
    df['changed'] = df['pos'].diff().abs() > 0
    df_changes = df[df['changed']]

    if df_changes.empty:
        return 0.0

    # Days spanned by the data
    duration_days = max(
        (df['ts'].max() - df['ts'].min()).total_seconds() / 86400,
        1.0
    )
    return len(df_changes) / duration_days


def normalise_tap(ops_day: float, critical: float = float(TPOSC_CRITICAL)) -> float:
    """0–20 ops → 0; ≥30 ops → 1."""
    return min(max((ops_day - TPOSC_WARNING) / (critical - TPOSC_WARNING), 0.0), 1.0)


# ── Metric 5: Load–Temperature Sensitivity ───────────────────────────────────

def load_temp_sensitivity(
    load_series: pd.Series,
    temp_series: pd.Series,
    window_days: int = 30,
) -> float:
    """
    Rolling Pearson correlation between load (MVA) and winding temperature (°C).

    A high correlation (r → 1) is expected for healthy transformers.
    *Diminishing* correlation can indicate sensor drift, cooling failure, or
    abnormal internal heating sources — hence it is included as a stress metric
    when r > sensitivity threshold (suggesting excessive thermal coupling
    beyond normal load-driven rise).

    Args:
        load_series:  Per-unit load time series.
        temp_series:  Winding temperature time series (same index).
        window_days:  Rolling window size in data-point equivalents.

    Returns:
        Pearson r (absolute value, most-recent window), 0–1.
    """
    if len(load_series) < 10 or len(temp_series) < 10:
        return 0.0

    series = pd.DataFrame({'load': load_series, 'temp': temp_series}).dropna()
    if len(series) < 10:
        return 0.0

    # Rolling correlation over the last window_days samples
    rolling_r = series['load'].rolling(window=min(window_days * 24, len(series))).corr(
        series['temp']
    )
    latest_r = rolling_r.dropna().iloc[-1] if not rolling_r.dropna().empty else 0.0
    return float(abs(latest_r))


def normalise_sensitivity(r: float) -> float:
    """Below 0.7 → 0 (normal); above 0.85 → 1 (concerning)."""
    return min(max((r - SENSITIVITY_WARNING) / (SENSITIVITY_CRITICAL - SENSITIVITY_WARNING), 0.0), 1.0)


# ── Batch calculation ─────────────────────────────────────────────────────────

def calculate_metrics_for_asset(
    asset_id: str,
    load_mva: float,
    rated_mva: float,
    ambient_temp_c: float,
    top_oil_rise_c: float,
    tap_ops: float,
    winding_resistance_delta_pct: float,
    load_series: Optional[pd.Series] = None,
    temp_series: Optional[pd.Series] = None,
) -> MetricResult:
    """
    Calculate all five health sub-metrics for a single transformer.

    This is the main entry point called by the batch pipeline for each asset.
    """
    ratio     = overload_ratio(load_mva, rated_mva)
    hs_temp   = hotspot_temperature(ambient_temp_c, top_oil_rise_c, ratio)
    faa       = faa_factor(hs_temp)
    sensitivity = (
        load_temp_sensitivity(load_series, temp_series)
        if load_series is not None and temp_series is not None
        else 0.0
    )

    # Winding resistance: % delta from factory, normalised (>5% = critical)
    winding_norm = min(max(winding_resistance_delta_pct / 5.0, 0.0), 1.0)

    return MetricResult(
        asset_id=asset_id,
        faa_factor=faa,
        faa_normalised=normalise_faa(faa),
        hotspot_temp=hs_temp,
        hotspot_normalised=normalise_hotspot(hs_temp),
        overload_ratio=ratio,
        overload_normalised=normalise_overload(ratio),
        tap_ops_daily=tap_ops,
        tap_normalised=normalise_tap(tap_ops),
        winding_resistance_delta=winding_resistance_delta_pct,
        winding_normalised=winding_norm,
        load_temp_sensitivity=sensitivity,
        sensitivity_normalised=normalise_sensitivity(sensitivity),
    )


if __name__ == "__main__":
    # Quick smoke test
    result = calculate_metrics_for_asset(
        asset_id="TXF-001",
        load_mva=111.6,
        rated_mva=90.0,
        ambient_temp_c=18.2,
        top_oil_rise_c=55.0,
        tap_ops=42.0,
        winding_resistance_delta_pct=4.8,
    )
    print(f"Asset:          {result.asset_id}")
    print(f"Hotspot:        {result.hotspot_temp:.1f}°C  (normalised: {result.hotspot_normalised:.3f})")
    print(f"FAA:            {result.faa_factor:.2f}×   (normalised: {result.faa_normalised:.3f})")
    print(f"Overload ratio: {result.overload_ratio:.2f}    (normalised: {result.overload_normalised:.3f})")
    print(f"Tap ops/day:    {result.tap_ops_daily:.0f}     (normalised: {result.tap_normalised:.3f})")
    print(f"Winding delta:  {result.winding_resistance_delta:.1f}%  (normalised: {result.winding_normalised:.3f})")
