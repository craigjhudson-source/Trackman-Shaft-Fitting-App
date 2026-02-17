# ui/tour_proven_matrix.py
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from core.decision_engine import build_tour_proven_matrix


def render_tour_proven_matrix(
    table_df: pd.DataFrame,
    *,
    baseline_shaft_id: Optional[str],
    answers: Dict[str, Any],
    environment_qid: str = "Q22",
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

    environment = (answers.get(environment_qid) or "Indoor").strip() or "Indoor"

    decision = build_tour_proven_matrix(
        table_df,
        baseline_shaft_id=baseline_shaft_id,
        answers=answers,
        environment=environment,
    )

    st.subheader("Tour Proven Recommendation")

    # Highlighted banner
    h = decision.get("highlighted") or {}
    if h.get("note_if_baseline_best"):
        st.info(h["note_if_baseline_best"])
    if h.get("no_upgrade_msg"):
        st.warning(h["no_upgrade_msg"])

    if h.get("shaft"):
        st.markdown(
            f"### ✅ Highlighted Pick: **{h['shaft']}**\n"
            f"- Overall: **{h.get('overall_score', 0):.1f}**\n"
            f"- Efficiency: **{(h.get('efficiency') or 0):.1f}**\n"
            f"- Confidence: **{(h.get('confidence') or 0):.1f}**"
        )
        if h.get("tradeoff_line"):
            st.caption(h["tradeoff_line"])

    # Too close to call
    if decision.get("too_close") and decision.get("too_close_reason"):
        st.info(decision["too_close_reason"])

    # Matrix
    matrix = decision.get("matrix") or []
    if not matrix:
        return

    st.subheader("Tour Proven Matrix")

    for item in matrix:
        bucket = item.get("bucket", "")
        shaft = item.get("shaft", "")
        conf = item.get("confidence", None)
        eff = item.get("efficiency", None)
        trade = item.get("tradeoff_line", None)
        reasons = item.get("reasons") or []

        with st.expander(f"{bucket}: {shaft}", expanded=(bucket == "Overall")):
            if eff is not None:
                st.write(f"Efficiency: {float(eff):.1f}")
            if conf is not None:
                st.write(f"Confidence: {float(conf):.1f}")
            if trade:
                st.caption(trade)
            for r in reasons:
                st.write(f"- {r}")
