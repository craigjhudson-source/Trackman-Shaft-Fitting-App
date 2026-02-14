# core/head_optimizer.py
from __future__ import annotations

from typing import Dict, List, Optional
import pandas as pd


def _f(row: pd.Series, key: str) -> Optional[float]:
    try:
        v = row.get(key, None)
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def _delta(w: Optional[float], b: Optional[float]) -> Optional[float]:
    if w is None or b is None:
        return None
    return w - b


def head_recommendations(
    winner_row: pd.Series,
    baseline_row: Optional[pd.Series] = None,
    *,
    club: str = "6i",
    player_pref: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    """
    Returns a list of dicts like:
      {"type": "Head", "severity": "warn|info", "text": "..."}
    Designed to be appended into your Phase 6 recs and fed into PDF.

    Notes:
      - This is a conservative ruleset. Tune thresholds as your dataset grows.
      - club is currently unused beyond text context, but kept for future expansion.
    """
    recs: List[Dict[str, str]] = []

    # Primary metrics
    spin = _f(winner_row, "Spin Rate")
    land = _f(winner_row, "Landing Angle")
    launch = _f(winner_row, "Launch Angle")
    carry = _f(winner_row, "Carry")
    ball_speed = _f(winner_row, "Ball Speed")

    # Baseline metrics (if present)
    b_spin = _f(baseline_row, "Spin Rate") if baseline_row is not None else None
    b_land = _f(baseline_row, "Landing Angle") if baseline_row is not None else None
    b_launch = _f(baseline_row, "Launch Angle") if baseline_row is not None else None

    d_spin = _delta(spin, b_spin)
    d_land = _delta(land, b_land)
    d_launch = _delta(launch, b_launch)

    # ---- Target windows (starter) ----
    # You can tune these per club later (6i vs 7i etc.)
    SPIN_LOW = 5200
    SPIN_HIGH = 6500
    LAND_MIN = 45.0

    # Helper labels (fitter language)
    def add(severity: str, text: str):
        recs.append({"type": "Head", "severity": severity, "text": text})

    # --- Hold-power assessment (the main driver for head choice) ---
    if spin is not None and land is not None:
        if spin < SPIN_LOW or land < LAND_MIN:
            add(
                "warn",
                f"Hold power risk ({spin:.0f} rpm, {land:.1f}°). "
                "Consider adding loft (+1°) OR moving to a higher-launch / higher-spin head profile."
            )
        elif spin > SPIN_HIGH:
            add(
                "warn",
                f"Spin is elevated ({spin:.0f} rpm). Consider a lower-spin head profile (stronger loft / lower-spin CG) "
                "before changing shafts."
            )
        else:
            add("info", f"Head/loft window looks workable ({spin:.0f} rpm, {land:.1f}°).")

    # --- Loft suggestion (simple, safe) ---
    # If either spin or landing is low -> add loft. If spin very high -> reduce.
    if spin is not None and land is not None:
        if spin < SPIN_LOW and land < LAND_MIN:
            add("warn", "Suggested test: **+1° loft** (or weaker loft head) to improve spin + landing angle.")
        elif spin < SPIN_LOW and land >= LAND_MIN:
            add("info", "Suggested test: **+1° loft** if you want a touch more stopping power.")
        elif spin > SPIN_HIGH + 400:
            add("warn", "Suggested test: **-1° loft** (or stronger loft head) to reduce spin if flight balloons.")

    # --- Head category suggestion (Players vs PD vs GI) ---
    # We infer based on needing help with height/spin vs needing spin reduction.
    # These are guidance buckets, not brand-specific.
    if spin is not None and land is not None:
        if spin < SPIN_LOW or land < LAND_MIN:
            add(
                "warn",
                "Head category direction: consider **Players Distance (PD)** or a **higher-launch Players head** "
                "(more help with launch/spin) rather than a low-spin Players head."
            )
        elif spin > SPIN_HIGH:
            add(
                "warn",
                "Head category direction: consider a **Players head / lower-spin profile** (lower spin CG) "
                "or slightly stronger loft to control spin."
            )
        else:
            add("info", "Head category direction: current window supports a **Players** style head if feel/control is priority.")

    # --- Baseline deltas (useful when you’re deciding head changes) ---
    if d_spin is not None:
        recs.append({"type": "Head Delta vs Baseline", "severity": "info", "text": f"Spin change vs baseline: {d_spin:+.0f} rpm."})
    if d_land is not None:
        recs.append({"type": "Head Delta vs Baseline", "severity": "info", "text": f"Landing angle change vs baseline: {d_land:+.1f}°."})
    if d_launch is not None:
        recs.append({"type": "Head Delta vs Baseline", "severity": "info", "text": f"Launch change vs baseline: {d_launch:+.1f}°."})

    # --- Optional: player preference shaping (future hook) ---
    # player_pref might include: {"feel": "soft|firm", "forgiveness": "high|mid|low"}
    if player_pref:
        feel = (player_pref.get("feel") or "").lower()
        forg = (player_pref.get("forgiveness") or "").lower()
        if feel in ("soft", "buttery") and forg in ("low", "mid"):
            recs.append({"type": "Preference", "severity": "info", "text": "Preference noted: softer feel / workable. Lean Players head if hold window allows."})
        elif forg in ("high",):
            recs.append({"type": "Preference", "severity": "info", "text": "Preference noted: forgiveness priority. Lean PD/GI head if hold window is borderline."})

    # --- Small extra context if we have speed/carry ---
    if ball_speed is not None and carry is not None:
        recs.append({"type": "Context", "severity": "info", "text": f"Context: Ball Speed {ball_speed:.1f}, Carry {carry:.1f} (used for future club-by-club windows)."})
    elif carry is not None:
        recs.append({"type": "Context", "severity": "info", "text": f"Context: Carry {carry:.1f} (used for future club-by-club windows)."})

    return recs
