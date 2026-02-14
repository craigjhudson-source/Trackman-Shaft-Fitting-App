# core/phase6_optimizer.py
from __future__ import annotations

from typing import Dict, List, Optional
import pandas as pd


def _get(row: pd.Series, key: str) -> Optional[float]:
    try:
        return float(row.get(key, None))
    except Exception:
        return None


def phase6_recommendations(
    winner_row: pd.Series,
    baseline_row: Optional[pd.Series] = None,
    *,
    club: str = "6i",
    environment: str = "Indoor (mat)",   # NEW
) -> List[Dict[str, str]]:

    recs: List[Dict[str, str]] = []

    spin = _get(winner_row, "Spin Rate")
    land = _get(winner_row, "Landing Angle")
    dyn_lie = _get(winner_row, "Dynamic Lie")
    ftp = _get(winner_row, "Face To Path")
    impact_off = _get(winner_row, "Impact Offset")

    d_spin = d_land = d_dyn = d_ftp = None
    if baseline_row is not None:
        b_spin = _get(baseline_row, "Spin Rate")
        b_land = _get(baseline_row, "Landing Angle")
        b_dyn = _get(baseline_row, "Dynamic Lie")
        b_ftp = _get(baseline_row, "Face To Path")

        if spin is not None and b_spin is not None:
            d_spin = spin - b_spin
        if land is not None and b_land is not None:
            d_land = land - b_land
        if dyn_lie is not None and b_dyn is not None:
            d_dyn = dyn_lie - b_dyn
        if ftp is not None and b_ftp is not None:
            d_ftp = ftp - b_ftp

    # ---------- Environment Adjustments ----------
    # Indoor mat typically reads slightly lower spin & steeper AoA
    if environment == "Indoor (mat)":
        spin_low = 5000
        spin_high = 6500
        landing_threshold = 44
    else:  # Outdoor turf
        spin_low = 5200
        spin_high = 6500
        landing_threshold = 45

    # ---------- Spin Window ----------
    if spin is not None:
        if spin < spin_low:
            recs.append({
                "type": "Ball/Head",
                "severity": "warn",
                "text": f"Low spin ({spin:.0f} rpm). Consider higher-spin ball or adding loft to improve hold."
            })
        elif spin > spin_high:
            recs.append({
                "type": "Ball/Head",
                "severity": "warn",
                "text": f"High spin ({spin:.0f} rpm). Consider lower-spin ball or reducing loft to tighten flight."
            })
        else:
            recs.append({
                "type": "Ball/Head",
                "severity": "info",
                "text": f"Spin looks workable ({spin:.0f} rpm)."
            })

    # ---------- Landing Angle ----------
    if land is not None and land < landing_threshold:
        recs.append({
            "type": "Hold Power",
            "severity": "warn",
            "text": f"Landing angle is shallow ({land:.1f}°). Consider higher-launch shaft/head or higher-spin ball."
        })

    # ---------- Baseline deltas ----------
    if d_spin is not None:
        recs.append({
            "type": "Delta vs Baseline",
            "severity": "info",
            "text": f"Spin change vs baseline: {d_spin:+.0f} rpm."
        })

    if d_land is not None:
        recs.append({
            "type": "Delta vs Baseline",
            "severity": "info",
            "text": f"Landing angle change vs baseline: {d_land:+.1f}°."
        })

    # ---------- Lie ----------
    if dyn_lie is not None:
        if dyn_lie > 1.5:
            recs.append({
                "type": "Lie",
                "severity": "warn",
                "text": f"Dynamic lie upright ({dyn_lie:+.1f}°). Consider flattening 1°."
            })
        elif dyn_lie < -1.5:
            recs.append({
                "type": "Lie",
                "severity": "warn",
                "text": f"Dynamic lie flat ({dyn_lie:+.1f}°). Consider 1° upright."
            })
        else:
            recs.append({
                "type": "Lie",
                "severity": "info",
                "text": f"Dynamic lie looks neutral ({dyn_lie:+.1f}°)."
            })

    # ---------- Grip ----------
    if ftp is not None:
        if ftp < -3:
            recs.append({
                "type": "Grip",
                "severity": "warn",
                "text": f"Face-to-path closed ({ftp:+.1f}°). Consider slightly larger grip."
            })
        elif ftp > 3:
            recs.append({
                "type": "Grip",
                "severity": "warn",
                "text": f"Face-to-path open ({ftp:+.1f}°). Consider slightly smaller grip."
            })

    if d_ftp is not None:
        recs.append({
            "type": "Delta vs Baseline",
            "severity": "info",
            "text": f"Face-to-path change vs baseline: {d_ftp:+.1f}°."
        })

    # ---------- Strike ----------
    if impact_off is not None:
        if impact_off > 5:
            recs.append({
                "type": "Strike",
                "severity": "info",
                "text": f"Toe-side strike tendency ({impact_off:+.0f} mm). Verify lie/length."
            })
        elif impact_off < -5:
            recs.append({
                "type": "Strike",
                "severity": "info",
                "text": f"Heel-side strike tendency ({impact_off:+.0f} mm). Verify lie/length."
            })

    return recs
