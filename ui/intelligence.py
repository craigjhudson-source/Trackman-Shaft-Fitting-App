# ui/intelligence.py
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd
import streamlit as st

from core.phase6_optimizer import phase6_recommendations
from ui.tour_proven_matrix import render_tour_proven_matrix

# Optional import so app doesn’t die if module missing
EFF_AVAILABLE = True
try:
    from core.efficiency_optimizer import EfficiencyConfig, build_comparison_table, pick_efficiency_winner
except Exception:
    EFF_AVAILABLE = False


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
    club: str = "6i",
) -> Tuple[Optional[pd.Series], pd.DataFrame, Optional[list]]:
    """
    Draws:
      - Baseline comparison table
      - Efficiency winner + flags
      - Tour Proven recommendation + matrix
      - Phase 6 suggestions

    Returns (winner_row, comparison_df, phase6_recs)
    """
    if not EFF_AVAILABLE:
        st.error(
            "Efficiency Optimizer module not available.\n\n"
            "Add core/efficiency_optimizer.py (and optionally core/__init__.py) then redeploy."
        )
        return None, pd.DataFrame(), None

    if lab_df is None or lab_df.empty:
        st.info("Upload + log TrackMan lab data to enable Intelligence.")
        return None, pd.DataFrame(), None

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
        cols = [c for c in display_cols if c in comparison_df.columns]
        st.dataframe(comparison_df[cols], use_container_width=True, hide_index=True, height=320)
    else:
        st.info("No comparison rows yet. Add at least one logged shaft set.")
        return None, pd.DataFrame(), None

    winner = pick_efficiency_winner(comparison_df)
    if winner is None:
        st.warning("No efficiency winner could be computed yet.")
        return None, comparison_df, None

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

    # Tour Proven decision matrix (goal-weighted, env-aware)
    render_tour_proven_matrix(
        comparison_df,
        baseline_shaft_id=str(baseline_shaft_id) if baseline_shaft_id else None,
        answers=answers,
        environment_override=environment,
    )

    # Phase 6
    st.subheader("Phase 6 Optimization Suggestions")

    w_id = str(winner.get("Shaft ID", ""))
    w_match = lab_df[lab_df["Shaft ID"].astype(str) == w_id] if "Shaft ID" in lab_df.columns else pd.DataFrame()
    winner_row = w_match.iloc[0] if len(w_match) else lab_df.iloc[0]

    recs = phase6_recommendations(
        winner_row,
        baseline_row=None,
        club=club,
        environment=environment,
    )

    for r in recs or []:
        sev = (r.get("severity") or "").lower()
        css = "rec-warn" if sev == "warn" else "rec-info"
        st.markdown(
            f"<div class='{css}'><b>{r.get('type','Note')}:</b> {r.get('text','')}</div>",
            unsafe_allow_html=True,
        )

    return winner, comparison_df, recs
