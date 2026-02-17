# ui/intelligence.py
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from core.efficiency_optimizer import EfficiencyConfig, build_comparison_table, pick_efficiency_winner
from ui.tour_proven_matrix import render_tour_proven_matrix


def render_intelligence_section(
    *,
    lab_df: Optional[pd.DataFrame],
    baseline_shaft_id: Optional[str],
    answers: Dict[str, Any],
    # pass your existing warning/threshold values in from app.py
    MIN_SHOTS: int,
    WARN_FACE_TO_PATH_SD: float,
    WARN_CARRY_SD: float,
    WARN_SMASH_SD: float,
) -> None:
    """
    This is the entire 'Intelligence' rendering block:
      - Builds comparison_df safely (never NameError)
      - Renders Tour Proven Matrix (safe)
      - Renders Baseline Comparison Table
      - Renders Efficiency Winner + confidence warnings
    """

    # ALWAYS define this so later code never NameErrors
    comparison_df = pd.DataFrame()

    # Build efficiency config from your inputs
    eff_cfg = EfficiencyConfig(
        MIN_SHOTS=int(MIN_SHOTS),
        WARN_FACE_TO_PATH_SD=float(WARN_FACE_TO_PATH_SD),
        WARN_CARRY_SD=float(WARN_CARRY_SD),
        WARN_SMASH_SD=float(WARN_SMASH_SD),
    )

    # Only build comparison table if lab_df exists
    if lab_df is not None and not lab_df.empty:
        comparison_df = build_comparison_table(
            lab_df,
            baseline_shaft_id=str(baseline_shaft_id) if baseline_shaft_id else None,
            cfg=eff_cfg,
        )

    # --- Tour Proven Matrix (new) ---
    # Safe even if comparison_df is empty
    render_tour_proven_matrix(
        comparison_df,
        baseline_shaft_id=baseline_shaft_id,
        answers=answers,
    )

    # --- Existing table ---
    st.subheader("📊 Baseline Comparison Table")

    display_cols = ["Shaft", "Carry Δ", "Launch Δ", "Spin Δ", "Smash", "Dispersion", "Efficiency", "Confidence"]
    if comparison_df is not None and not comparison_df.empty:
        # Only show columns that actually exist (prevents KeyError)
        cols = [c for c in display_cols if c in comparison_df.columns]
        st.dataframe(comparison_df[cols], use_container_width=True, hide_index=True, height=320)
    else:
        st.info("No comparison rows yet. Add at least one logged shaft set.")

    # --- Winner + warnings ---
    winner = pick_efficiency_winner(comparison_df) if comparison_df is not None and not comparison_df.empty else None

    if winner is None:
        st.warning("No efficiency winner could be computed yet.")
        return

    st.success(
        f"🏆 **Efficiency Winner:** {winner.get('Shaft', '')} "
        f"(Efficiency {winner.get('Efficiency', '')} | Confidence {winner.get('Confidence', '')})"
    )

    flags = winner.get("_flags") or {}
    if flags.get("low_shots"):
        st.warning(f"⚠️ Low shot count (MIN_SHOTS={int(MIN_SHOTS)}). Confidence reduced.")
    if flags.get("high_face_to_path_sd"):
        st.warning(f"⚠️ Face-to-Path SD high (> {float(WARN_FACE_TO_PATH_SD):.2f}). Confidence reduced.")
    if flags.get("high_carry_sd"):
        st.warning(f"⚠️ Carry SD high (> {float(WARN_CARRY_SD):.2f}). Confidence reduced.")
    if flags.get("high_smash_sd"):
        st.warning(f"⚠️ Smash SD high (> {float(WARN_SMASH_SD):.2f}). Confidence reduced.")
