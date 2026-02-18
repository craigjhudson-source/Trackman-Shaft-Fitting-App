# core/session_state.py
from __future__ import annotations

from typing import Any, Dict


def init_session_state(st: Any) -> None:
    """
    Centralized Streamlit session_state initialization.

    Goals:
      - Prevent KeyErrors (notably lab_controls)
      - Provide stable containers for tab switching / reruns
      - Avoid overwriting any existing session_state values
    """

    ss = st.session_state

    # Interview answers live here (per sheet glossary).
    if "answers" not in ss or not isinstance(ss.get("answers"), dict):
        ss["answers"] = {}

    # Trackman tab: persist preview df so it doesn't disappear on rerun/tab switch.
    # (Set to None by default; UI should render from this when present.)
    if "tm_preview_df" not in ss:
        ss["tm_preview_df"] = None

    # Trackman sessions / summaries (keep as dict container; content managed elsewhere).
    if "tm_sessions" not in ss or not isinstance(ss.get("tm_sessions"), dict):
        ss["tm_sessions"] = {}

    # Goal-based recommendations should be the post-lab source of truth for Rec tab.
    # Expected to hold a dict payload (leaderboard/winner/etc), but default to None.
    if "goal_recommendations" not in ss:
        ss["goal_recommendations"] = None

    # Used to force Streamlit refresh behavior after successful lab "Add" actions
    # (per patch queue: increment on successful Add).
    if "tm_data_version" not in ss:
        ss["tm_data_version"] = 0

    # Critical fix: lab_controls must always exist before any UI reads it.
    if "lab_controls" not in ss or not isinstance(ss.get("lab_controls"), dict):
        ss["lab_controls"] = {
            "length_matched": False,
            "swing_weight_matched": False,
            "grip_matched": False,
            "same_head": False,
            "same_ball": False,
        }
    else:
        # Ensure required keys exist even if an older session_state dict is present.
        defaults = {
            "length_matched": False,
            "swing_weight_matched": False,
            "grip_matched": False,
            "same_head": False,
            "same_ball": False,
        }
        for k, v in defaults.items():
            if k not in ss["lab_controls"]:
                ss["lab_controls"][k] = v

    # Optional: a place to stash last computed winner/summary objects.
    # These defaults are non-invasive and safe.
    if "winner_summary" not in ss:
        ss["winner_summary"] = None
    if "phase6_suggestions" not in ss:
        ss["phase6_suggestions"] = None
