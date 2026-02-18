# core/session_state.py
from __future__ import annotations

from typing import Any


def init_session_state(st: Any) -> None:
    """
    Centralized Streamlit session_state initialization.

    Goals:
      - Prevent KeyErrors / AttributeErrors across tabs
      - Ensure reruns / tab switches keep stable containers
      - Avoid overwriting existing values
    """
    ss = st.session_state

    # ---------------- Interview flow keys ----------------
    if "form_step" not in ss:
        ss["form_step"] = 0
    if "interview_complete" not in ss:
        ss["interview_complete"] = False
    if "email_sent" not in ss:
        ss["email_sent"] = False

    # Answers container (interview writes here)
    if "answers" not in ss or not isinstance(ss.get("answers"), dict):
        ss["answers"] = {}

    # Environment default used by Trackman tab + profile
    if "environment" not in ss:
        ss["environment"] = "Indoors (Mat)"

    # ---------------- Trackman / lab containers ----------------
    if "tm_lab_data" not in ss or not isinstance(ss.get("tm_lab_data"), list):
        ss["tm_lab_data"] = []

    # Canonical preview persistence keys
    if "tm_preview_df" not in ss:
        ss["tm_preview_df"] = None
    if "tm_preview_name" not in ss:
        ss["tm_preview_name"] = None
    if "tm_preview_time" not in ss:
        ss["tm_preview_time"] = None

    # Optional legacy preview keys (some older code may read these)
    if "tm_last_preview_df" not in ss:
        ss["tm_last_preview_df"] = None
    if "tm_last_preview_name" not in ss:
        ss["tm_last_preview_name"] = None
    if "tm_last_preview_time" not in ss:
        ss["tm_last_preview_time"] = None

    # Used to signal downstream refresh after successful Add
    if "tm_data_version" not in ss:
        ss["tm_data_version"] = 0

    # ---------------- Intelligence outputs ----------------
    # Canonical output to drive Recommendations tab post-Trackman
    if "goal_recommendations" not in ss:
        ss["goal_recommendations"] = None

    # Legacy key some UI may still read
    if "goal_recs" not in ss:
        ss["goal_recs"] = None

    if "phase6_recs" not in ss:
        ss["phase6_recs"] = None
    if "winner_summary" not in ss:
        ss["winner_summary"] = None

    # ---------------- Critical fix: lab_controls ----------------
    if "lab_controls" not in ss or not isinstance(ss.get("lab_controls"), dict):
        ss["lab_controls"] = {
            "length_matched": False,
            "swing_weight_matched": False,
            "grip_matched": False,
            "same_head": False,
            "same_ball": False,
        }
    else:
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
