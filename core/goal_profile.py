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

    # Primary goal (Q23)
    primary_goal_raw: str
    primary_goal_key: str  # normalized bucket key we use in scoring

    # Flight (secondary modifier)
    flight_current: str
    flight_happy: str
    flight_target: str
    wants_flight_change: bool

    # Misc (optional)
    miss: str
    trying_to_beat_gamer: bool


def _primary_goal_key_from_q23(q23: str) -> str:
    """
    Map Q23 answer text to a stable key.
    We keep this forgiving so your sheet wording can change.
    """
    t = _low(q23)

    # Hold greens / stopping power
    if ("hold" in t and "green" in t) or ("stop" in t and "green" in t) or "landing angle" in t:
        return "HOLD_GREENS"

    # Dispersion / accuracy / stability
    if any(k in t for k in ["dispersion", "accuracy", "straight", "control", "stability", "consistent", "tighten"]):
        return "STABILITY"

    # Anti-left / hook
    if any(k in t for k in ["anti-left", "anti left", "hook", "left miss", "stop hooking", "pull hook"]):
        return "ANTI_LEFT"

    # Height / launch
    if any(k in t for k in ["launch", "height", "higher", "get it up", "peak height"]):
        return "FLIGHT_HIGHER"

    # Lower / penetrating
    if any(k in t for k in ["lower", "penetrating", "knockdown", "flight it down"]):
        return "FLIGHT_LOWER"

    # Distance / speed
    if any(k in t for k in ["distance", "carry", "speed", "ball speed", "more yards"]):
        return "DISTANCE"

    # Default if unknown
    return "BALANCED"


def build_goal_profile(answers: Dict[str, Any], environment: str = "") -> GoalProfile:
    env = _norm(environment) or _norm(answers.get("Q22")) or "Indoors (Mat)"

    # Q23 = primary decider
    q23 = _norm(answers.get("Q23"))
    primary_key = _primary_goal_key_from_q23(q23)

    # Flight / Feel (we only use Flight as secondary for now)
    flight_current = _norm(answers.get("Q16_1"))
    flight_happy = _norm(answers.get("Q16_2"))
    flight_target = _norm(answers.get("Q16_3"))
    wants_flight_change = _is_no_or_unsure(flight_happy) and bool(flight_target)

    # Optional (these IDs can vary; keep defensive)
    miss = _norm(answers.get("Q18"))

    # Gamer intent heuristic
    trying_text = " ".join([_low(answers.get(k)) for k in answers.keys()])
    trying_to_beat_gamer = "gamer" in trying_text and ("beat" in trying_text or "trying" in trying_text)

    return GoalProfile(
        environment=env,
        primary_goal_raw=q23,
        primary_goal_key=primary_key,
        flight_current=flight_current,
        flight_happy=flight_happy,
        flight_target=flight_target,
        wants_flight_change=wants_flight_change,
        miss=miss,
        trying_to_beat_gamer=trying_to_beat_gamer,
    )
