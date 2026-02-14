# core/scoring.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class ScoreConfig:
    # weights: higher = matters more
    w_smash: float = 3.0
    w_ball_speed: float = 2.0
    w_carry: float = 2.0

    # stability penalties (lower SD is better)
    w_face_to_path_sd: float = 3.0
    w_carry_side_sd: float = 2.0
    w_total_side_sd: float = 1.5

    # optional strike consistency if present
    w_impact_offset_sd: float = 1.0

    # “fit window” penalties
    w_spin_window: float = 1.0
    w_landing_angle: float = 1.0

    # default windows (starter values, tune later)
    spin_low: float = 5200
    spin_high: float = 6500
    landing_min: float = 45.0


def _to_float(s) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _z(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    mu = s.mean()
    sd = s.std(ddof=0)
    if sd == 0 or np.isnan(sd):
        return pd.Series([0.0] * len(s), index=s.index)
    return (s - mu) / sd


def _range_penalty(value: float, low: float, high: float) -> float:
    """0 inside window; grows as you move outside."""
    if value is None or np.isnan(value):
        return 0.0
    if value < low:
        return (low - value) / (high - low + 1e-9)
    if value > high:
        return (value - high) / (high - low + 1e-9)
    return 0.0


def score_shafts(
    lab_df: pd.DataFrame,
    *,
    baseline_tag: str = "Current Baseline",
    config: Optional[ScoreConfig] = None,
) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """
    Returns:
      (score_table_df, winners_dict)

    score_table_df columns include:
      Shaft ID, Score, EfficiencyScore, StabilityScore, FitPenalty, etc.
    """
    cfg = config or ScoreConfig()

    df = lab_df.copy()
    if "Shaft ID" not in df.columns:
        raise ValueError("lab_df must contain 'Shaft ID'")

    # Exclude baseline from ranking
    cand = df[df["Shaft ID"] != baseline_tag].copy()
    if len(cand) == 0:
        return pd.DataFrame(), {}

    # Ensure numeric fields exist safely
    # core positives
    cand["Smash Factor"] = _to_float(cand.get("Smash Factor"))
    cand["Ball Speed"] = _to_float(cand.get("Ball Speed"))
    cand["Carry"] = _to_float(cand.get("Carry"))

    # stability SDs (lower is better)
    cand["Face To Path SD"] = _to_float(cand.get("Face To Path SD"))
    cand["Carry Side SD"] = _to_float(cand.get("Carry Side SD"))
    cand["Total Side SD"] = _to_float(cand.get("Total Side SD"))
    cand["Impact Offset SD"] = _to_float(cand.get("Impact Offset SD"))

    # fit metrics
    cand["Spin Rate"] = _to_float(cand.get("Spin Rate"))
    cand["Landing Angle"] = _to_float(cand.get("Landing Angle"))

    # Build z-scores: positives add, SDs subtract
    z_smash = _z(cand["Smash Factor"].fillna(cand["Smash Factor"].mean()))
    z_ball = _z(cand["Ball Speed"].fillna(cand["Ball Speed"].mean()))
    z_carry = _z(cand["Carry"].fillna(cand["Carry"].mean()))

    # For SDs: smaller is better => use negative z of SD
    # fill missing SDs with mean so they don’t auto-win/lose
    def z_inv_sd(col: str) -> pd.Series:
        s = cand[col]
        if s.isna().all():
            return pd.Series([0.0] * len(cand), index=cand.index)
        s2 = s.fillna(s.mean())
        return -_z(s2)

    z_ftp_sd = z_inv_sd("Face To Path SD")
    z_carry_side_sd = z_inv_sd("Carry Side SD")
    z_total_side_sd = z_inv_sd("Total Side SD")
    z_impact_sd = z_inv_sd("Impact Offset SD")

    # Fit penalties: spin outside window + landing too shallow
    spin_pen = cand["Spin Rate"].apply(lambda v: _range_penalty(v, cfg.spin_low, cfg.spin_high))
    land_pen = cand["Landing Angle"].apply(lambda v: 0.0 if (v is None or np.isnan(v)) else max(0.0, (cfg.landing_min - v) / 5.0))

    # Weighted sum
    efficiency = (cfg.w_smash * z_smash) + (cfg.w_ball_speed * z_ball) + (cfg.w_carry * z_carry)
    stability = (cfg.w_face_to_path_sd * z_ftp_sd) + (cfg.w_carry_side_sd * z_carry_side_sd) + (cfg.w_total_side_sd * z_total_side_sd) + (cfg.w_impact_offset_sd * z_impact_sd)
    fit_penalty = (cfg.w_spin_window * spin_pen) + (cfg.w_landing_angle * land_pen)

    cand["EfficiencyScore"] = efficiency.round(3)
    cand["StabilityScore"] = stability.round(3)
    cand["FitPenalty"] = fit_penalty.round(3)

    # Final score: higher is better, penalties subtract
    cand["Score"] = (cand["EfficiencyScore"] + cand["StabilityScore"] - cand["FitPenalty"]).round(3)

    # Winners
    winners: Dict[str, str] = {}
    winners["Overall Winner"] = cand.loc[cand["Score"].astype(float).idxmax(), "Shaft ID"]
    winners["Speed King (Ball Speed)"] = cand.loc[cand["Ball Speed"].astype(float).idxmax(), "Shaft ID"] if cand["Ball Speed"].notna().any() else winners["Overall Winner"]
    winners["Efficiency King (Smash)"] = cand.loc[cand["Smash Factor"].astype(float).idxmax(), "Shaft ID"] if cand["Smash Factor"].notna().any() else winners["Overall Winner"]

    # Consistency King = min Face To Path SD if available else min Carry Side SD
    if cand["Face To Path SD"].notna().any():
        winners["Consistency King (F2P SD)"] = cand.loc[cand["Face To Path SD"].astype(float).idxmin(), "Shaft ID"]
    elif cand["Carry Side SD"].notna().any():
        winners["Consistency King (Carry Side SD)"] = cand.loc[cand["Carry Side SD"].astype(float).idxmin(), "Shaft ID"]
    else:
        winners["Consistency King"] = winners["Overall Winner"]

    # Output table (nice order)
    out_cols = [
        "Shaft ID",
        "Score",
        "EfficiencyScore",
        "StabilityScore",
        "FitPenalty",
        "Smash Factor",
        "Ball Speed",
        "Carry",
        "Spin Rate",
        "Landing Angle",
        "Face To Path SD",
        "Carry Side SD",
        "Total Side SD",
        "Impact Offset SD",
    ]
    out_cols = [c for c in out_cols if c in cand.columns]
    score_table = cand[out_cols].sort_values("Score", ascending=False).reset_index(drop=True)

    return score_table, winners
