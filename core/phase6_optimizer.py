# core/phase6_optimizer.py
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd


def _get(row: pd.Series, key: str) -> Optional[float]:
    v = row.get(key, None)
    try:
        return float(v)
    except Exception:
        return None


def phase6_recommendations(
    winner_row: pd.Series,
    baseline_row: Optional[pd.Series] = None,
    *,
    club: str = "6i",
) -> List[Dict[str, str]]:
    """
    Returns a list of recommendations:
      [{"type": "Ball", "severity": "info|warn", "text": "..."}]
    Uses baseline deltas if provided.
    """
    recs: List[Dict[str, str]] = []

    # --- Pull metrics ---
    spin = _get(winner_row, "Spin Rate")
    land = _get(winner_row, "Landing Angle")
    dyn_lie = _get(winner_row, "Dynamic Lie")
    ftp = _get(winner_row, "Face To Path")
    impact_off = _get(winner_row, "Impact Offset")

    # Baseline deltas (if available)
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

    # --- Ball / Head (spin + landing angle) ---
    # For a 6i most players want roughly ~5200–6500 rpm (varies), and landing angle often ~45–50+ for hold.
    if spin is not None:
        if spin < 5200:
            recs.append({
                "type": "Ball/Head",
                "severity": "warn",
                "text": f"Low spin detected ({spin:.0f} rpm). Consider a higher-spin ball and/or adding loft (or a higher-spin head) to improve hold."
            })
        elif spin > 6500:
            recs.append({
                "type": "Ball/Head",
                "severity": "warn",
                "text": f"High spin detected ({spin:.0f} rpm). Consider a lower-spin ball and/or reducing loft (or a lower-spin head) to tighten flight."
            })
        else:
            recs.append({
                "type": "Ball/Head",
                "severity": "info",
                "text": f"Spin is in a workable window ({spin:.0f} rpm)."
            })

    if land is not None:
        if land < 45:
            recs.append({
                "type": "Hold Power",
                "severity": "warn",
                "text": f"Landing angle is shallow ({land:.1f}°). Consider adding loft, a higher-spin ball, or a higher-launch/higher-spin head to increase stopping power."
            })

    # If deltas exist, give “what changed vs baseline”
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

    # --- Lie angle recommendation ---
    if dyn_lie is not None:
        if dyn_lie > 1.5:
            recs.append({
                "type": "Lie",
                "severity": "warn",
                "text": f"Dynamic lie is upright ({dyn_lie:+.1f}°). Consider flattening 1° (then re-test strike & start line)."
            })
        elif dyn_lie < -1.5:
            recs.append({
                "type": "Lie",
                "severity": "warn",
                "text": f"Dynamic lie is flat ({dyn_lie:+.1f}°). Consider going 1° upright (then re-test strike & start line)."
            })
        else:
            recs.append({
                "type": "Lie",
                "severity": "info",
                "text": f"Dynamic lie looks neutral ({dyn_lie:+.1f}°)."
            })

    # --- Grip size cue (closure rate proxy via face-to-path) ---
    # Convention: negative FTP often indicates face more closed relative to path; positive more open.
    if ftp is not None:
        if ftp < -3:
            recs.append({
                "type": "Grip",
                "severity": "warn",
                "text": f"Face-to-path is closed ({ftp:+.1f}°). Consider slightly larger grip (+1–2 wraps) to slow closure."
            })
        elif ftp > 3:
            recs.append({
                "type": "Grip",
                "severity": "warn",
                "text": f"Face-to-path is open ({ftp:+.1f}°). Consider slightly smaller grip (or fewer wraps) to help closure."
            })

    if d_ftp is not None:
        recs.append({
            "type": "Delta vs Baseline",
            "severity": "info",
            "text": f"Face-to-path change vs baseline: {d_ftp:+.1f}°."
        })

    # --- Strike location cue (impact offset, if your unit is mm) ---
    if impact_off is not None:
        # This threshold is a starting point; you can tighten later.
        if impact_off > 5:
            recs.append({
                "type": "Strike",
                "severity": "info",
                "text": f"Impact offset suggests toe-side strike ({impact_off:+.0f} mm). Consider lie/length check or head/shaft combo that centers contact."
            })
        elif impact_off < -5:
            recs.append({
                "type": "Strike",
                "severity": "info",
                "text": f"Impact offset suggests heel-side strike ({impact_off:+.0f} mm). Consider lie/length check or head/shaft combo that centers contact."
            })

    return recs
