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


def _z(x: Any) -> pd.Series:
    """
    Robust z-score helper.

    Accepts:
      - pandas Series (preferred)
      - list/tuple/numpy array
      - scalar numbers (float/int)
      - None

    Returns:
      - pandas Series
        * If input was a Series, output preserves its index/length.
        * If input was scalar, output is length-1 Series.
        * If input is array-like, output matches that length.
    """
    # Preserve index when possible
    if isinstance(x, pd.Series):
        s = pd.to_numeric(x, errors="coerce")
        idx = x.index
    else:
        # Scalar / None / array-like -> normalize to Series
        if x is None:
            s = pd.Series([np.nan])
        elif isinstance(x, (int, float, np.number)):
            s = pd.Series([float(x)])
        else:
            try:
                s = pd.Series(list(x))
            except Exception:
                s = pd.Series([np.nan])
        s = pd.to_numeric(s, errors="coerce")
        idx = s.index

    # Handle empty / all-NaN
    if len(s) == 0:
        return pd.Series([], dtype="float64", index=idx)

    if s.isna().all():
        return pd.Series([0.0] * len(s), index=idx)

    mu = s.mean(skipna=True)
    sd = s.std(skipna=True)

    # Guard against sd = 0 / NaN
    if sd is None or (isinstance(sd, float) and np.isnan(sd)) or float(sd) == 0.0:
        return pd.Series([0.0] * len(s), index=idx)

    return (s - mu) / sd


def _soft_tradeoff_line(delta_carry: Optional[float]) -> Optional[str]:
    """
    Soft phrasing everywhere.
    Shows if abs(delta) >= 2.0 yards, rounded to nearest 0.5.
    """
    if delta_carry is None or np.isnan(delta_carry):
        return None
    if abs(delta_carry) < 2.0:
        return None
    rounded = round(delta_carry * 2.0) / 2.0
    if rounded < 0:
        return f"Tradeoff: may cost ~{abs(rounded):.1f} yards of carry."
    return f"Bonus: may add ~{abs(rounded):.1f} yards of carry."


def _safe_col(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


# -----------------------------
# Config
# -----------------------------
@dataclass(frozen=True)
class DecisionConfig:
    TOO_CLOSE_BAND: float = 2.0

    BEAT_GAMER_MIN_OVERALL: float = 2.0
    BEAT_GAMER_MIN_DISP_IMPROVE_PCT: float = 10.0
    BEAT_GAMER_MIN_HOLD_POINTS: float = 2.0

    HOLD_INDOOR_W_LAND: float = 0.65
    HOLD_INDOOR_W_SPIN: float = 0.20
    HOLD_INDOOR_W_HEIGHT: float = 0.15

    HOLD_OUTDOOR_W_LAND: float = 0.50
    HOLD_OUTDOOR_W_SPIN: float = 0.35
    HOLD_OUTDOOR_W_HEIGHT: float = 0.15


# -----------------------------
# Component scoring
# -----------------------------
def compute_hold_index(table_df: pd.DataFrame, *, environment: str, cfg: DecisionConfig) -> pd.Series:
    """
    0–100 relative hold index using Landing Angle + Spin + Height (env-aware).
    Works even if some metrics are missing.
    """
    env = (environment or "").strip().lower()
    indoor = env.startswith("indoor") or env.startswith("indoors")

    col_land = _safe_col(table_df, "Carry Flat - Land. Angle", "Landing Angle", "Land. Angle")
    col_spin = _safe_col(table_df, "Spin Rate", "Spin")
    col_h = _safe_col(table_df, "Max Height - Height", "Peak Height", "Max Height")

    if col_land is None and col_spin is None and col_h is None:
        return pd.Series([50.0] * len(table_df), index=table_df.index)

    z_land = _z(table_df[col_land]) if col_land else pd.Series([0.0] * len(table_df), index=table_df.index)
    z_spin = _z(table_df[col_spin]) if col_spin else pd.Series([0.0] * len(table_df), index=table_df.index)
    z_h = _z(table_df[col_h]) if col_h else pd.Series([0.0] * len(table_df), index=table_df.index)

    if indoor:
        w_land, w_spin, w_h = cfg.HOLD_INDOOR_W_LAND, cfg.HOLD_INDOOR_W_SPIN, cfg.HOLD_INDOOR_W_HEIGHT
    else:
        w_land, w_spin, w_h = cfg.HOLD_OUTDOOR_W_LAND, cfg.HOLD_OUTDOOR_W_SPIN, cfg.HOLD_OUTDOOR_W_HEIGHT

    raw = (w_land * z_land) + (w_spin * z_spin) + (w_h * z_h)
    p = raw.rank(pct=True).fillna(0.5)
    return (p * 100.0).round(1)


def compute_dispersion_blend(table_df: pd.DataFrame) -> pd.Series:
    """
    0–100 where higher is better stability, using:
      - Face To Path SD (lower better)
      - Carry SD (lower better)
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
    g = (goal or "").strip().lower()
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
    table_df: pd.DataFrame, *, answers: Dict[str, Any], shaft_meta: Optional[pd.DataFrame] = None
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

    if comparison_table is None or comparison_table.empty:
        return {"matrix": [], "highlighted": None, "too_close": False, "too_close_reason": None}

    df = comparison_table.copy()
    df["Shaft ID"] = df["Shaft ID"].astype(str)
    base_id = str(baseline_shaft_id) if baseline_shaft_id is not None else None

    eff = pd.to_numeric(df.get("Efficiency"), errors="coerce").fillna(0.0)

    carry_delta = pd.to_numeric(df.get("Carry Δ"), errors="coerce")
    if carry_delta.isna().all():
        carry_abs = pd.to_numeric(df.get("Carry"), errors="coerce")
        raw_dist = _z(carry_abs) if carry_abs is not None else pd.Series([0.0] * len(df), index=df.index)
    else:
        raw_dist = _z(carry_delta)
    dist = (raw_dist.rank(pct=True).fillna(0.5) * 100.0).round(1)

    disp = (
        compute_dispersion_blend(df)
        if (("Face To Path SD" in df.columns) or ("Carry SD" in df.columns))
        else pd.Series([50.0] * len(df), index=df.index)
    )
    hold = compute_hold_index(df, environment=environment, cfg=cfg)
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

    overall_w = pick_best("_score_overall")
    dist_w = pick_best("_score_distance")
    disp_w = pick_best("_score_dispersion")
    hold_w = pick_best("_score_hold")
    flight_w = pick_best("_score_flight")
    feel_w = pick_best("_score_feel")

    # too close
    tmp_overall = df.sort_values(["_score_overall", "Confidence"], ascending=[False, False]).reset_index(drop=True)
    too_close = False
    too_close_reason = None
    if len(tmp_overall) >= 2:
        top = float(tmp_overall.loc[0, "_score_overall"])
        second = float(tmp_overall.loc[1, "_score_overall"])
        if abs(top - second) <= cfg.TOO_CLOSE_BAND:
            too_close = True
            c1 = float(pd.to_numeric(tmp_overall.loc[0, "Carry Δ"], errors="coerce") or 0.0)
            c2 = float(pd.to_numeric(tmp_overall.loc[1, "Carry Δ"], errors="coerce") or 0.0)
            d1 = float(tmp_overall.loc[0, "_score_dispersion"])
            d2 = float(tmp_overall.loc[1, "_score_dispersion"])
            too_close_reason = (
                "Too close to call — overall scores overlap. "
                f"Carry deltas are similar ({c1:+.1f} vs {c2:+.1f}) and stability is comparable "
                f"({d1:.0f} vs {d2:.0f}). Consider deciding by feel/flight preference."
            )

    # highlighted pick (never baseline)
    highlighted = overall_w
    if base_id is not None and str(overall_w.get("Shaft ID")) == base_id:
        alt = df[df["Shaft ID"] != base_id].sort_values(["_score_overall", "Confidence"], ascending=[False, False])
        if not alt.empty:
            highlighted = alt.iloc[0]

    # beat gamer gate + messaging
    no_upgrade_msg: Optional[str] = None
    if (goal or "").strip().lower() == "trying to beat my gamer" and base_id is not None:
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
                disp_improve_pct = ((alt_disp - base_disp) / base_disp) * 100.0 if base_disp > 0 else 0.0

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
                        "Use the matrix + feel/flight preference to decide if you still want to change."
                    )

    env_note = "Indoor" if (environment or "").strip().lower().startswith(("indoor", "indoors")) else "Outdoor"

    def make_bucket(label: str, row: pd.Series, reasons: List[str], score_col: str) -> Dict[str, Any]:
        trade = _soft_tradeoff_line(_to_float(row.get("Carry Δ")))
        return {
            "bucket": label,
            "shaft": row.get("Shaft"),
            "shaft_id": row.get("Shaft ID"),
            "score": float(_to_float(row.get(score_col)) or 0.0),
            "efficiency": _to_float(row.get("Efficiency")),
            "confidence": _to_float(row.get("Confidence")),
            "carry_delta": _to_float(row.get("Carry Δ")),
            "launch_delta": _to_float(row.get("Launch Δ")),
            "spin_delta": _to_float(row.get("Spin Δ")),
            "tradeoff_line": trade,
            "reasons": reasons,
        }

    matrix = [
        make_bucket(
            "Overall",
            overall_w,
            [
                f"Goal-weighted score (Environment: {env_note})",
                f"Efficiency {float(_to_float(overall_w.get('Efficiency')) or 0.0):.1f} / Confidence {float(_to_float(overall_w.get('Confidence')) or 0.0):.1f}",
            ],
            "_score_overall",
        ),
        make_bucket(
            "Distance",
            dist_w,
            [
                "Maximizes distance relative to baseline",
                f"Carry Δ {float(_to_float(dist_w.get('Carry Δ')) or 0.0):+.1f} yards",
            ],
            "_score_distance",
        ),
        make_bucket(
            "Dispersion",
            disp_w,
            [
                "Best stability blend (Face-to-Path SD + Carry SD)",
                f"Confidence {float(_to_float(disp_w.get('Confidence')) or 0.0):.1f}",
            ],
            "_score_dispersion",
        ),
        make_bucket(
            "Hold Greens",
            hold_w,
            [
                "Best descent window (Landing Angle + Spin + Height)",
                "Spin values may read lower indoors; weighting adjusts automatically.",
            ],
            "_score_hold",
        ),
        make_bucket(
            "Flight Window",
            flight_w,
            [
                "Best matches requested flight change",
                f"Launch Δ {float(_to_float(flight_w.get('Launch Δ')) or 0.0):+.1f}°",
            ],
            "_score_flight",
        ),
        make_bucket(
            "Feel",
            feel_w,
            [
                "Best matches requested feel (v1: may be neutral without shaft feel metadata)",
            ],
            "_score_feel",
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
