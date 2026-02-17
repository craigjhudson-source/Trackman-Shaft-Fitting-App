# core/goal_scoring.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from core.goal_profile import GoalProfile


@dataclass(frozen=True)
class GoalScoreResult:
    shaft_id: str
    shaft_label: str
    overall_score: float
    goal_scores: Dict[str, float]
    deltas: Dict[str, float]
    reasons: List[str]


def _to_float(x: Any) -> Optional[float]:
    try:
        s = "" if x is None else str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _get_metric(row: pd.Series, key: str) -> Optional[float]:
    if key not in row.index:
        return None
    return _to_float(row.get(key))


def _delta(lab: pd.DataFrame, sid: str, baseline_sid: str, metric: str) -> Optional[float]:
    try:
        r = lab.loc[lab["Shaft ID"].astype(str) == str(sid)].iloc[0]
        b = lab.loc[lab["Shaft ID"].astype(str) == str(baseline_sid)].iloc[0]
    except Exception:
        return None
    rv = _get_metric(r, metric)
    bv = _get_metric(b, metric)
    if rv is None or bv is None:
        return None
    return rv - bv


def _sd(lab: pd.DataFrame, sid: str, metric_sd: str) -> Optional[float]:
    try:
        r = lab.loc[lab["Shaft ID"].astype(str) == str(sid)].iloc[0]
    except Exception:
        return None
    return _get_metric(r, metric_sd)


def _z(delta: Optional[float], denom: Optional[float], eps: float = 1e-6) -> float:
    if delta is None:
        return 0.0
    d = denom if denom is not None else 0.0
    if abs(d) < eps:
        d = 1.0  # avoid blowups; treat as 1 unit scale
    return float(delta) / float(d)


def _env_weights(environment: str) -> Dict[str, float]:
    env = (environment or "").lower()
    indoors = "indoor" in env or "mat" in env
    # Indoors tends to have tighter launch/spin; outdoors can have more variance.
    return {
        "launch": 1.0 if indoors else 0.9,
        "spin": 0.9 if indoors else 1.0,
        "landing": 1.0,
        "dispersion": 1.0,
        "consistency": 1.0,
        "speed": 0.8,
    }


def score_goalcard(
    lab_df: pd.DataFrame,
    baseline_shaft_id: Optional[str],
    profile: GoalProfile,
) -> Dict[str, Any]:
    """
    Returns a dict with:
      - baseline_shaft_id
      - results: List[GoalScoreResult] sorted best->worst
      - top_by_goal: dict goal->GoalScoreResult
      - goals_used: list[str]
    """
    if lab_df is None or lab_df.empty:
        return {"baseline_shaft_id": baseline_shaft_id, "results": [], "top_by_goal": {}, "goals_used": []}

    lab = lab_df.copy()
    for c in lab.columns:
        if lab[c].dtype == "object":
            lab[c] = lab[c].astype(str).str.strip()

    if "Shaft ID" not in lab.columns:
        return {"baseline_shaft_id": baseline_shaft_id, "results": [], "top_by_goal": {}, "goals_used": []}

    # Choose baseline if not provided: first row
    if not baseline_shaft_id:
        baseline_shaft_id = str(lab.iloc[0]["Shaft ID"]).strip()

    # Build goals and weights
    ew = _env_weights(profile.environment)

    goals: Dict[str, Dict[str, float]] = {}

    # Flight change (Higher/Lower): use Launch + (optional) Peak + Landing
    if profile.wants_flight_change:
        ft = (profile.flight_target or "").lower()
        if "high" in ft:
            goals["Flight Higher"] = {
                "Launch Angle": 1.0 * ew["launch"],
                "Landing Angle": 0.7 * ew["landing"],
                "Spin Rate": 0.3 * ew["spin"],
            }
        elif "low" in ft:
            goals["Flight Lower"] = {
                "Launch Angle": -1.0 * ew["launch"],
                "Landing Angle": -0.7 * ew["landing"],
                "Spin Rate": -0.2 * ew["spin"],
            }

    # Hold greens (locked): Landing primary + Spin + Peak (if available)
    if profile.wants_hold_greens:
        goals["Hold Greens"] = {
            "Landing Angle": 1.2 * ew["landing"],
            "Spin Rate": 0.8 * ew["spin"],
        }

    # Anti-left / stability: minimize left dispersion + face-to-path + SDs
    if profile.wants_anti_left:
        goals["Anti-Left / Stability"] = {
            "Total Side": -1.0 * ew["dispersion"],
            "Carry Side": -0.8 * ew["dispersion"],
            "Face To Path": -0.7 * ew["dispersion"],
            "Face To Path SD": -0.6 * ew["consistency"],
        }

    # Feel: use “consistency” proxies (lower SDs) + smash stability
    if profile.wants_feel_change:
        ft = (profile.feel_target or "").lower()
        smoother = any(x in ft for x in ["smooth", "smoother", "softer"])
        firmer = any(x in ft for x in ["firm", "stiff", "tighter"])
        # Both map to consistency, but we can bias slightly:
        if smoother or firmer:
            goals["Feel / Consistency"] = {
                "Club Speed SD": -0.7 * ew["consistency"],
                "Ball Speed SD": -0.7 * ew["consistency"],
                "Smash Factor SD": -0.8 * ew["consistency"],
                "Carry SD": -0.7 * ew["consistency"],
            }

    # Always include a “Baseline-neutral performance” safety goal (optional)
    # This prevents the system from recommending something that tanks speed.
    goals["Do No Harm"] = {
        "Carry": 0.4,
        "Ball Speed": 0.3,
        "Smash Factor": 0.3,
    }

    goals_used = list(goals.keys())

    # Precompute baseline SD denominators per metric (or fallback)
    # For SD-weighted metrics, denom uses baseline SD if present, else 1
    baseline_row = None
    try:
        baseline_row = lab.loc[lab["Shaft ID"].astype(str) == str(baseline_shaft_id)].iloc[0]
    except Exception:
        baseline_row = None

    def denom_for(metric: str) -> float:
        # If metric is an SD metric itself, denom=1
        if metric.endswith(" SD"):
            return 1.0
        # Prefer baseline SD of that metric if present (e.g., Carry SD as denom for Carry delta)
        if baseline_row is not None:
            sd_col = f"{metric} SD"
            if sd_col in lab.columns:
                bsd = _get_metric(baseline_row, sd_col)
                if bsd is not None and bsd > 0:
                    return float(bsd)
        # Fallback scale: metric-dependent
        return 1.0

    results: List[GoalScoreResult] = []

    for _, row in lab.iterrows():
        sid = str(row.get("Shaft ID", "")).strip()
        if not sid:
            continue
        label = str(row.get("Shaft Label", "")).strip() or f"ID {sid}"

        deltas: Dict[str, float] = {}
        # Build deltas for any metrics used
        for goal_name, weights in goals.items():
            for metric in weights.keys():
                if metric.endswith(" SD"):
                    # For SD metrics we want lower SD vs baseline SD
                    base_sd = _sd(lab, baseline_shaft_id, metric)
                    this_sd = _sd(lab, sid, metric)
                    if base_sd is None or this_sd is None:
                        continue
                    deltas[metric] = float(this_sd - base_sd)
                else:
                    d = _delta(lab, sid, baseline_shaft_id, metric)
                    if d is None:
                        continue
                    deltas[metric] = float(d)

        goal_scores: Dict[str, float] = {}
        reasons: List[str] = []

        overall = 0.0
        for goal_name, weights in goals.items():
            g = 0.0
            for metric, w in weights.items():
                d = deltas.get(metric, None)
                if d is None:
                    continue
                denom = 1.0 if metric.endswith(" SD") else denom_for(metric)
                g += float(w) * _z(d, denom)

            goal_scores[goal_name] = float(g)

            # Overall: sum all goals equally, with “Do No Harm” smaller
            if goal_name == "Do No Harm":
                overall += 0.4 * g
            else:
                overall += 1.0 * g

        # Simple reason bullets for the top 2 contributing metrics (non SD) + top SD improvement
        # (Keep this explainable but not overly verbose.)
        contribs: List[Tuple[float, str]] = []
        for metric, d in deltas.items():
            if metric.endswith(" SD"):
                # Lower is better if negative delta; capture improvements
                contribs.append(((-d), f"{metric} {'↓' if d < 0 else '↑'} {abs(d):.2f}"))
            else:
                contribs.append((abs(d), f"{metric} {'+' if d >= 0 else ''}{d:.2f}"))

        contribs = sorted(contribs, key=lambda x: x[0], reverse=True)[:3]
        reasons = [c[1] for c in contribs if c[0] > 0]

        results.append(
            GoalScoreResult(
                shaft_id=sid,
                shaft_label=label,
                overall_score=float(overall),
                goal_scores=goal_scores,
                deltas=deltas,
                reasons=reasons,
            )
        )

    results = sorted(results, key=lambda r: r.overall_score, reverse=True)

    top_by_goal: Dict[str, Any] = {}
    for goal in goals_used:
        # Pick top by that goal score (excluding Do No Harm as a display goal)
        if goal == "Do No Harm":
            continue
        best = max(results, key=lambda r: r.goal_scores.get(goal, -1e9), default=None)
        if best:
            top_by_goal[goal] = best

    return {
        "baseline_shaft_id": baseline_shaft_id,
        "results": results,
        "top_by_goal": top_by_goal,
        "goals_used": goals_used,
    }
