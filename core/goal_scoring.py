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


def _first_row(lab: pd.DataFrame, shaft_id: str) -> Optional[pd.Series]:
    try:
        return lab.loc[lab["Shaft ID"].astype(str) == str(shaft_id)].iloc[0]
    except Exception:
        return None


def _delta(lab: pd.DataFrame, sid: str, baseline_sid: str, metric: str) -> Optional[float]:
    r = _first_row(lab, sid)
    b = _first_row(lab, baseline_sid)
    if r is None or b is None:
        return None
    rv = _get_metric(r, metric)
    bv = _get_metric(b, metric)
    if rv is None or bv is None:
        return None
    return rv - bv


def _sd_delta(lab: pd.DataFrame, sid: str, baseline_sid: str, metric_sd: str) -> Optional[float]:
    """
    SD delta: negative is better (more consistent).
    """
    r = _first_row(lab, sid)
    b = _first_row(lab, baseline_sid)
    if r is None or b is None:
        return None
    rv = _get_metric(r, metric_sd)
    bv = _get_metric(b, metric_sd)
    if rv is None or bv is None:
        return None
    return rv - bv


def _z(delta: Optional[float], denom: float, eps: float = 1e-6) -> float:
    if delta is None:
        return 0.0
    d = float(denom)
    if abs(d) < eps:
        d = 1.0
    return float(delta) / d


def _env_scale(environment: str) -> Dict[str, float]:
    env = (environment or "").lower()
    indoors = "indoor" in env or "mat" in env
    return {
        "launch": 1.0 if indoors else 0.9,
        "spin": 0.9 if indoors else 1.0,
        "landing": 1.0,
        "disp": 1.0,
        "cons": 1.0,
        "speed": 0.8,
    }


def _primary_goal_weights(primary_key: str, env_scale: Dict[str, float]) -> Dict[str, float]:
    """
    Primary goal weights driven by Q23 (main decider).
    Positive weight => more is better vs baseline.
    Negative weight => less is better vs baseline.
    """
    e = env_scale

    if primary_key == "HOLD_GREENS":
        # Locked: landing angle primary + spin secondary
        return {
            "Landing Angle": 1.25 * e["landing"],
            "Spin Rate": 0.95 * e["spin"],
        }

    if primary_key == "STABILITY":
        # "Straighter"
        return {
            "Total Side": -1.10 * e["disp"],
            "Carry Side": -0.90 * e["disp"],
            "Face To Path": -0.70 * e["disp"],
            "Face To Path SD": -0.70 * e["cons"],
            "Carry SD": -0.55 * e["cons"],
        }

    if primary_key == "DISTANCE":
        # "More Distance"
        return {
            "Carry": 1.10,
            "Ball Speed": 0.85 * e["speed"],
            "Smash Factor": 0.65,
            # keep it playable
            "Total Side": -0.35 * e["disp"],
        }

    if primary_key == "FLIGHT_WINDOW":
        # "Flight Window" = controlled height/launch with reasonable dispersion
        return {
            "Launch Angle": 1.00 * e["launch"],
            "Landing Angle": 0.70 * e["landing"],
            "Spin Rate": 0.40 * e["spin"],
            "Total Side": -0.40 * e["disp"],
        }

    if primary_key == "BEAT_GAMER":
        # "Trying To Beat My Gamer" = balanced improvement vs baseline (slightly aggressive)
        return {
            "Carry": 0.90,
            "Ball Speed": 0.70 * e["speed"],
            "Landing Angle": 0.50 * e["landing"],
            "Total Side": -0.50 * e["disp"],
            "Carry SD": -0.35 * e["cons"],
        }

    # BALANCED default ("A Bit Of Everything")
    return {
        "Carry": 0.55,
        "Ball Speed": 0.45 * e["speed"],
        "Smash Factor": 0.35,
        "Landing Angle": 0.35 * e["landing"],
        "Total Side": -0.35 * e["disp"],
        "Carry SD": -0.25 * e["cons"],
    }


def _flight_modifier_weights(profile: GoalProfile, env_scale: Dict[str, float]) -> Dict[str, float]:
    """
    Secondary modifier driven by Q16 (only if player wants a flight change).
    Smaller magnitude than primary goal so Q23 stays dominant.
    """
    if not profile.wants_flight_change:
        return {}

    e = env_scale
    t = (profile.flight_target or "").strip().lower()

    if "high" in t:
        return {
            "Launch Angle": 0.45 * e["launch"],
            "Landing Angle": 0.25 * e["landing"],
            "Spin Rate": 0.15 * e["spin"],
        }

    if "low" in t:
        return {
            "Launch Angle": -0.45 * e["launch"],
            "Landing Angle": -0.25 * e["landing"],
            "Spin Rate": -0.10 * e["spin"],
        }

    return {}


def score_goalcard(
    lab_df: pd.DataFrame,
    baseline_shaft_id: Optional[str],
    profile: GoalProfile,
) -> Dict[str, Any]:
    """
    Returns dict:
      baseline_shaft_id: str
      results: List[GoalScoreResult] sorted best->worst
      top_by_goal: dict[str, GoalScoreResult]
      goals_used: list[str]
    """
    if lab_df is None or lab_df.empty:
        return {"baseline_shaft_id": baseline_shaft_id, "results": [], "top_by_goal": {}, "goals_used": []}

    lab = lab_df.copy()
    for c in lab.columns:
        if lab[c].dtype == "object":
            lab[c] = lab[c].astype(str).str.strip()

    if "Shaft ID" not in lab.columns:
        return {"baseline_shaft_id": baseline_shaft_id, "results": [], "top_by_goal": {}, "goals_used": []}

    if not baseline_shaft_id:
        baseline_shaft_id = str(lab.iloc[0]["Shaft ID"]).strip()

    env_scale = _env_scale(profile.environment)

    primary_w = _primary_goal_weights(profile.primary_goal_key, env_scale)
    flight_mod_w = _flight_modifier_weights(profile, env_scale)

    # Guardrails to prevent "wins goal but tanks session"
    do_no_harm = {
        "Carry": 0.35,
        "Ball Speed": 0.25 * env_scale["speed"],
        "Smash Factor": 0.25,
    }

    goals: Dict[str, Dict[str, float]] = {}

    primary_title = f"Primary (Q23): {profile.primary_goal_raw or profile.primary_goal_key}"
    goals[primary_title] = primary_w

    if flight_mod_w:
        goals["Secondary (Q16): Flight Change"] = flight_mod_w

    goals["Guardrail: Do No Harm"] = do_no_harm

    goals_used = list(goals.keys())

    baseline_row = _first_row(lab, str(baseline_shaft_id))

    def denom_for(metric: str) -> float:
        """
        z-score denom uses baseline SD of metric if available, else 1.
        For SD metrics themselves, denom=1.
        """
        if metric.endswith(" SD"):
            return 1.0
        if baseline_row is not None:
            sd_col = f"{metric} SD"
            if sd_col in lab.columns:
                bsd = _get_metric(baseline_row, sd_col)
                if bsd is not None and bsd > 0:
                    return float(bsd)
        return 1.0

    results: List[GoalScoreResult] = []

    for _, row in lab.iterrows():
        sid = str(row.get("Shaft ID", "")).strip()
        if not sid:
            continue
        label = str(row.get("Shaft Label", "")).strip() or f"ID {sid}"

        deltas: Dict[str, float] = {}
        # compute deltas for all metrics used in any goal
        for _, weights in goals.items():
            for metric in weights.keys():
                if metric.endswith(" SD"):
                    d = _sd_delta(lab, sid, baseline_shaft_id, metric)
                    if d is None:
                        continue
                    deltas[metric] = float(d)
                else:
                    d = _delta(lab, sid, baseline_shaft_id, metric)
                    if d is None:
                        continue
                    deltas[metric] = float(d)

        goal_scores: Dict[str, float] = {}
        overall = 0.0

        # Goal blending weights: Q23 dominates, Q16 secondary, guardrail light
        for goal_name, weights in goals.items():
            g = 0.0
            for metric, w in weights.items():
                d = deltas.get(metric, None)
                if d is None:
                    continue
                denom = denom_for(metric) if not metric.endswith(" SD") else 1.0
                g += float(w) * _z(d, denom)

            goal_scores[goal_name] = float(g)

            if goal_name.startswith("Primary"):
                overall += 1.00 * g
            elif goal_name.startswith("Secondary"):
                overall += 0.55 * g
            else:
                overall += 0.35 * g

        # Reasons: top 3 absolute deltas from primary+secondary metrics (human-readable)
        reason_metrics = list(primary_w.keys()) + list(flight_mod_w.keys())
        contribs: List[Tuple[float, str]] = []

        for metric in reason_metrics:
            if metric not in deltas:
                continue
            d = deltas[metric]
            if metric.endswith(" SD"):
                contribs.append((abs(d), f"{metric} {'↓' if d < 0 else '↑'} {abs(d):.2f}"))
            else:
                contribs.append((abs(d), f"{metric} {'+' if d >= 0 else ''}{d:.2f}"))

        contribs = sorted(contribs, key=lambda x: x[0], reverse=True)[:3]
        reasons = [c[1] for c in contribs]

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

    # best per goal (excluding guardrail)
    top_by_goal: Dict[str, Any] = {}
    for goal in goals_used:
        if goal.startswith("Guardrail"):
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
