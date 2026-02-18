# ui/intelligence.py
from __future__ import annotations

import re
from typing import Any, Dict, Optional, List

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


_ID_RE = re.compile(r"\(ID\s*([0-9]+)\)", re.IGNORECASE)


def _safe_str(x: Any) -> str:
    try:
        return str(x).strip()
    except Exception:
        return ""


def _extract_id_from_label(label: str) -> Optional[str]:
    """
    Attempts to parse "(ID 28)" style suffixes used in your UI labels.
    """
    if not label:
        return None
    m = _ID_RE.search(label)
    if not m:
        return None
    return m.group(1).strip()


def _coerce_shaft_id(row: Dict[str, Any]) -> Optional[str]:
    """
    Prefer explicit Shaft ID column, else parse from label.
    """
    sid = _safe_str(row.get("Shaft ID", ""))
    if sid:
        return sid
    return _extract_id_from_label(_safe_str(row.get("Shaft", "")))


def _build_fallback_goal_rankings(
    comparison_df: pd.DataFrame,
    *,
    baseline_shaft_id: Optional[str],
) -> Dict[str, Any]:
    """
    This is a TEMPORARY bridge so Recommendations can show something meaningful
    immediately after Trackman logging, even before we fully activate Q23/Q16 goal scoring.

    We rank by Efficiency (then Confidence), and provide a small explanation list.
    """
    out: Dict[str, Any] = {
        "baseline_shaft_id": _safe_str(baseline_shaft_id) if baseline_shaft_id else None,
        "results": [],
        "top_by_goal": {},
        "source": "efficiency_fallback",
    }

    if comparison_df is None or comparison_df.empty:
        return out

    df = comparison_df.copy()

    # Ensure we have columns we expect
    for c in ["Efficiency", "Confidence", "Carry Δ", "Launch Δ", "Spin Δ", "Dispersion", "Smash", "Shaft", "Shaft ID"]:
        if c not in df.columns:
            df[c] = None

    # Sort best-first
    def _to_float(v: Any) -> float:
        try:
            return float(v)
        except Exception:
            return 0.0

    df["_eff"] = df["Efficiency"].apply(_to_float)
    df["_conf"] = df["Confidence"].apply(_to_float)

    df = df.sort_values(by=["_eff", "_conf"], ascending=[False, False])

    results: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        row = r.to_dict()
        sid = _coerce_shaft_id(row)
        label = _safe_str(row.get("Shaft", ""))

        reasons: List[str] = []
        cd = row.get("Carry Δ", None)
        ld = row.get("Launch Δ", None)
        sd = row.get("Spin Δ", None)
        disp = row.get("Dispersion", None)

        # Keep reasons short + readable
        if cd is not None and _safe_str(cd):
            reasons.append(f"Carry Δ: {cd}")
        if ld is not None and _safe_str(ld):
            reasons.append(f"Launch Δ: {ld}")
        if sd is not None and _safe_str(sd):
            reasons.append(f"Spin Δ: {sd}")
        if disp is not None and _safe_str(disp):
            reasons.append(f"Dispersion: {disp}")

        overall_score = _to_float(row.get("Efficiency", 0.0))

        results.append(
            {
                "shaft_id": sid,
                "shaft_label": label,
                "overall_score": overall_score,
                "reasons": reasons[:3],
                "goal_scores": {"Efficiency": overall_score},
                "raw": row,
            }
        )

    out["results"] = results

    # Provide a single "goal" card so Recommendations can render "Best by goal"
    if results:
        out["top_by_goal"] = {"Efficiency": results[0]}

    return out


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
) -> Dict[str, Any]:
    """
    Draws:
      - Baseline comparison table
      - Efficiency winner + flags
      - Tour Proven recommendation + matrix
      - Phase 6 suggestions

    IMPORTANT SIDE EFFECT (required by your app UX):
      - Writes st.session_state.winner_summary so Recommendations can unlock PDF + show winner
      - Writes st.session_state.goal_rankings so Recommendations can show Trackman-based rankings
    """
    out: Dict[str, Any] = {
        "winner": None,
        "winner_summary": None,
        "comparison_df": pd.DataFrame(),
        "goal_rankings": None,
        "phase6_recs": None,
    }

    if not EFF_AVAILABLE:
        st.error(
            "Efficiency Optimizer module not available.\n\n"
            "Add core/efficiency_optimizer.py (and optionally core/__init__.py) then redeploy."
        )
        return out

    if lab_df is None or lab_df.empty:
        st.info("Upload + log TrackMan lab data to enable Intelligence.")
        return out

    eff_cfg = EfficiencyConfig(
        MIN_SHOTS=int(MIN_SHOTS),
        WARN_FACE_TO_PATH_SD=float(WARN_FACE_TO_PATH_SD),
        WARN_CARRY_SD=float(WARN_CARRY_SD),
        WARN_SMASH_SD=float(WARN_SMASH_SD),
    )

    comparison_df = build_comparison_table(
        lab_df,
        baseline_shaft_id=_safe_str(baseline_shaft_id) if baseline_shaft_id else None,
        cfg=eff_cfg,
    )

    out["comparison_df"] = comparison_df

    st.subheader("📊 Baseline Comparison Table")
    display_cols = ["Shaft", "Carry Δ", "Launch Δ", "Spin Δ", "Smash", "Dispersion", "Efficiency", "Confidence"]
    if comparison_df is not None and not comparison_df.empty:
        cols = [c for c in display_cols if c in comparison_df.columns]
        st.dataframe(comparison_df[cols], use_container_width=True, hide_index=True, height=320)
    else:
        st.info("No comparison rows yet. Add at least one logged shaft set.")
        return out

    winner = pick_efficiency_winner(comparison_df)
    out["winner"] = winner

    if winner is None:
        st.warning("No efficiency winner could be computed yet.")
        return out

    # ---------------- Winner summary (for Recommendations tab) ----------------
    winner_label = _safe_str(winner.get("Shaft", ""))
    winner_id = _safe_str(winner.get("Shaft ID", "")) or (_extract_id_from_label(winner_label) or "")

    explain = f"Efficiency {winner.get('Efficiency')} | Confidence {winner.get('Confidence')}"
    winner_summary = {
        "shaft_id": winner_id or None,
        "shaft_label": winner_label or None,
        "headline": "Efficiency Winner",
        "explain": explain,
        "raw": winner,
    }

    # Persist so Recommendations can see it reliably
    st.session_state.winner_summary = winner_summary
    out["winner_summary"] = winner_summary

    st.success(f"🏆 **Efficiency Winner:** {winner_label} ({explain})")

    flags = winner.get("_flags") or {}
    if flags.get("low_shots"):
        st.warning(f"⚠️ Low shot count (MIN_SHOTS={int(MIN_SHOTS)}). Confidence reduced.")
    if flags.get("high_face_to_path_sd"):
        st.warning(f"⚠️ Face-to-Path SD high (> {float(WARN_FACE_TO_PATH_SD):.2f}). Confidence reduced.")
    if flags.get("high_carry_sd"):
        st.warning(f"⚠️ Carry SD high (> {float(WARN_CARRY_SD):.1f}). Confidence reduced.")
    if flags.get("high_smash_sd"):
        st.warning(f"⚠️ Smash SD high (> {float(WARN_SMASH_SD):.3f}). Confidence reduced.")

    # ---------------- Tour Proven matrix (still renders as before) ----------------
    render_tour_proven_matrix(
        comparison_df,
        baseline_shaft_id=_safe_str(baseline_shaft_id) if baseline_shaft_id else None,
        answers=answers,
        environment_override=environment,
    )

    # ---------------- Goal rankings (bridge so Recommendations changes after upload) ----------------
    goal_rankings = _build_fallback_goal_rankings(
        comparison_df,
        baseline_shaft_id=_safe_str(baseline_shaft_id) if baseline_shaft_id else None,
    )
    st.session_state.goal_rankings = goal_rankings
    out["goal_rankings"] = goal_rankings

    # ---------------- Phase 6 ----------------
    st.subheader("Phase 6 Optimization Suggestions")

    w_id = _safe_str(winner.get("Shaft ID", ""))
    if "Shaft ID" in lab_df.columns and w_id:
        w_match = lab_df[lab_df["Shaft ID"].astype(str) == w_id]
    else:
        w_match = pd.DataFrame()

    winner_row = w_match.iloc[0] if len(w_match) else lab_df.iloc[0]

    recs = phase6_recommendations(
        winner_row,
        baseline_row=None,
        club=club,
        environment=environment,
    )

    out["phase6_recs"] = recs
    st.session_state.phase6_recs = recs

    for r in recs or []:
        sev = (_safe_str(r.get("severity", ""))).lower()
        css = "rec-warn" if sev == "warn" else "rec-info"
        st.markdown(
            f"<div class='{css}'><b>{_safe_str(r.get('type','Note'))}:</b> {_safe_str(r.get('text',''))}</div>",
            unsafe_allow_html=True,
        )

    return out
