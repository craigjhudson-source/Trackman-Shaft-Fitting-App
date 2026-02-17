# core/goal_profile.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


def _norm(s: Any) -> str:
    return "" if s is None else str(s).strip()


def _low(s: Any) -> str:
    return _norm(s).lower()


def _is_yes(s: Any) -> bool:
    v = _low(s)
    return v in {"yes", "y", "true"}


def _is_no_or_unsure(s: Any) -> bool:
    v = _low(s)
    v = v.replace("-", " ").replace("_", " ")
    v = " ".join(v.split())
    return v in {"no", "unsure", "not sure", "maybe"}


@dataclass(frozen=True)
class GoalProfile:
    environment: str

    # Flight
    flight_current: str
    flight_happy: str
    flight_target: str  # Higher/Lower/"" (only meaningful if not happy)

    # Feel
    feel_current: str
    feel_happy: str
    feel_target: str  # Smoother/Firmer/etc (only meaningful if not happy)

    # Misc (optional)
    miss: str
    trying_to_beat_gamer: bool

    # Derived flags
    wants_flight_change: bool
    wants_feel_change: bool
    wants_hold_greens: bool
    wants_anti_left: bool


def build_goal_profile(answers: Dict[str, Any], environment: str = "") -> GoalProfile:
    env = _norm(environment) or _norm(answers.get("Q22")) or "Indoors (Mat)"

    # Flight / Feel (your locked sheet truth)
    flight_current = _norm(answers.get("Q16_1"))
    flight_happy = _norm(answers.get("Q16_2"))
    flight_target = _norm(answers.get("Q16_3"))

    feel_current = _norm(answers.get("Q19_1"))
    feel_happy = _norm(answers.get("Q19_2"))
    feel_target = _norm(answers.get("Q19_3"))

    # Optional (these IDs can vary by sheet; keep defensive)
    miss = _norm(answers.get("Q18"))

    # Try to beat gamer: we infer from any answer text containing "gamer"
    trying_text = " ".join([_low(answers.get(k)) for k in answers.keys()])
    trying_to_beat_gamer = "gamer" in trying_text and ("beat" in trying_text or "trying" in trying_text)

    wants_flight_change = _is_no_or_unsure(flight_happy) and bool(flight_target)
    wants_feel_change = _is_no_or_unsure(feel_happy) and bool(feel_target)

    # Hold greens: detect by scanning answers text (keeps it sheet-agnostic)
    wants_hold_greens = "hold" in trying_text and "green" in trying_text

    # Anti-left: detect miss tendency mentions
    miss_l = _low(miss)
    wants_anti_left = any(x in miss_l for x in ["left", "hook", "pull"])

    return GoalProfile(
        environment=env,
        flight_current=flight_current,
        flight_happy=flight_happy,
        flight_target=flight_target,
        feel_current=feel_current,
        feel_happy=feel_happy,
        feel_target=feel_target,
        miss=miss,
        trying_to_beat_gamer=trying_to_beat_gamer,
        wants_flight_change=wants_flight_change,
        wants_feel_change=wants_feel_change,
        wants_hold_greens=wants_hold_greens,
        wants_anti_left=wants_anti_left,
    )
