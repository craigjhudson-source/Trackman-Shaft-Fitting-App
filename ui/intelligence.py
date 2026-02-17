# ui/intelligence.py
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from core.efficiency_optimizer import EfficiencyConfig, build_comparison_table, pick_efficiency_winner
from core.phase6_optimizer import phase6_recommendations
from ui.tour_proven_matrix import render_tour_proven_matrix


def render_intelligence_block(
    *,
    lab_df: pd.DataFrame,
    baseline_shaft_id: Optional[str],
    answers: Dict[str, Any],
    environment: str,
    MIN_SHOTS: int,
    WARN_FACE_TO_PATH_SD: float,
    WARN_CARRY_SD: float,
    WARN_SMASH_SD: float,
) -> None:
    """
    Safe, modular Intelligence section:
    - ALWAYS defines comparison_df (prevents NameError)
    - Builds comparison table if possible
    - Renders Tour Proven Matrix
    - Renders Baseline Comparison table
    - Picks winner and shows confidence warnings
    - Runs Phase 6 recs
    """

    # Prevent NameError forever:
    comparison_df = pd.DataFrame()

    if lab_df is None or lab_df.empty:
        st.info("Upload files to begin correlation.")
        return

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

    # --- Tour Proven Matrix (new) ---
    render_tour_proven_matrix(
        comparison_df,
        baseline_shaft_id=baseline_shaft_id,
        answers=answers,
    )

    # --- Baseline table ---
    st.subheader("📊 Baseline Comparison Table")

    display_cols = ["Shaft", "Carry Δ", "Launch Δ", "Spin Δ", "Smash", "Dispersion", "Efficiency", "Confidence"]
    if comparison_df is not None and not comparison_df.empty:
        cols = [c for c in display_cols if c in comparison_df.columns]
        st.dataframe(comparison_df[cols], use_container_width=True, hide_index=True, height=320)
    else:
        st.info("No comparison rows yet. Add at least one logged shaft set.")
        return

    # --- Winner ---
    winner = pick_efficiency_winner(comparison_df)
    if winner is None:
        st.warning("No efficiency winner could be computed yet.")
        return

    st.success(
        f"🏆 **Efficiency Winner:** {winner.get('Shaft','')} "
        f"(Efficiency {winner.get('Efficiency','')} | Confidence {winner.get('Confidence','')})"
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

    # --- Phase 6 ---
    st.subheader("Phase 6 Optimization Suggestions")

    try:
        w_id = str(winner.get("Shaft ID", "")).strip()
        if w_id and "Shaft ID" in lab_df.columns:
            w_match = lab_df[lab_df["Shaft ID"].astype(str) == w_id]
            winner_row = w_match.iloc[0] if len(w_match) else lab_df.iloc[0]
        else:
            winner_row = lab_df.iloc[0]

        recs = phase6_recommendations(
            winner_row,
            baseline_row=None,
            club="6i",
            environment=environment,
        )

        # Return these to app.py via session_state if you want
        st.session_state.phase6_recs = recs

        for r in recs:
            sev = r.get("severity")
            if sev == "warn":
                st.warning(f"{r.get('type','Note')}: {r.get('text','')}")
            else:
                st.info(f"{r.get('type','Note')}: {r.get('text','')}")

    except Exception as e:
        st.error(f"Phase 6 optimizer error: {e}")
