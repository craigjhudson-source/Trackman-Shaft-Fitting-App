# core/decision_engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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

    rounded = round(delta_carry * 2.0) / 2.0
    if rounded < 0:
        return f"Tradeoff: may cost ~{abs(rounded):.1f} yards of carry."
    return f"Bonus: may add ~{abs(rounded):.1f} yards of carry."


def _safe_col(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    """Returns first matching column in df among candidates."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _is_indoor(environment: str) -> bool:
    env = (environment or "").strip().lower()
    # Handles: "Indoor", "Indoors (Mat)", "indoor mat", etc.
    return "indoor" in env


# -----------------------------
# Config
# -----------------------------
@dataclass(frozen=True)
class DecisionConfig:
    # If top-2 overall scores are within this band => "too close to call"
    TOO_CLOSE_BAND: float = 2.0

    # For "Trying to beat my gamer": require at least one meaningful edge
    BEAT_GAMER_MIN_OVERALL: float = 2.0  # overall score points (0-100 scale)
    BEAT_GAMER_MIN_DISP_IMPROVE_PCT: float = 10.0  # % improvement
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
def compute_hold_index(table_df: pd.DataFrame, *, environment: str) -> pd.Series:
    """
    Holds greens index using:
      - Landing Angle
      - Spin Rate
      - Peak/Max Height

    Degrades gracefully if missing.
    Returns 0–100 (relative within this test set).
    """
    indoor = _is_indoor(environment)

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

    p = idx.rank(pct=True).fillna(0.5)
    return (p * 100.0).round(1)


def compute_dispersion_blend(table_df: pd.DataFrame) -> pd.Series:
    """
    Blend stability using:
      - Face To Path SD (lower better)
      - Carry SD (lower better)
    Returns 0–100 where higher is better.
    """
    ftp_sd = pd.to_numeric(table_df.get("Face To Path SD"), errors="coerce")
    carry_sd = pd.to_numeric(table_df.get("Carry SD"), errors="coerce")

    if ftp_sd is None or ftp_sd.isna().all():
        ftp_sd = pd.Series([np.nan] * len(table_df), index=table_df.index)
    if carry_sd is None or carry_sd.isna().all():
        carry_sd = pd.Series([np.nan] * len(table_df), index=table_df.index)

    z_ftp = _z(ftp_sd)
    z_car = _z(carry_sd)

    raw = (-0.60 * z_ftp) + (-0.40 * z_car)
    p = raw.rank(pct=True).fillna(0.5)
    return (p * 100.0).round(1)


def _goal_weights(goal: str) -> Dict[str, float]:
    """
    Returns weights for:
      overall = w_eff*Efficiency + w_disp*Disp + w_dist*Distance + w_hold*Hold + w_flight*Flight + w_feel*Feel
    """
    g = (goal or "").strip().lower()

    # Default: A Bit of Everything
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

    s = sum(w.values())
    return {k: v / s for k, v in w.items()}


def compute_flight_window_score(table_df: pd.DataFrame, *, answers: Dict[str, Any]) -> pd.Series:
    want = (answers.get("Q16_2") or "").strip().lower()
    happy = (answers.get("Q16_1") or "").strip().lower()

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
    happy = (answers.get("Q19_1") or "").strip().lower()
    target = (answers.get("Q19_2") or "").strip().lower()

    if happy == "yes" or target in {"", "not sure", "unsure"}:
        return pd.Series([50.0] * len(table_df), index=table_df.index)

    if shaft_meta is None or shaft_meta.empty:
        return pd.Series([50.0] * len(table_df), index=table_df.index)

    col_id = _safe_col(shaft_meta, "Shaft ID", "ID")
    col_feel = _safe_col(shaft_meta, "Feel", "Feel Tag", "Profile", "Notes")
    if col_id is None or col_feel is None:
        return pd.Series([50.0] * len(table_df), index=table_df.index)

    meta = shaft_meta.copy()
    meta[col_id] = meta[col_id].astype(str)

    def score_for_id(sid: str) -> float:
        row = meta.loc[meta[col_id] == str(sid)]
        if row.empty:
            return 50.0
        txt = str(row.iloc[0].get(col_feel, "")).lower()
        if not txt:
            return 50.0
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
    cfg = cfg or DecisionConfig()

    # IMPORTANT: initialize so we never hit UnboundLocalError
    no_upgrade_msg: Optional[str] = None

    if comparison_table is None or comparison_table.empty:
        return {"matrix": [], "highlighted": None, "too_close": False, "too_close_reason": None}

    df = comparison_table.copy()
    df["Shaft ID"] = df["Shaft ID"].astype(str)
    base_id = str(baseline_shaft_id) if baseline_shaft_id is not None else None

    # Component scores (0–100)
    eff = pd.to_numeric(df.get("Efficiency"), errors="coerce").fillna(0.0)

    carry_delta = pd.to_numeric(df.get("Carry Δ"), errors="coerce")
    if carry_delta.isna().all():
        carry_abs = pd.to_numeric(df.get("Carry"), errors="coerce")
        raw_dist = _z(carry_abs) if carry_abs is not None else pd.Series([0.0] * len(df), index=df.index)
    else:
        raw_dist = _z(carry_delta)
    dist = (raw_dist.rank(pct=True).fillna(0.5) * 100.0).round(1)

    if ("Face To Path SD" in df.columns) or ("Carry SD" in df.columns):
        disp = compute_dispersion_blend(df)
    else:
        disp = pd.Series([50.0] * len(df), index=df.index)

    hold = compute_hold_index(df, environment=environment)
    flight = compute_flight_window_score(df, answers=answers)
    feel = compute_feel_score(df, answers=answers, shaft_meta=shaft_meta)

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

    def pick_best(score_col: str) -> pd.Series:
        tmp = df.sort_values([score_col, "Confidence"], ascending=[False, False])
        return tmp.iloc[0]

    def make_bucket(name: str, row: pd.Series, reason_lines: List[str]) -> Dict[str, Any]:
        trade = _soft_tradeoff_line(_to_float(row.get("Carry Δ")))
        score_key = "_score_overall" if name == "Overall" else "_score_" + name.lower().replace(" ", "_")
        return {
            "bucket": name,
            "shaft": row.get("Shaft"),
            "shaft": row.get("Shaft"),
            "shaft_id": row.get("Shaft ID"),
            "score": float(_to_float(row.get(score_key)) or 0.0),
            "efficiency": _to_float(row.get("Efficiency")),
            "confidence": _to_float(row.get("Confidence")),
            "carry_delta": _to_float(row.get("Carry Δ")),
            "launch_delta": _to_float(row.get("Launch Δ")),
            "spin_delta": _to_float(row.get("Spin Δ")),
            "tradeoff_line": trade,
            "reasons": reason_lines,
        }

    overall_w = pick_best("_score_overall")
    dist_w = pick_best("_score_distance")
    disp_w = pick_best("_score_dispersion")
    hold_w = pick_best("_score_hold")
    flight_w = pick_best("_score_flight")
    feel_w = pick_best("_score_feel")

    # Too close to call
    tmp_overall = df.sort_values(["_score_overall", "Confidence"], ascending=[False, False]).reset_index(drop=True)
    too_close = False
    too_close_reason = None
    if len(tmp_overall) >= 2:
        top = float(tmp_overall.loc[0, "_score_overall"])
        second = float(tmp_overall.loc[1, "_score_overall"])
        if abs(top - second) <= cfg.TOO_CLOSE_BAND:
            too_close = True

            c1 = _to_float(tmp_overall.loc[0, "Carry Δ"])
            c2 = _to_float(tmp_overall.loc[1, "Carry Δ"])
            d1 = float(tmp_overall.loc[0, "_score_dispersion"])
            d2 = float(tmp_overall.loc[1, "_score_dispersion"])

            c1s = f"{c1:+.1f}" if c1 is not None else "n/a"
            c2s = f"{c2:+.1f}" if c2 is not None else "n/a"

            too_close_reason = (
                "Too close to call — overall scores overlap. "
                f"Carry deltas are similar ({c1s} vs {c2s}) and stability is comparable "
                f"({d1:.0f} vs {d2:.0f}). Consider deciding by feel/flight preference."
            )

    # Highlighted pick: comes from overall, but NEVER baseline
    highlighted = overall_w
    if base_id is not None and str(overall_w.get("Shaft ID")) == base_id:
        alt = df[df["Shaft ID"] != base_id].sort_values(["_score_overall", "Confidence"], ascending=[False, False])
        if not alt.empty:
            highlighted = alt.iloc[0]

    # Special gate for "Trying to beat my gamer"
    if goal.strip().lower() == "trying to beat my gamer" and base_id is not None:
        base_rows = df[df["Shaft ID"] == base_id]
        if not base_rows.empty:
            base = base_rows.iloc[0]
            alt_df = df[df["Shaft ID"] != base_id].sort_values(["_score_overall", "Confidence"], ascending=[False, False])
            if not alt_df.empty:
                best_alt = alt_df.iloc[0]

                base_overall = float(base.get("_score_overall", 0.0))
                alt_overall = float(best_alt.get("_score_overall", 0.0))

                base_disp = float(base.get("_score_dispersion", 50.0))
                alt_disp = float(best_alt.get("_score_dispersion", 50.0))

                disp_improve_pct = 0.0
                if base_disp > 0:
                    disp_improve_pct = ((alt_disp - base_disp) / base_disp) * 100.0

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
                    highlighted = best_alt
                    no_upgrade_msg = (
                        "No clear upgrade over your gamer today — alternatives are close, but not meaningfully better. "
                        "Use the matrix + feel/flight preference to choose if you still want to change."
                    )

    env_note = "Indoor" if _is_indoor(environment) else "Outdoor"

    matrix = [
        make_bucket(
            "Overall",
            overall_w,
            [
                f"Goal-weighted score (Environment: {env_note})",
                f"Efficiency {float(_to_float(overall_w.get('Efficiency')) or 0.0):.1f} / "
                f"Confidence {float(_to_float(overall_w.get('Confidence')) or 0.0):.1f}",
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
                f"Confidence {float(_to_float(disp_w.get('Confidence')) or 0.0):.1f}",
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
        "no_upgrade_msg": no_upgrade_msg,
    }

    return {
        "matrix": matrix,
        "highlighted": highlighted_bucket,
        "too_close": too_close,
        "too_close_reason": too_close_reason,
        "goal": goal,
        "environment": environment,
    }
