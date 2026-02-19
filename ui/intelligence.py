from __future__ import annotations

import re
from typing import Any, Dict, Optional, List, Set, Tuple

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


def _to_float(x: Any, default: float = 0.0) -> float:
    """
    Never-throw numeric coercion. Streamlit redacts tracebacks, so we keep this strict.
    """
    try:
        if x is None:
            return float(default)
        if isinstance(x, str):
            s = x.strip()
            if s == "" or s.lower() in {"nan", "none", "—", "-", "na", "n/a"}:
                return float(default)
            return float(s)
        return float(x)
    except Exception:
        return float(default)


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


def _tested_shaft_ids_from_lab(lab_df: pd.DataFrame) -> Set[str]:
    out: Set[str] = set()
    try:
        if lab_df is None or lab_df.empty:
            return out
        if "Shaft ID" in lab_df.columns:
            vals = lab_df["Shaft ID"].astype(str).str.strip()
            out.update([v for v in vals.tolist() if v])
    except Exception:
        return out
    return out


def _get_shafts_df_for_pool() -> pd.DataFrame:
    """
    Candidate pool must come from Shafts sheet and use Shafts!ID (never dataframe index).
    We rely on app.py setting:
      st.session_state.shafts_df_for_ui / st.session_state.all_shafts_df
    """
    df = st.session_state.get("shafts_df_for_ui", None)
    if isinstance(df, pd.DataFrame) and not df.empty:
        return df
    df = st.session_state.get("all_shafts_df", None)
    if isinstance(df, pd.DataFrame) and not df.empty:
        return df
    return pd.DataFrame()


def _weight_num(x: Any) -> Optional[float]:
    try:
        s = str(x).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def _lookup_gamer_identity(answers: Dict[str, Any]) -> Tuple[str, str, str]:
    # Q10 = Brand, Q12 = Model, Q11 = Flex
    b = _safe_str(answers.get("Q10", "")).lower()
    m = _safe_str(answers.get("Q12", "")).lower()
    f = _safe_str(answers.get("Q11", "")).lower()
    return b, m, f


def _lookup_gamer_weight(shafts_df: pd.DataFrame, answers: Dict[str, Any]) -> Optional[float]:
    if shafts_df is None or shafts_df.empty:
        return None

    b, m, f = _lookup_gamer_identity(answers)
    if not b or not m:
        return None

    df = shafts_df.copy()
    for c in ["ID", "Brand", "Model", "Flex", "Weight (g)", "Weight"]:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].astype(str).str.strip()

    hit = df[(df["Brand"].str.lower() == b) & (df["Model"].str.lower() == m)]
    if f:
        hit_f = hit[hit["Flex"].str.lower() == f]
        if not hit_f.empty:
            hit = hit_f

    if hit.empty:
        return None

    w = hit.iloc[0].get("Weight (g)", "") or hit.iloc[0].get("Weight", "")
    wn = _weight_num(w)
    return wn


def _label_for_id(shafts_df: pd.DataFrame, sid: str) -> str:
    """
    Build a consistent label for display (but ID is always the canonical join key).
    """
    if shafts_df is None or shafts_df.empty:
        return f"Unknown Shaft (ID {sid})"

    df = shafts_df.copy()
    for c in ["ID", "Brand", "Model", "Flex", "Weight (g)", "Weight"]:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].astype(str).str.strip()

    hit = df[df["ID"] == str(sid).strip()]
    if hit.empty:
        return f"Unknown Shaft (ID {sid})"

    r = hit.iloc[0]
    brand = _safe_str(r.get("Brand", ""))
    model = _safe_str(r.get("Model", ""))
    flex = _safe_str(r.get("Flex", ""))
    wt = _safe_str(r.get("Weight (g)", "")) or _safe_str(r.get("Weight", ""))

    label = " ".join([x for x in [brand, model, flex] if x]).strip() or f"Shaft (ID {sid})"
    if wt:
        label = f"{label} | {wt}g"
    return f"{label} (ID {sid})"


def _build_next_round_pool(
    shafts_df: pd.DataFrame,
    *,
    answers: Dict[str, Any],
    baseline_shaft_id: Optional[str],
    tested_ids: Set[str],
    max_n: int = 3,
) -> List[Dict[str, Any]]:
    """
    Produces UNTESTED next-round candidates using only Shafts!ID.

    Priority:
      1) Stage-1 shortlist IDs (st.session_state.pretest_shortlist_df)
      2) Widen within same Brand closest weight to gamer
    """
    out: List[Dict[str, Any]] = []

    # Defensive baseline filter
    base_id = _safe_str(baseline_shaft_id) if baseline_shaft_id else ""
    if base_id:
        tested_ids = set(tested_ids)
        tested_ids.add(base_id)

    if shafts_df is None or shafts_df.empty:
        return out

    df = shafts_df.copy()
    for c in ["ID", "Brand", "Model", "Flex", "Weight (g)", "Weight"]:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].astype(str).str.strip()

    # --- 1) Stage-1 shortlist IDs
    seed_ids: List[str] = []
    pre = st.session_state.get("pretest_shortlist_df", None)
    if isinstance(pre, pd.DataFrame) and not pre.empty and "ID" in pre.columns:
        seed_ids = [str(x).strip() for x in pre["ID"].tolist() if str(x).strip()]

    seed_ids = [sid for sid in seed_ids if sid not in tested_ids]

    for sid in seed_ids:
        out.append(
            {
                "shaft_id": sid,
                "shaft_label": _label_for_id(df, sid),
                "overall_score": 0.0,
                "reasons": ["Next round candidate (from Stage-1 shortlist)", "Not yet tested in TrackMan Lab"],
                "goal_scores": {"Next Round": 0.0},
                "source": "next_round_pool",
            }
        )
        if len(out) >= max_n:
            return out

    # --- 2) Widen by same Brand, closest weight to gamer
    gamer_brand = _safe_str(answers.get("Q10", ""))
    gamer_weight = _lookup_gamer_weight(df, answers)

    candidates = df.copy()
    candidates = candidates[~candidates["ID"].isin(list(tested_ids))]

    if gamer_brand:
        candidates = candidates[candidates["Brand"].str.lower() == gamer_brand.lower()]

    # compute weight diffs
    candidates["__w__"] = candidates["Weight (g)"].apply(_weight_num)
    if gamer_weight is not None:
        candidates["__w_diff__"] = candidates["__w__"].apply(lambda w: abs(w - gamer_weight) if w is not None else 9999.0)
    else:
        candidates["__w_diff__"] = 9999.0

    candidates = candidates.sort_values(by=["__w_diff__"], ascending=[True])

    for _, r in candidates.iterrows():
        sid = _safe_str(r.get("ID", ""))
        if not sid or sid in tested_ids:
            continue
        why = ["Next round candidate (same brand, closest weight to gamer)", "Not yet tested in TrackMan Lab"]
        out.append(
            {
                "shaft_id": sid,
                "shaft_label": _label_for_id(df, sid),
                "overall_score": 0.0,
                "reasons": why[:3],
                "goal_scores": {"Next Round": 0.0},
                "source": "next_round_pool",
            }
        )
        if len(out) >= max_n:
            break

    return out


def _build_fallback_goal_rankings(
    comparison_df: pd.DataFrame,
    *,
    baseline_shaft_id: Optional[str],
    shafts_df: pd.DataFrame,
    answers: Dict[str, Any],
    tested_ids: Set[str],
) -> Dict[str, Any]:
    """
    Bridge so Recommendations can show meaningful Trackman-based rankings
    immediately after logging.

    We rank by Efficiency (then Confidence), and provide short reasons.

    PLUS:
      - append a small "next round pool" of UNTESTED Shafts!ID candidates
        so Recommendations can populate "Next Round to Test".
    """
    out: Dict[str, Any] = {
        "baseline_shaft_id": _safe_str(baseline_shaft_id) if baseline_shaft_id else None,
        "results": [],
        "top_by_goal": {},
        "source": "efficiency_fallback",
    }

    if comparison_df is None or comparison_df.empty:
        # Still include next-round pool if possible
        pool = _build_next_round_pool(
            shafts_df,
            answers=answers,
            baseline_shaft_id=baseline_shaft_id,
            tested_ids=tested_ids,
            max_n=3,
        )
        out["results"] = list(pool)
        if pool:
            out["top_by_goal"] = {"Next Round": pool[0]}
        return out

    df = comparison_df.copy()

    # Ensure expected columns exist
    for c in ["Efficiency", "Confidence", "Carry Δ", "Launch Δ", "Spin Δ", "Dispersion", "Smash", "Shaft", "Shaft ID"]:
        if c not in df.columns:
            df[c] = None

    df["_eff"] = df["Efficiency"].apply(lambda v: _to_float(v, 0.0))
    df["_conf"] = df["Confidence"].apply(lambda v: _to_float(v, 0.0))

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

        if cd is not None and _safe_str(cd):
            reasons.append(f"Carry Δ: {cd}")
        if ld is not None and _safe_str(ld):
            reasons.append(f"Launch Δ: {ld}")
        if sd is not None and _safe_str(sd):
            reasons.append(f"Spin Δ: {sd}")
        if disp is not None and _safe_str(disp):
            reasons.append(f"Dispersion: {disp}")

        overall_score = _to_float(row.get("Efficiency", 0.0), 0.0)

        results.append(
            {
                "shaft_id": sid,
                "shaft_label": label,
                "overall_score": overall_score,
                "reasons": reasons[:3],
                "goal_scores": {"Efficiency": overall_score},
                "raw": row,  # keep raw row for debugging / future engine
            }
        )

    # Append NEXT ROUND pool (untested)
    pool = _build_next_round_pool(
        shafts_df,
        answers=answers,
        baseline_shaft_id=baseline_shaft_id,
        tested_ids=tested_ids,
        max_n=3,
    )

    # Only append truly untested IDs (defensive)
    pool2: List[Dict[str, Any]] = []
    for p in pool:
        sid = _safe_str(p.get("shaft_id", ""))
        if not sid:
            continue
        if sid in tested_ids:
            continue
        pool2.append(p)

    results.extend(pool2)

    out["results"] = results
    if results:
        out["top_by_goal"] = {"Efficiency": results[0]}
        if pool2:
            out["top_by_goal"]["Next Round"] = pool2[0]

    return out


def _write_goal_payloads(
    payload: Dict[str, Any],
    *,
    baseline_shaft_id: Optional[str],
    environment: str,
    answers: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Writes canonical + legacy session payloads for the Recommendations tab.

    Canonical:
      st.session_state.goal_recommendations

    Legacy/back-compat:
      st.session_state.goal_rankings
      st.session_state.goal_recs

    Returns the canonical dict written.
    """
    base_id = _safe_str(baseline_shaft_id) if baseline_shaft_id else None
    q23 = _safe_str(answers.get("Q23", ""))
    q16_intent = _safe_str(answers.get("Q16_2", ""))  # "Higher/Lower/Not sure" intent

    canonical: Dict[str, Any] = dict(payload) if isinstance(payload, dict) else {}
    canonical.setdefault("baseline_shaft_id", base_id)

    canonical["baseline_tag_id"] = base_id
    canonical["environment"] = _safe_str(environment) or "Indoors (Mat)"
    canonical["generated_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    canonical["meta"] = {
        "primary_goal_q23": q23,
        "flight_intent_q16": q16_intent,
        "engine": canonical.get("source", "unknown"),
    }

    st.session_state.goal_recommendations = canonical
    st.session_state.goal_rankings = canonical

    st.session_state.goal_recs = {
        "source": canonical.get("source", "goal_recommendations"),
        "baseline_tag_id": base_id,
        "environment": canonical.get("environment"),
        "generated_at": canonical.get("generated_at"),
        "winner_summary": st.session_state.get("winner_summary", None),
    }

    return canonical


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

    IMPORTANT SIDE EFFECTS:
      - Writes st.session_state.winner_summary
      - Writes st.session_state.goal_recommendations (canonical) + legacy payloads
      - Writes st.session_state.phase6_recs
    """
    out: Dict[str, Any] = {
        "winner": None,
        "winner_summary": None,
        "comparison_df": pd.DataFrame(),
        "goal_rankings": None,
        "goal_recommendations": None,
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

    base_id = _safe_str(baseline_shaft_id) if baseline_shaft_id else None

    comparison_df = build_comparison_table(
        lab_df,
        baseline_shaft_id=base_id,
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

    # ---------------- Tour Proven matrix ----------------
    render_tour_proven_matrix(
        comparison_df,
        baseline_shaft_id=base_id,
        answers=answers,
        environment_override=environment,
    )

    # ---------------- Goal recommendations payload (canonical) ----------------
    shafts_df = _get_shafts_df_for_pool()
    tested_ids = _tested_shaft_ids_from_lab(lab_df)

    fallback_payload = _build_fallback_goal_rankings(
        comparison_df,
        baseline_shaft_id=base_id,
        shafts_df=shafts_df,
        answers=answers,
        tested_ids=tested_ids,
    )

    canonical = _write_goal_payloads(
        fallback_payload,
        baseline_shaft_id=base_id,
        environment=environment,
        answers=answers,
    )

    out["goal_rankings"] = canonical
    out["goal_recommendations"] = canonical

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
