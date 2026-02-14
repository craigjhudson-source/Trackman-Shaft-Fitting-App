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

    # Spin windows (starter rules — tune later)
    if spin is not None:
        if spin < 5200:
            recs.append({"type": "Ball/Head", "severity": "warn",
                         "text": f"Low spin ({spin:.0f} rpm). Consider higher-spin ball and/or adding loft / higher-spin head to improve hold."})
        elif spin > 6500:
            recs.append({"type": "Ball/Head", "severity": "warn",
                         "text": f"High spin ({spin:.0f} rpm). Consider lower-spin ball and/or reducing loft / lower-spin head to tighten flight."})
        else:
            recs.append({"type": "Ball/Head", "severity": "info",
                         "text": f"Spin looks workable ({spin:.0f} rpm)."})

    if land is not None and land < 45:
        recs.append({"type": "Hold Power", "severity": "warn",
                     "text": f"Landing angle is shallow ({land:.1f}°). Consider adding loft, higher-spin ball, or higher-launch/head to increase stopping power."})

    if d_spin is not None:
        recs.append({"type": "Delta vs Baseline", "severity": "info",
                     "text": f"Spin change vs baseline: {d_spin:+.0f} rpm."})
    if d_land is not None:
        recs.append({"type": "Delta vs Baseline", "severity": "info",
                     "text": f"Landing angle change vs baseline: {d_land:+.1f}°."})

    # Lie
    if dyn_lie is not None:
        if dyn_lie > 1.5:
            recs.append({"type": "Lie", "severity": "warn",
                         "text": f"Dynamic lie is upright ({dyn_lie:+.1f}°). Consider flattening 1° then re-test."})
        elif dyn_lie < -1.5:
            recs.append({"type": "Lie", "severity": "warn",
                         "text": f"Dynamic lie is flat ({dyn_lie:+.1f}°). Consider 1° upright then re-test."})
        else:
            recs.append({"type": "Lie", "severity": "info",
                         "text": f"Dynamic lie looks neutral ({dyn_lie:+.1f}°)."})

    # Grip cue via face-to-path
    if ftp is not None:
        if ftp < -3:
            recs.append({"type": "Grip", "severity": "warn",
                         "text": f"Face-to-path is closed ({ftp:+.1f}°). Consider larger grip (+1–2 wraps) to slow closure."})
        elif ftp > 3:
            recs.append({"type": "Grip", "severity": "warn",
                         "text": f"Face-to-path is open ({ftp:+.1f}°). Consider smaller grip (or fewer wraps) to help closure."})

    if d_ftp is not None:
        recs.append({"type": "Delta vs Baseline", "severity": "info",
                     "text": f"Face-to-path change vs baseline: {d_ftp:+.1f}°."})

    # Strike cue (if impact offset exists)
    if impact_off is not None:
        if impact_off > 5:
            recs.append({"type": "Strike", "severity": "info",
                         "text": f"Toe-side strike tendency ({impact_off:+.0f} mm). Consider lie/length verification or combo that centers contact."})
        elif impact_off < -5:
            recs.append({"type": "Strike", "severity": "info",
                         "text": f"Heel-side strike tendency ({impact_off:+.0f} mm). Consider lie/length verification or combo that centers contact."})

    return recs
