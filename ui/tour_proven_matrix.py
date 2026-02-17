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
      - Tour Proven Matrix buckets

    Safe to call even if table_df is empty.
    """
    # Guard: no lab data yet (common after "New Fitting")
    if table_df is None or table_df.empty:
        st.info("Tour Proven Matrix will appear after lab data is added.")
        return

    # Pull environment from interview answers (default if missing)
    environment = str(answers.get(environment_qid) or "Indoors (Mat)").strip()
    if not environment:
        environment = "Indoors (Mat)"

    # IMPORTANT: environment must be passed as a keyword argument
    decision = build_tour_proven_matrix(
        table_df,
        baseline_shaft_id=baseline_shaft_id,
        answers=answers,
        environment=environment,
    )

    st.subheader("Tour Proven Recommendation")

    # Highlighted banner block (robust to missing keys)
    h = decision.get("highlighted") or {}

    # If baseline tested best, show the note (but do NOT highlight baseline)
    note_if_baseline_best = h.get("note_if_baseline_best")
    if note_if_baseline_best:
        st.info(note_if_baseline_best)

    # If the engine detected "no meaningful upgrade", show message
    no_upgrade_msg = h.get("no_upgrade_msg")
    if no_upgrade_msg:
        st.warning(no_upgrade_msg)

    # Primary highlighted pick details
    shaft = h.get("shaft")
    if shaft:
        overall = float(h.get("overall_score") or 0.0)
        eff = float(h.get("efficiency") or 0.0)
        conf = float(h.get("confidence") or 0.0)

        st.markdown(
            f"### ✅ Highlighted Pick: **{shaft}**\n"
            f"- Overall: **{overall:.1f}**\n"
            f"- Efficiency: **{eff:.1f}**\n"
            f"- Confidence: **{conf:.1f}**"
        )

        tradeoff_line = h.get("tradeoff_line")
        if tradeoff_line:
            st.caption(tradeoff_line)

    # Too close to call message
    if decision.get("too_close") and decision.get("too_close_reason"):
        st.info(str(decision["too_close_reason"]))

    # Matrix list (bucket cards)
    matrix = decision.get("matrix") or []
    if not matrix:
        return

    st.subheader("Tour Proven Matrix")

    for item in matrix:
        bucket = str(item.get("bucket") or "").strip()
        shaft = str(item.get("shaft") or "").strip()
        conf = item.get("confidence", None)
        eff = item.get("efficiency", None)
        trade = item.get("tradeoff_line", None)
        reasons = item.get("reasons") or []

        title = f"{bucket}: {shaft}" if bucket and shaft else (bucket or shaft or "Recommendation")
        expanded = bucket.lower() == "overall" if bucket else False

        with st.expander(title, expanded=expanded):
            if eff is not None:
                try:
                    st.write(f"Efficiency: {float(eff):.1f}")
                except Exception:
                    st.write(f"Efficiency: {eff}")

            if conf is not None:
                try:
                    st.write(f"Confidence: {float(conf):.1f}")
                except Exception:
                    st.write(f"Confidence: {conf}")

            if trade:
                st.caption(str(trade))

            if reasons:
                for r in reasons:
                    st.write(f"- {r}")
