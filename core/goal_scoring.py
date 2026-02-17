# core/goal_profile.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


def _norm(s: Any) -> str:
    return "" if s is None else str(s).strip()


def _low(s: Any) -> str:
    return _norm(s).lower()


def _is_no_or_unsure(s: Any) -> bool:
    v = _low(s)
    v = v.replace("-", " ").replace("_", " ")
    v = " ".join(v.split())
    return v in {"no", "unsure", "not sure", "maybe"}


@dataclass(frozen=True)
class GoalProfile:
    environment: str

    # Q23
    primary_goal_raw: str
    primary_goal_key: str  # one of: DISTANCE, STABILITY, HOLD_GREENS, FLIGHT_WINDOW, BALANCED, BEAT_GAMER

    # Q16 (secondary)
    flight_current: str
    flight_happy: str
    flight_target: str
    wants_flight_change: bool

    # optional context
    miss: str


def _primary_goal_key_from_q23(q23: str) -> str:
    """
    Exact mapping from your Q23 dropdown options.
    This is deterministic (no keyword guessing).
    """
    t = (q23 or "").strip().lower()

    if t == "more distance":
        return "DISTANCE"

    if t == "straighter":
        return "STABILITY"

    if t == "hold greens better":
        return "HOLD_GREENS"

    if t == "flight window":
        return "FLIGHT_WINDOW"

    if t == "a bit of everything":
        return "BALANCED"

    if t == "trying to beat my gamer":
        return "BEAT_GAMER"

    return "BALANCED"


def build_goal_profile(answers: Dict[str, Any], environment: str = "") -> GoalProfile:
    env = _norm(environment) or _norm(answers.get("Q22")) or "Indoors (Mat)"

    # Q23 primary decider
    q23 = _norm(answers.get("Q23"))
    primary_key = _primary_goal_key_from_q23(q23)

    # Q16 secondary
    flight_current = _norm(answers.get("Q16_1"))
    flight_happy = _norm(answers.get("Q16_2"))
    flight_target = _norm(answers.get("Q16_3"))
    wants_flight_change = _is_no_or_unsure(flight_happy) and bool(flight_target)

    # optional
    miss = _norm(answers.get("Q18"))

    return GoalProfile(
        environment=env,
        primary_goal_raw=q23,
        primary_goal_key=primary_key,
        flight_current=flight_current,
        flight_happy=flight_happy,
        flight_target=flight_target,
        wants_flight_change=wants_flight_change,
        miss=miss,
    )
