# ui/intelligence.py
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from core.efficiency_optimizer import (
    EfficiencyConfig,
    build_comparison_table,
    pick_efficiency_winner,
)
from core.phase6_optimizer import phase6_recommendations
from ui.tour_proven_matrix import render_tour_proven_matrix


def render_intelligence_block(
    *,
    lab_df: pd.DataFrame,
    baseline_shaft_id: Optional[str],
    answers: Dict[str, Any],
    environment: str,
    MIN_SHOTS: int = 8,
    WARN_FACE_TO_PATH_SD: float = 3.0,
    WARN_CARRY_SD: float = 10.0,
    WARN_SMASH_SD: float = 0.10,
) -> Optional[Dict[str, Any]]:
    """
    Renders the full Intelligence block inside TrackMan Lab:
      1) Baseline Comparison Table (Efficiency + Confidence)
      2) Efficiency Winner banner + quality warnings
      3) Tour Proven Matrix (5-bucket recommendation)
      4) Phase 6 optimizer suggestions for the efficiency winner

    Returns:
      phase6_recs (list[dict]) or None
    """

    if lab_df is None or lab_df.empty:
        st.info("Upload and log TrackMan data (click ➕ Add) to enable the intelligence layer.")
        return None

    # ------------------ Build comparison table ------------------
    eff_cfg = EfficiencyConfig(
        MIN_SHOTS=int(MIN_SHOTS),
        WARN_FACE_TO_PATH_SD=float(WARN_FACE_TO_PATH_SD),
        WARN_CARRY_SD=float(WARN_CARRY_SD),
        WARN_SMASH_SD=float(WARN_SMASH_SD),
    )

    comparison_df = build_comparison_table(
        lab_df,
        baseline_shaft_id=str(baseline_shaft_id) if baseline_shaft_id else None,
        cfg=eff_cfg,
    )

    st.subheader("📊 Baseline Comparison Table")

    display_cols = ["Shaft", "Carry Δ", "Launch Δ", "Spin Δ", "Smash", "Dispersion", "Efficiency", "Confidence"]
    if comparison_df is not None and not comparison_df.empty:
        safe_cols = [c for c in display_cols if c in comparison_df.columns]
        st.dataframe(comparison_df[safe_cols], use_container_width=True, hide_index=True, height=320)
    else:
        st.info("No comparison rows yet. Add at least one logged shaft set.")
        return None

    # ------------------ Pick winner + show warnings ------------------
    winner = pick_efficiency_winner(comparison_df)
    if winner is None:
        st.warning("No efficiency winner could be computed yet.")
        return None

    st.success(
        f"🏆 **Efficiency Winner:** {winner['Shaft']} "
        f"(Efficiency {winner['Efficiency']} | Confidence {winner['Confidence']})"
    )

    flags = winner.get("_flags") or {}
    if flags.get("low_shots"):
        st.warning(f"⚠️ Low shot count (MIN_SHOTS={int(MIN_SHOTS)}). Confidence reduced.")
    if flags.get("high_face_to_path_sd"):
        st.warning(f"⚠️ Face-to-Path SD high (> {float(WARN_FACE_TO_PATH_SD):.2f}). Confidence reduced.")
    if flags.get("high_carry_sd"):
        st.warning(f"⚠️ Carry SD high (> {float(WARN_CARRY_SD):.1f}). Confidence reduced.")
    if flags.get("high_smash_sd"):
        st.warning(f"⚠️ Smash SD high (> {float(WARN_SMASH_SD):.3f}). Confidence reduced.")

    st.divider()

    # ------------------ Tour Proven Matrix ------------------
    # IMPORTANT: keyword args required (tour_proven_matrix signature enforces this)
    render_tour_proven_matrix(
        comparison_df,
        baseline_shaft_id=str(baseline_shaft_id) if baseline_shaft_id else None,
        answers=answers or {},
        environment_qid="Q22",
    )

    st.divider()

    # ------------------ Phase 6 Optimization Suggestions ------------------
    st.subheader("Phase 6 Optimization Suggestions")

    # Find row in lab_df matching the winning shaft id (fallback to first row)
    w_id = str(winner.get("Shaft ID", ""))
    try:
        w_match = lab_df[lab_df["Shaft ID"].astype(str) == w_id]
        winner_row = w_match.iloc[0] if len(w_match) else lab_df.iloc[0]
    except Exception:
        winner_row = lab_df.iloc[0]

    recs = phase6_recommendations(
        winner_row,
        baseline_row=None,
        club="6i",
        environment=environment,
    )

    # Return to caller to include in PDF if desired
    return {"phase6_recs": recs}
