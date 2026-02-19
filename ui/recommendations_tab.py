from __future__ import annotations

from typing import Any, Dict, Optional, List, Set, Tuple

import pandas as pd
import streamlit as st

from utils_pdf import create_pdf_bytes
from utils import send_email_with_pdf

from core.pretest_shortlist import build_pretest_shortlist


# -----------------------------
# Utilities
# -----------------------------
def _safe_str(x: Any) -> str:
    try:
        return str(x).strip()
    except Exception:
        return ""


def _winner_ready() -> bool:
    ws = st.session_state.get("winner_summary", None)
    if isinstance(ws, dict) and (ws.get("shaft_label") or ws.get("explain")):
        return True
    phase6 = st.session_state.get("phase6_recs", None)
    return isinstance(phase6, list) and len(phase6) > 0


def _fmt_pref_line(primary: str, followup: str) -> str:
    p = (primary or "").strip()
    f = (followup or "").strip()
    if not p and not f:
        return ""
    if f:
        return f"{p} → {f}" if p else f
    return p


def _refresh_controls() -> None:
    c1, c2, c3 = st.columns([1, 1, 3])

    if c1.button("🔄 Refresh Recommendations"):
        st.rerun()

    last = st.session_state.get("tm_last_update", "")
    if last:
        c3.caption(f"Last Trackman update: {last}")

    # Event-driven only (no polling)
    auto = c2.checkbox("Auto-refresh", value=True)

    if auto:
        current_v = int(st.session_state.get("tm_data_version", 0) or 0)
        seen_v = int(st.session_state.get("recs_seen_tm_version", -1) or -1)

        if current_v != seen_v:
            st.session_state.recs_seen_tm_version = current_v
            if current_v > 0:
                st.rerun()
        else:
            st.session_state.recs_seen_tm_version = current_v


# -----------------------------
# Goal payload (canonical)
# -----------------------------
def _get_goal_payload() -> Optional[Dict[str, Any]]:
    gr = st.session_state.get("goal_recommendations", None)
    if isinstance(gr, dict) and gr:
        return gr
    gr2 = st.session_state.get("goal_rankings", None)
    if isinstance(gr2, dict) and gr2:
        return gr2
    gr3 = st.session_state.get("goal_recs", None)
    if isinstance(gr3, dict) and gr3:
        return gr3
    return None


def _tested_shaft_ids() -> Set[str]:
    out: Set[str] = set()
    try:
        lab = st.session_state.get("tm_lab_data", None)
        if not isinstance(lab, list) or len(lab) == 0:
            return out
        df = pd.DataFrame(lab)
        if df.empty:
            return out
        if "Shaft ID" in df.columns:
            vals = df["Shaft ID"].astype(str).str.strip()
            out.update([v for v in vals.tolist() if v])
    except Exception:
        return out
    return out


def _result_to_row(r: Any) -> Dict[str, Any]:
    if r is None:
        return {}
    if isinstance(r, dict):
        return {
            "Shaft ID": _safe_str(r.get("shaft_id", "")) or _safe_str(r.get("Shaft ID", "")),
            "Shaft": _safe_str(r.get("shaft_label", "")) or _safe_str(r.get("Shaft", "")),
            "Score": float(r.get("overall_score", r.get("Score", 0.0)) or 0.0),
            "Why": " | ".join([str(x) for x in (r.get("reasons") or [])][:3]) or _safe_str(r.get("Why", "")),
        }
    return {
        "Shaft ID": _safe_str(getattr(r, "shaft_id", "")),
        "Shaft": _safe_str(getattr(r, "shaft_label", "")),
        "Score": float(getattr(r, "overall_score", 0.0) or 0.0),
        "Why": " | ".join([str(x) for x in (getattr(r, "reasons", None) or [])][:3]),
    }


def _goal_best_to_card(best: Any, goal_name: str, baseline_id: Optional[str]) -> None:
    if best is None:
        return

    if isinstance(best, dict):
        lab = _safe_str(best.get("shaft_label", "")) or _safe_str(best.get("Shaft", ""))
        sid = _safe_str(best.get("shaft_id", "")) or _safe_str(best.get("Shaft ID", ""))
        reasons = best.get("reasons") or []
        g_scores = best.get("goal_scores") or {}
    else:
        lab = _safe_str(getattr(best, "shaft_label", ""))
        sid = _safe_str(getattr(best, "shaft_id", ""))
        reasons = getattr(best, "reasons", []) or []
        g_scores = getattr(best, "goal_scores", {}) or {}

    g_val = None
    try:
        if isinstance(g_scores, dict):
            g_val = float(g_scores.get(goal_name, 0.0) or 0.0)
    except Exception:
        g_val = None

    baseline_txt = f"(vs baseline {baseline_id})" if baseline_id else "(vs baseline)"
    st.markdown(f"**{goal_name}** {baseline_txt}")
    st.write(f"**{lab}**  (ID {sid})")
    if g_val is not None:
        st.caption(f"Goal score: {g_val:.2f}")
    if reasons:
        for b in reasons[:3]:
            st.write(f"- {b}")


def _next_round_from_goal_payload(gr: Dict[str, Any], max_n: int = 3) -> List[Dict[str, Any]]:
    baseline_id = _safe_str(gr.get("baseline_shaft_id", "") or "")
    results = gr.get("results", []) or []

    tested = _tested_shaft_ids()
    if baseline_id:
        tested.add(baseline_id)

    out: List[Dict[str, Any]] = []
    for r in results:
        row = _result_to_row(r)
        sid = _safe_str(row.get("Shaft ID", ""))
        if not sid:
            continue
        if sid in tested:
            continue
        out.append(row)
        if len(out) >= max_n:
            break

    return out


# -----------------------------
# Gamer row (pull weight if possible)
# -----------------------------
def _gamer_identity(ans: Dict[str, Any]) -> Tuple[str, str, str]:
    brand = _safe_str(ans.get("Q10", "")).lower()
    model = _safe_str(ans.get("Q12", "")).lower()
    flex = _safe_str(ans.get("Q11", "")).lower()
    return brand, model, flex


def _lookup_gamer_weight(shafts_df: pd.DataFrame, ans: Dict[str, Any]) -> str:
    if not isinstance(shafts_df, pd.DataFrame) or shafts_df.empty:
        return "—"

    b, m, f = _gamer_identity(ans)
    if not b or not m:
        return "—"

    df = shafts_df.copy()
    for c in ["Brand", "Model", "Flex", "Weight (g)"]:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].astype(str).str.strip()

    hit = df[
        (df["Brand"].str.lower() == b)
        & (df["Model"].str.lower() == m)
        & ((df["Flex"].str.lower() == f) if f else True)
    ]

    if hit.empty and f:
        hit = df[(df["Brand"].str.lower() == b) & (df["Model"].str.lower() == m)]

    if hit.empty:
        return "—"

    w = _safe_str(hit.iloc[0].get("Weight (g)", ""))
    return w if w else "—"


def _gamer_row(ans: Dict[str, Any], shafts_df: pd.DataFrame) -> Dict[str, Any]:
    brand = _safe_str(ans.get("Q10", ""))
    model = _safe_str(ans.get("Q12", ""))
    flex = _safe_str(ans.get("Q11", ""))
    label = " ".join([x for x in [brand, model] if x]).strip() or "Current Gamer"
    weight = _lookup_gamer_weight(shafts_df, ans)

    return {
        "ID": "GAMER",
        "Brand": brand or "—",
        "Model": model or label,
        "Flex": flex or "—",
        "Weight (g)": weight,
    }


def _dedupe_shortlist(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    d = df.copy()
    for c in ["ID", "Brand", "Model", "Flex", "Weight (g)"]:
        if c not in d.columns:
            d[c] = ""
        d[c] = d[c].astype(str).str.strip()

    out_rows = []
    seen: Set[str] = set()

    for _, r in d.iterrows():
        rid = _safe_str(r.get("ID", ""))
        key = (
            rid
            if rid and rid.upper() != "GAMER"
            else f"GAMER|{_safe_str(r.get('Brand',''))}|{_safe_str(r.get('Model',''))}|{_safe_str(r.get('Flex',''))}"
        )
        if key in seen:
            continue
        seen.add(key)
        out_rows.append(
            {
                "ID": rid,
                "Brand": _safe_str(r.get("Brand", "")),
                "Model": _safe_str(r.get("Model", "")),
                "Flex": _safe_str(r.get("Flex", "")),
                "Weight (g)": _safe_str(r.get("Weight (g)", "")),
            }
        )

    return pd.DataFrame(out_rows)


def _get_shafts_df_for_ui() -> pd.DataFrame:
    shafts_df = st.session_state.get("shafts_df_for_ui", None)
    if isinstance(shafts_df, pd.DataFrame) and not shafts_df.empty:
        return shafts_df
    shafts_df = st.session_state.get("all_shafts_df", None)
    if isinstance(shafts_df, pd.DataFrame) and not shafts_df.empty:
        return shafts_df
    return pd.DataFrame()


def _fallback_next_round_candidates(
    shafts_df: pd.DataFrame,
    ans: Dict[str, Any],
    max_n: int = 3,
) -> List[Dict[str, Any]]:
    """
    Fallback next-round list when goal payload has no new untested shafts.

    Rules (small + safe):
      1) Start with Stage-1 shortlist IDs from session_state (Shafts!ID).
      2) If those are already tested, widen within the Shafts sheet:
         - same Brand+Model family as gamer
         - then same Brand, closest weight to gamer (if gamer weight available)
      3) Always filter out anything already logged in TrackMan Lab and baseline.
    """
    if not isinstance(shafts_df, pd.DataFrame) or shafts_df.empty:
        return []

    tested = _tested_shaft_ids()

    baseline_id = _safe_str(st.session_state.get("baseline_tag_id", "") or "")
    if baseline_id:
        tested.add(baseline_id)

    # Normalize Shafts df
    df = shafts_df.copy()
    for c in ["ID", "Brand", "Model", "Flex", "Weight (g)"]:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].astype(str).str.strip()

    # Stage-1 shortlist IDs (best first)
    seed_ids: List[str] = []
    pre = st.session_state.get("pretest_shortlist_df", None)
    if isinstance(pre, pd.DataFrame) and not pre.empty and "ID" in pre.columns:
        seed_ids = [str(x).strip() for x in pre["ID"].tolist() if str(x).strip()]

    # Remove tested/baseline
    seed_ids = [sid for sid in seed_ids if sid not in tested]

    def _row_for_id(sid: str) -> Optional[Dict[str, Any]]:
        hit = df[df["ID"] == str(sid)]
        if hit.empty:
            return None
        r = hit.iloc[0]
        label = " ".join([x for x in [r.get("Brand", ""), r.get("Model", ""), r.get("Flex", "")] if str(x).strip()])
        return {
            "Shaft ID": str(r.get("ID", "")).strip(),
            "Shaft": label.strip(),
            "Score": 0.0,
            "Why": "Stage-1 shortlist candidate (untested)",
        }

    out: List[Dict[str, Any]] = []
    for sid in seed_ids:
        rr = _row_for_id(sid)
        if rr and rr.get("Shaft ID"):
            out.append(rr)
        if len(out) >= max_n:
