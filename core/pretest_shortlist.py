from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import numpy as np
import pandas as pd


# -----------------------------
# Config + helpers
# -----------------------------
@dataclass(frozen=True)
class PretestConfig:
    # How many non-gamer shafts to suggest
    N: int = 3

    # Weighting
    W_FLEX: float = 140.0
    W_WEIGHT: float = 6.0

    # Goal weights (applied as score bonuses/penalties; lower score is better)
    W_STABILITY: float = 120.0
    W_LAUNCH_FOR_DISTANCE: float = 80.0
    W_LAUNCH_FOR_HOLD: float = 45.0

    # Flight constraint penalty (very strong so we don't contradict the user)
    FLIGHT_CONSTRAINT_PENALTY: float = 10000.0

    # Optional: if IDs are missing or blank, we drop those rows
    REQUIRE_ID: bool = True


def _safe_str(x: Any) -> str:
    try:
        return str(x).strip()
    except Exception:
        return ""


def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, str) and x.strip() == "":
            return None
        return float(x)
    except Exception:
        return None


def _norm_goal(goal: str) -> str:
    g = _safe_str(goal).lower()

    # normalize to exactly the choices you listed
    if "more distance" in g:
        return "more distance"
    if "straighter" in g:
        return "straighter"
    if "hold" in g:
        return "hold greens better"
    if "flight" in g:
        return "flight window"
    if "bit" in g or "everything" in g or "balanced" in g:
        return "a bit of everything"
    if "beat" in g and "gamer" in g:
        return "trying to beat my gamer"

    # if sheet stores the exact label already, this still handles it
    return g


def _norm_yesno(x: str) -> str:
    s = _safe_str(x).lower()
    # your Q16_2 is "Are you happy?" => yes/no
    if s in {"yes", "y", "true"}:
        return "yes"
    if s in {"no", "n", "false"}:
        return "no"
    return s


def _norm_hilo(x: str) -> str:
    s = _safe_str(x).lower()
    if "high" in s or "higher" in s:
        return "higher"
    if "low" in s or "lower" in s:
        return "lower"
    return s


def _targets_from_carry(carry_6i: float) -> Tuple[float, float]:
    """
    Return (target_flexscore, target_weight)
    """
    c = float(carry_6i)
    if c >= 195:
        return 8.5, 130.0
    if c >= 180:
        return 7.0, 125.0
    if c >= 165:
        return 6.0, 110.0
    return 5.0, 95.0


def _coerce_numeric_cols(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for col in ["FlexScore", "Weight (g)", "LaunchScore", "StabilityIndex"]:
        if col not in d.columns:
            d[col] = np.nan
        d[col] = pd.to_numeric(d[col], errors="coerce")
    return d


def _extract_flight_intent(answers: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Uses:
      Q16_2 = happy? (yes/no)
      Q16_3 = higher/lower if not happy

    Returns:
      (apply_constraint, direction) where direction in {"higher","lower"} or None
    """
    happy = _norm_yesno(answers.get("Q16_2", ""))
    if happy != "no":
        return False, None

    dir_ = _norm_hilo(answers.get("Q16_3", ""))
    if dir_ in {"higher", "lower"}:
        return True, dir_
    return False, None


def _flight_constraint_penalty(row_launch: Optional[float], *, direction: str, cfg: PretestConfig) -> float:
    """
    We don't know your LaunchScore scale, so we use relative ranking logic:
    - If user wants LOWER: heavily penalize shafts in top half of LaunchScore
    - If user wants HIGHER: heavily penalize shafts in bottom half
    This is done later after ranking, but this helper exists for clarity.
    """
    # This function is kept for future hard thresholds; currently we do percentile gating.
    return 0.0


def _build_shortlist_scored(
    shafts_df: pd.DataFrame,
    answers: Dict[str, Any],
    cfg: PretestConfig,
) -> pd.DataFrame:
    """
    Returns shafts with a computed _score (lower is better), filtered + sorted.
    """
    d = _coerce_numeric_cols(shafts_df)

    # Require ID to be present + stable
    if "ID" not in d.columns:
        # Without an ID column, the whole app can't be trusted.
        return pd.DataFrame()

    d["ID"] = d["ID"].astype(str).str.strip()
    d["ID"] = d["ID"].replace({"nan": "", "None": "", "NaN": ""})

    if cfg.REQUIRE_ID:
        d = d[d["ID"] != ""].copy()
        if d.empty:
            return pd.DataFrame()

    carry = _to_float(answers.get("Q15", 150)) or 150.0
    target_flex, target_w = _targets_from_carry(carry)

    goal = _norm_goal(answers.get("Q23", ""))

    # Base score = fit to carry (flex+weight)
    flex = d["FlexScore"].fillna(target_flex)
    wt = d["Weight (g)"].fillna(target_w)

    d["_score"] = (abs(flex - target_flex) * cfg.W_FLEX) + (abs(wt - target_w) * cfg.W_WEIGHT)

    # Prefer closer to "typical" requirements: if carry is big, avoid too soft
    if carry >= 180:
        d.loc[d["FlexScore"].fillna(0) < 6.5, "_score"] += 4000.0

    # Goal weighting
    stab = d["StabilityIndex"].fillna(0.0)
    launch = d["LaunchScore"].fillna(0.0)

    if goal == "more distance":
        # distance: allow a little more launch, but still keep carry-fit
        d["_score"] -= (launch * cfg.W_LAUNCH_FOR_DISTANCE)

    elif goal == "straighter":
        # straighter: hammer stability; don't “buy” distance with offline dispersion
        d["_score"] -= (stab * cfg.W_STABILITY)

    elif goal == "hold greens better":
        # hold: blend of launch and stability
        d["_score"] -= (launch * cfg.W_LAUNCH_FOR_HOLD)
        d["_score"] -= (stab * (cfg.W_STABILITY * 0.45))

    elif goal == "flight window":
        # flight is driven mostly by Q16; here we keep neutral and let constraints do the work
        d["_score"] -= (stab * (cfg.W_STABILITY * 0.20))

    elif goal == "trying to beat my gamer":
        # beat gamer: stability + some launch (but not contradicting flight constraint)
        d["_score"] -= (stab * (cfg.W_STABILITY * 0.55))
        d["_score"] -= (launch * (cfg.W_LAUNCH_FOR_HOLD * 0.35))

    else:
        # a bit of everything (balanced)
        d["_score"] -= (stab * (cfg.W_STABILITY * 0.35))
        d["_score"] -= (launch * (cfg.W_LAUNCH_FOR_HOLD * 0.25))

    # Flight constraints (Q16): prevent contradictory recommendations
    apply_constraint, direction = _extract_flight_intent(answers)

    if apply_constraint and "LaunchScore" in d.columns:
        # Use percentile gate so we don't rely on unknown LaunchScore scale
        # Higher LaunchScore => higher launching
        launch_rank = d["LaunchScore"].rank(pct=True, na_option="keep")

        if direction == "lower":
            # penalize shafts that are in the top half (higher launching)
            d.loc[launch_rank >= 0.50, "_score"] += cfg.FLIGHT_CONSTRAINT_PENALTY
        elif direction == "higher":
            # penalize shafts that are in the bottom half (lower launching)
            d.loc[launch_rank <= 0.50, "_score"] += cfg.FLIGHT_CONSTRAINT_PENALTY

    # Output with stable columns
    for c in ["Brand", "Model", "Flex", "Weight (g)"]:
        if c not in d.columns:
            d[c] = ""

    out = d.sort_values("_score", ascending=True).reset_index(drop=True)
    return out


def build_pretest_shortlist(
    shafts_df: pd.DataFrame,
    answers: Dict[str, Any],
    *,
    n: int = 3,
) -> pd.DataFrame:
    """
    Returns 2–3 shafts (NOT including gamer) with stable IDs coming from Shafts!ID.
    """
    cfg = PretestConfig(N=int(n))
    scored = _build_shortlist_scored(shafts_df, answers, cfg)

    if scored is None or scored.empty:
        return pd.DataFrame(columns=["ID", "Brand", "Model", "Flex", "Weight (g)"])

    cols = ["ID", "Brand", "Model", "Flex", "Weight (g)"]
    keep = scored.head(cfg.N)[cols].copy().reset_index(drop=True)

    # Clean
    for c in cols:
        if c in keep.columns:
            keep[c] = keep[c].astype(str).str.strip().replace({"nan": "", "None": "", "NaN": ""})

    return keep
