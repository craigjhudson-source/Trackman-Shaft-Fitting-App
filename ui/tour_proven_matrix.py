from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from core.decision_engine import build_tour_proven_matrix


def _f(x: Any, default: float = 0.0) -> float:
    """
    Safe float formatter helper for UI.
    Accepts None / '' / numeric strings and returns a float.
    """
    try:
        if x is None:
            return float(default)
        if isinstance(x, str) and x.strip() == "":
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def render_tour_proven_matrix(
    table_df: pd.DataFrame,
    *,
    baseline_shaft_id: Optional[str],
    answers: Dict[str, Any],
    environment_qid: str = "Q22",
    environment_override: Optional[str] = None,
) -> None:
    """
    Renders:
      - Highlighted Recommendation (never baseline)
      - Too close to call message
      - 5-bucket matrix

    Safe to call even if table_df is empty.
    """
    if table_df is None or table_df.empty:
        st.info("Tour Proven Matrix will appear after lab data is added.")
        return

    env = (environment_override or answers.get(environment_qid) or "Indoors (Mat)").strip()
    if not env:
        env = "Indoors (Mat)"

    decision = build_tour_proven_matrix(
        table_df,
        baseline_shaft_id=baseline_shaft_id,
        answers=answers,
        environment=env,
    )

    st.subheader("Tour Proven Recommendation")

    h = decision.get("highlighted") or {}
    if isinstance(h, dict):
        if h.get("note_if_baseline_best"):
            st.info(str(h["note_if_baseline_best"]))
        if h.get("no_upgrade_msg"):
            st.warning(str(h["no_upgrade_msg"]))

        shaft_name = str(h.get("shaft") or "").strip()
        if shaft_name:
            overall_score = _f(h.get("overall_score"), 0.0)
            efficiency = _f(h.get("efficiency"), 0.0)
            confidence = _f(h.get("confidence"), 0.0)

            st.markdown(
                f"### ✅ Highlighted Pick: **{shaft_name}**\n"
                f"- Overall: **{overall_score:.1f}**\n"
                f"- Efficiency: **{efficiency:.1f}**\n"
                f"- Confidence: **{confidence:.1f}**"
            )
            if h.get("tradeoff_line"):
                st.caption(str(h["tradeoff_line"]))

    if decision.get("too_close") and decision.get("too_close_reason"):
        st.info(str(decision["too_close_reason"]))

    matrix = decision.get("matrix") or []
    if not isinstance(matrix, list) or len(matrix) == 0:
        return

    st.subheader("Tour Proven Matrix")

    for item in matrix:
        if not isinstance(item, dict):
            continue

        bucket = str(item.get("bucket", "") or "").strip()
        shaft = str(item.get("shaft", "") or "").strip()
        conf = item.get("confidence", None)
        eff = item.get("efficiency", None)
        trade = item.get("tradeoff_line", None)
        reasons = item.get("reasons") or []

        title = f"{bucket}: {shaft}".strip(": ").strip()
        if not title:
            title = "Recommendation"

        with st.expander(title, expanded=(bucket == "Overall")):
            if eff is not None:
                st.write(f"Efficiency: {_f(eff):.1f}")
            if conf is not None:
                st.write(f"Confidence: {_f(conf):.1f}")
            if trade:
                st.caption(str(trade))
            if isinstance(reasons, list):
                for r in reasons:
                    rr = str(r or "").strip()
                    if rr:
                        st.write(f"- {rr}")
