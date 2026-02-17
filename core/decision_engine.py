# core/decision_engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# -----------------------------
# Helpers
# -----------------------------
def _to_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, str) and x.strip() == "":
            return None
        return float(x)
    except Exception:
        return None


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _z(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    mu = s.mean(skipna=True)
    sd = s.std(skipna=True)
    if sd is None or np.isnan(sd) or sd == 0:
        return pd.Series([0.0] * len(series), index=series.index)
    return (s - mu) / sd


def _soft_tradeoff_line(delta_carry: Optional[float]) -> Optional[str]:
    """
    Soft phrasing everywhere (your choice #2).
    Shows if abs(delta) >= 2.0 yards, rounded to nearest 0.5.
    """
    if delta_carry is None:
        return None
    if abs(delta_carry) < 2.0:
        return None
    # round to nearest 0.5
    rounded = round(delta_carry * 2.0) / 2.0
    if rounded < 0:
        return f"Tradeoff: may cost ~{abs(rounded):.1f} yards of carry."
    return f"Bonus: may add ~{abs(rounded):.1f} yards of carry."


def _safe_col(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    """
    Returns first matching column in df among candidates.
    """
    for c in candidates:
        if c in df.columns:
            return c
    return None


# -----------------------------
# Config
# -----------------------------
@dataclass(frozen=True)
class DecisionConfig:
    # If top-2 overall scores are within this band => "too close to call"
    TOO_CLOSE_BAND: float = 2.0

    # For "Trying to beat my gamer": require at least one meaningful edge
    BEAT_GAMER_MIN_OVERALL: float = 2.0  # overall score points (0-100 scale)
    BEAT_GAMER_MIN_DISP_IMPROVE_PCT: float = 10.0  # % improvement (lower is better)
    BEAT_GAMER_MIN_HOLD_POINTS: float = 2.0  # hold index points (0-100 scale)

    # Hold Greens composition weights by environment
    HOLD_INDOOR_W_LAND: float = 0.65
    HOLD_INDOOR_W_SPIN: float = 0.20
    HOLD_INDOOR_W_HEIGHT: float = 0.15

    HOLD_OUTDOOR_W_LAND: float = 0.50
    HOLD_OUTDOOR_W_SPIN: float = 0.35
    HOLD_OUTDOOR_W_HEIGHT: float = 0.15


# -----------------------------
# Core scoring
# -----------------------------
def compute_hold_index(
    table_df: pd.DataFrame,
    *,
    environment: str,
) -> pd.Series:
    """
    Uses per-shaft values already present in lab_df-derived table inputs OR upstream lab_df.

    We expect the calling code to merge required raw metrics into the comparison table or
    pass a table_df that already contains:
      - Spin Rate (or Spin)
      - Carry Flat - Land. Angle (or Landing Angle)
      - Max Height - Height (or Peak Height)
    If missing, it will degrade gracefully (index becomes 0).
    """
    env = (environment or "").strip().lower()
    indoor = env == "indoor"

    # Find likely columns
    col_land = _safe_col(table_df, "Carry Flat - Land. Angle", "Landing Angle", "Land. Angle")
    col_spin = _safe_col(table_df, "Spin Rate", "Spin")
    col_h = _safe_col(table_df, "Max Height - Height", "Peak Height", "Max Height")

    if col_land is None and col_spin is None and col_h is None:
        return pd.Series([0.0] * len(table_df), index=table_df.index)

    z_land = _z(table_df[col_land]) if col_land else pd.Series([0.0] * len(table_df), index=table_df.index)
    z_spin = _z(table_df[col_spin]) if col_spin else pd.Series([0.0] * len(table_df), index=table_df.index)
    z_h = _z(table_df[col_h]) if col_h else pd.Series([0.0] * len(table_df), index=table_df.index)

    if indoor:
        w_land, w_spin, w_h = 0.65, 0.20, 0.15
    else:
        w_land, w_spin, w_h = 0.50, 0.35, 0.15

    idx = (w_land * z_land) + (w_spin * z_spin) + (w_h * z_h)

    # normalize to 0–100 (relative)
    # shift + scale by percentile to keep stable UX
    p = idx.rank(pct=True).fillna(0.5)
    return (p * 100.0).round(1)


def compute_dispersion_blend(
    table_df: pd.DataFrame,
) -> pd.Series:
    """
    Blend dispersion stability using what you already compute:
      - Face To Path SD (lower better)
      - Carry SD (lower better)
    You also expose a 'Dispersion' display value, but we want the components.
    Returns 0–100 where higher is better.
    """
    ftp_sd = pd.to_numeric(table_df.get("Face To Path SD"), errors="coerce")
    carry_sd = pd.to_numeric(table_df.get("Carry SD"), errors="coerce")

    # If components aren't present in the table, degrade gracefully
    if ftp_sd is None or ftp_sd.isna().all():
        ftp_sd = pd.Series([np.nan] * len(table_df), index=table_df.index)
    if carry_sd is None or carry_sd.isna().all():
        carry_sd = pd.Series([np.nan] * len(table_df), index=table_df.index)

    # Lower SD => better. Use z-score inverted.
    z_ftp = _z(ftp_sd)
    z_car = _z(carry_sd)

    # If one is missing, weights still work (z will be 0)
    raw = (-0.60 * z_ftp) + (-0.40 * z_car)
    p = raw.rank(pct=True).fillna(0.5)
    return (p * 100.0).round(1)


def _goal_weights(goal: str) -> Dict[str, float]:
    """
    Returns weights for:
      overall = w_eff*Efficiency + w_disp*Disp + w_dist*Distance + w_hold*Hold + w_flight*Flight + w_feel*Feel
    Keep these simple and transparent; tune later.
    """
    g = (goal or "").strip().lower()

    # Defaults (A Bit of Everything)
    w = dict(eff=0.30, disp=0.25, dist=0.20, hold=0.20, flight=0.03, feel=0.02)

    if g == "more distance":
        w = dict(eff=0.25, disp=0.15, dist=0.45, hold=0.10, flight=0.03, feel=0.02)
    elif g == "straighter":
        w = dict(eff=0.20, disp=0.50, dist=0.10, hold=0.15, flight=0.03, feel=0.02)
    elif g == "hold greens better":
        w = dict(eff=0.20, disp=0.15, dist=0.10, hold=0.52, flight=0.01, feel=0.02)
    elif g == "flight window":
        w = dict(eff=0.25, disp=0.20, dist=0.10, hold=0.20, flight=0.23, feel=0.02)
    elif g == "trying to beat my gamer":
        w = dict(eff=0.30, disp=0.25, dist=0.20, hold=0.22, flight=0.01, feel=0.02)

    # normalize
    s = sum(w.values())
    return {k: v / s for k, v in w.items()}


def compute_flight_window_score(
    table_df: pd.DataFrame,
    *,
    answers: Dict[str, Any],
) -> pd.Series:
    """
    Uses interview:
      - Q16_1 happy with flight? (Yes/No/Unsure)
      - Q16_2 Higher/Lower/Not sure (only if No/Unsure)
    If user wants higher: reward higher Launch Angle / Height / LandAngle.
    If lower: reward lower Launch/Height (but still keep it relative).
    Returns 0–100.
    """
    want = (answers.get("Q16_2") or "").strip().lower()
    happy = (answers.get("Q16_1") or "").strip().lower()

    # If happy/yes or not specified => neutral
    if happy == "yes" or want in {"", "not sure", "unsure"}:
        return pd.Series([50.0] * len(table_df), index=table_df.index)

    col_launch = _safe_col(table_df, "Launch Angle", "Launch")
    col_h = _safe_col(table_df, "Max Height - Height", "Peak Height", "Max Height")
    col_land = _safe_col(table_df, "Carry Flat - Land. Angle", "Landing Angle", "Land. Angle")

    z_launch = _z(table_df[col_launch]) if col_launch else pd.Series([0.0] * len(table_df), index=table_df.index)
    z_h = _z(table_df[col_h]) if col_h else pd.Series([0.0] * len(table_df), index=table_df.index)
    z_land = _z(table_df[col_land]) if col_land else pd.Series([0.0] * len(table_df), index=table_df.index)

    if want == "higher":
        raw = (0.45 * z_launch) + (0.35 * z_h) + (0.20 * z_land)
    elif want == "lower":
        raw = (-0.55 * z_launch) + (-0.35 * z_h) + (-0.10 * z_land)
    else:
        raw = pd.Series([0.0] * len(table_df), index=table_df.index)

    p = raw.rank(pct=True).fillna(0.5)
    return (p * 100.0).round(1)


def compute_feel_score(
    table_df: pd.DataFrame,
    *,
    answers: Dict[str, Any],
    shaft_meta: Optional[pd.DataFrame] = None,
) -> pd.Series:
    """
    Minimal v1:
    If user is happy with feel => neutral 50.
    If not happy: we try to reward shafts tagged/typed as closer to desired feel.
    This needs shaft metadata (e.g., profile/feel descriptors). If not present, stay neutral.
    """
    happy = (answers.get("Q19_1") or "").strip().lower()
    target = (answers.get("Q19_2") or "").strip().lower()

    if happy == "yes" or target in {"", "not sure", "unsure"}:
        return pd.Series([50.0] * len(table_df), index=table_df.index)

    # If we don't have metadata to drive feel, keep neutral
    if shaft_meta is None or shaft_meta.empty:
        return pd.Series([50.0] * len(table_df), index=table_df.index)

    # Try common fields if you have them (safe, optional)
    # You can map these later to your Descriptions sheet / shafts sheet fields.
    col_id = _safe_col(shaft_meta, "Shaft ID", "ID")
    col_feel = _safe_col(shaft_meta, "Feel", "Feel Tag", "Profile", "Notes")
    if col_id is None or col_feel is None:
        return pd.Series([50.0] * len(table_df), index=table_df.index)

    meta = shaft_meta.copy()
    meta[col_id] = meta[col_id].astype(str)

    # crude text match
    def score_for_id(sid: str) -> float:
        row = meta.loc[meta[col_id] == str(sid)]
        if row.empty:
            return 50.0
        txt = str(row.iloc[0].get(col_feel, "")).lower()
        if not txt:
            return 50.0
        # very simple mapping – refine later
        if "smooth" in target and ("smooth" in txt or "butter" in txt):
            return 85.0
        if "stable" in target and ("stable" in txt or "tight" in txt):
            return 85.0
        if "lively" in target and ("lively" in txt or "kick" in txt):
            return 85.0
        return 55.0

    out = []
    for _, r in table_df.iterrows():
        sid = str(r.get("Shaft ID", ""))
        out.append(score_for_id(sid))
    return pd.Series(out, index=table_df.index).round(1)


# -----------------------------
# Decision Engine
# -----------------------------
def build_tour_proven_matrix(
    comparison_table: pd.DataFrame,
    *,
    baseline_shaft_id: Optional[str],
    answers: Dict[str, Any],
    environment: str,
    cfg: Optional[DecisionConfig] = None,
    shaft_meta: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    comparison_table: output from build_comparison_table(...) with extra raw cols if available.
      REQUIRED cols:
        - Shaft, Shaft ID, Carry Δ, Launch Δ, Spin Δ, Efficiency, Confidence
      RECOMMENDED (to improve buckets):
        - Carry (absolute), Spin Rate, Launch Angle, Face To Path SD, Carry SD,
          Carry Flat - Land. Angle, Max Height - Height

    Returns dict with:
      - matrix: list of bucket dicts
      - highlighted: bucket dict
      - too_close: bool
      - too_close_reason: str|None
    """
    cfg = cfg or DecisionConfig()

    if comparison_table is None or comparison_table.empty:
        return {"matrix": [], "highlighted": None, "too_close": False, "too_close_reason": None}

    df = comparison_table.copy()

    # Ensure types
    df["Shaft ID"] = df["Shaft ID"].astype(str)
    base_id = str(baseline_shaft_id) if baseline_shaft_id is not None else None

    # Build component scores (0–100)
    # Efficiency already 0–100 in your table.
    eff = pd.to_numeric(df.get("Efficiency"), errors="coerce").fillna(0.0)

    # Distance score: use Carry Δ if available, else use Carry absolute if present
    carry_delta = pd.to_numeric(df.get("Carry Δ"), errors="coerce")
    if carry_delta.isna().all():
        carry_abs = pd.to_numeric(df.get("Carry"), errors="coerce")
        raw_dist = _z(carry_abs) if carry_abs is not None else pd.Series([0.0]*len(df), index=df.index)
    else:
        raw_dist = _z(carry_delta)
    dist = (raw_dist.rank(pct=True).fillna(0.5) * 100.0).round(1)

    # Dispersion blend: if SD components not present, fall back to neutral
    if ("Face To Path SD" in df.columns) or ("Carry SD" in df.columns):
        disp = compute_dispersion_blend(df)
    else:
        disp = pd.Series([50.0]*len(df), index=df.index)

    # Hold Greens index (landing angle + spin + height), env-aware
    hold = compute_hold_index(df, environment=environment)

    # Flight window score from answers
    flight = compute_flight_window_score(df, answers=answers)

    # Feel score (v1 may be neutral unless metadata is provided)
    feel = compute_feel_score(df, answers=answers, shaft_meta=shaft_meta)

    # Overall score: goal weighted blend
    goal = (answers.get("Q23") or "").strip()
    w = _goal_weights(goal)

    overall = (
        w["eff"] * eff
        + w["disp"] * disp
        + w["dist"] * dist
        + w["hold"] * hold
        + w["flight"] * flight
        + w["feel"] * feel
    ).round(2)

    df["_score_overall"] = overall
    df["_score_distance"] = dist
    df["_score_dispersion"] = disp
    df["_score_hold"] = hold
    df["_score_flight"] = flight
    df["_score_feel"] = feel

    # Sorting utility
    def pick_best(score_col: str) -> pd.Series:
        tmp = df.sort_values([score_col, "Confidence"], ascending=[False, False])
        return tmp.iloc[0]

    def make_bucket(name: str, row: pd.Series, reason_lines: List[str]) -> Dict[str, Any]:
        trade = _soft_tradeoff_line(_to_float(row.get("Carry Δ")))
        return {
            "bucket": name,
            "shaft": row.get("Shaft"),
            "shaft_id": row.get("Shaft ID"),
            "score": float(_to_float(row.get("_score_" + name.lower().replace(" ", "_"))) or 0.0) if name != "Overall" else float(_to_float(row.get("_score_overall")) or 0.0),
            "efficiency": _to_float(row.get("Efficiency")),
            "confidence": _to_float(row.get("Confidence")),
            "carry_delta": _to_float(row.get("Carry Δ")),
            "launch_delta": _to_float(row.get("Launch Δ")),
            "spin_delta": _to_float(row.get("Spin Δ")),
            "tradeoff_line": trade,
            "reasons": reason_lines,
        }

    # Winners for each bucket
    overall_w = pick_best("_score_overall")
    dist_w = pick_best("_score_distance")
    disp_w = pick_best("_score_dispersion")
    hold_w = pick_best("_score_hold")
    flight_w = pick_best("_score_flight")
    feel_w = pick_best("_score_feel")

    # Too close to call (overall top2)
    tmp_overall = df.sort_values(["_score_overall", "Confidence"], ascending=[False, False]).reset_index(drop=True)
    too_close = False
    too_close_reason = None
    if len(tmp_overall) >= 2:
        top = float(tmp_overall.loc[0, "_score_overall"])
        second = float(tmp_overall.loc[1, "_score_overall"])
        if abs(top - second) <= cfg.TOO_CLOSE_BAND:
            too_close = True
            # build a short explain
            c1 = tmp_overall.loc[0, "Carry Δ"]
            c2 = tmp_overall.loc[1, "Carry Δ"]
            d1 = tmp_overall.loc[0, "_score_dispersion"]
            d2 = tmp_overall.loc[1, "_score_dispersion"]
            too_close_reason = (
                "Too close to call — overall scores overlap. "
                f"Carry deltas are similar ({c1:+.1f} vs {c2:+.1f}) and stability is comparable "
                f"({d1:.0f} vs {d2:.0f}). Consider deciding by feel/flight preference."
            )

    # Highlighted pick: comes from overall, but NEVER baseline/gamer
    highlighted = overall_w
    if base_id is not None and str(overall_w.get("Shaft ID")) == base_id:
        # choose best alternative
        alt = df[df["Shaft ID"] != base_id].sort_values(["_score_overall", "Confidence"], ascending=[False, False])
        if not alt.empty:
            highlighted = alt.iloc[0]

    # Special gate for "Trying to beat my gamer"
    if (goal or "").strip().lower() == "trying to beat my gamer" and base_id is not None:
        # Find baseline row in df (if present)
        base_rows = df[df["Shaft ID"] == base_id]
        if not base_rows.empty:
            base = base_rows.iloc[0]
            best_alt = df[df["Shaft ID"] != base_id].sort_values(["_score_overall", "Confidence"], ascending=[False, False]).iloc[0]

            base_overall = float(base.get("_score_overall", 0.0))
            alt_overall = float(best_alt.get("_score_overall", 0.0))

            # Dispersion improvement %: (base - alt)/base * 100 if base>0
            base_disp = float(base.get("_score_dispersion", 50.0))
            alt_disp = float(best_alt.get("_score_dispersion", 50.0))
            disp_improve_pct = 0.0
            if base_disp > 0:
                disp_improve_pct = ((alt_disp - base_disp) / base_disp) * 100.0  # higher score = better

            base_hold = float(base.get("_score_hold", 50.0))
            alt_hold = float(best_alt.get("_score_hold", 50.0))

            beats = (
                (alt_overall - base_overall) >= cfg.BEAT_GAMER_MIN_OVERALL
                or disp_improve_pct >= cfg.BEAT_GAMER_MIN_DISP_IMPROVE_PCT
                or (alt_hold - base_hold) >= cfg.BEAT_GAMER_MIN_HOLD_POINTS
            )

            if beats:
                highlighted = best_alt
            else:
                # No clear upgrade
                highlighted = best_alt  # still show best alternative, but we will message "no clear upgrade"
                # Attach a message in output
                # (UI can show this as a banner)
                no_upgrade_msg = (
                    "No clear upgrade over your gamer today — alternatives are close, but not meaningfully better. "
                    "Use the matrix + feel/flight preference to choose if you still want to change."
                )
        else:
            no_upgrade_msg = None
    else:
        no_upgrade_msg = None

    # Build bucket objects (with simple reasons)
    env_note = "Indoor" if (environment or "").strip().lower() == "indoor" else "Outdoor"

    matrix = [
        make_bucket(
            "Overall",
            overall_w,
            [
                f"Goal-weighted score (Environment: {env_note})",
                f"Efficiency {float(overall_w.get('Efficiency', 0.0)):.1f} / Confidence {float(overall_w.get('Confidence', 0.0)):.1f}",
            ],
        ),
        make_bucket(
            "Distance",
            dist_w,
            [
                "Maximizes distance relative to baseline",
                f"Carry Δ {float(_to_float(dist_w.get('Carry Δ')) or 0.0):+.1f} yards",
            ],
        ),
        make_bucket(
            "Dispersion",
            disp_w,
            [
                "Best stability blend (Face-to-Path SD + Carry SD)",
                f"Confidence {float(disp_w.get('Confidence', 0.0)):.1f}",
            ],
        ),
        make_bucket(
            "Hold Greens",
            hold_w,
            [
                "Best descent window (Landing Angle + Spin + Height)",
                "Spin values may read lower indoors; weighting adjusts automatically.",
            ],
        ),
        make_bucket(
            "Flight Window",
            flight_w,
            [
                "Best matches requested flight change",
                f"Launch Δ {float(_to_float(flight_w.get('Launch Δ')) or 0.0):+.1f}°",
            ],
        ),
        make_bucket(
            "Feel",
            feel_w,
            [
                "Best matches requested feel (v1: may be neutral without shaft feel metadata)",
            ],
        ),
    ]

    highlighted_bucket = {
        "bucket": "Highlighted",
        "shaft": highlighted.get("Shaft"),
        "shaft_id": highlighted.get("Shaft ID"),
        "overall_score": float(_to_float(highlighted.get("_score_overall")) or 0.0),
        "efficiency": _to_float(highlighted.get("Efficiency")),
        "confidence": _to_float(highlighted.get("Confidence")),
        "tradeoff_line": _soft_tradeoff_line(_to_float(highlighted.get("Carry Δ"))),
        "note_if_baseline_best": (
            "Your gamer tested best overall today; highlighting the best alternative recommendation."
            if base_id is not None and str(overall_w.get("Shaft ID")) == base_id
            else None
        ),
        "no_upgrade_msg",
    }

    return {
        "matrix": matrix,
        "highlighted": highlighted_bucket,
        "too_close": too_close,
        "too_close_reason": too_close_reason,
        "goal": goal,
        "environment": environment,
    }

