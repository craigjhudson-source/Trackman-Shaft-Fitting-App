# ui/trackman_tab.py
from __future__ import annotations

import datetime
from typing import Dict, Any, Optional, List

import pandas as pd
import streamlit as st

from core.trackman import load_trackman, summarize_trackman, debug_trackman
from core.trackman_display import render_trackman_session

# Intelligence block is optional but expected in your repo
UI_INTEL_AVAILABLE = True
try:
    from ui.intelligence import render_intelligence_block
except Exception:
    UI_INTEL_AVAILABLE = False


def _ensure_lab_controls() -> None:
    """
    Defensive init so Trackman tab never depends on app.py session defaults.
    """
    if "lab_controls" not in st.session_state or not isinstance(st.session_state.get("lab_controls"), dict):
        st.session_state.lab_controls = {
            "length_matched": False,
            "swing_weight_matched": False,
            "grip_matched": False,
            "same_head": False,
            "same_ball": False,
        }
    else:
        for k, v in {
            "length_matched": False,
            "swing_weight_matched": False,
            "grip_matched": False,
            "same_head": False,
            "same_ball": False,
        }.items():
            st.session_state.lab_controls.setdefault(k, v)


def _ensure_preview_persistence_defaults() -> None:
    """
    Persist preview across reruns/tab switching.

    NEW canonical keys:
      - tm_preview_df
      - tm_preview_name
      - tm_preview_time

    Legacy keys (kept for backward compatibility):
      - tm_last_preview_df
      - tm_last_preview_name
      - tm_last_preview_time
    """
    st.session_state.setdefault("tm_preview_df", None)
    st.session_state.setdefault("tm_preview_name", None)
    st.session_state.setdefault("tm_preview_time", None)

    # Legacy mirrors
    st.session_state.setdefault("tm_last_preview_df", None)
    st.session_state.setdefault("tm_last_preview_name", None)
    st.session_state.setdefault("tm_last_preview_time", None)


def _ensure_core_state_defaults() -> None:
    """
    Ensure common keys exist even if app.py didn't initialize them.
    """
    st.session_state.setdefault("environment", "Indoors (Mat)")
    st.session_state.setdefault("answers", {})
    st.session_state.setdefault("tm_lab_data", [])
    st.session_state.setdefault("tm_data_version", 0)

    # NEW canonical recommendation output key
    st.session_state.setdefault("goal_recommendations", None)

    # Legacy key (some UI may still read this)
    st.session_state.setdefault("goal_recs", None)

    st.session_state.setdefault("phase6_recs", None)
    st.session_state.setdefault("winner_summary", None)


def _bump_tm_refresh() -> None:
    """
    Signals that Trackman lab data changed so other tabs can refresh.
    """
    try:
        st.session_state.tm_data_version = int(st.session_state.get("tm_data_version", 0)) + 1
    except Exception:
        st.session_state.tm_data_version = 1

    st.session_state.tm_last_update = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _controls_complete() -> bool:
    _ensure_lab_controls()
    return all(bool(v) for v in st.session_state.lab_controls.values())


def _extract_tag_ids(raw_df: pd.DataFrame) -> List[str]:
    if raw_df is None or raw_df.empty or "Tags" not in raw_df.columns:
        return []
    s = raw_df["Tags"].astype(str).str.strip()
    s = s[s != ""]
    cleaned: List[str] = []
    for v in s.unique().tolist():
        try:
            fv = float(v)
            cleaned.append(str(int(fv)) if fv.is_integer() else str(v))
        except Exception:
            cleaned.append(str(v))
    cleaned = list(dict.fromkeys(cleaned))
    return sorted(cleaned)


def _shaft_label_map(shafts_df: pd.DataFrame) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if shafts_df is None or shafts_df.empty:
        return out

    df = shafts_df.copy()
    for c in ["ID", "Brand", "Model", "Flex", "Weight (g)", "Weight"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()

    for _, r in df.iterrows():
        sid = str(r.get("ID", "")).strip()
        if not sid:
            continue
        brand = str(r.get("Brand", "")).strip()
        model = str(r.get("Model", "")).strip()
        flex = str(r.get("Flex", "")).strip()
        wt = str(r.get("Weight (g)", "")).strip()
        if not wt:
            wt = str(r.get("Weight", "")).strip()

        label = " | ".join([x for x in [brand, model, flex] if x])
        if wt:
            label = f"{label} | {wt}g"
        out[sid] = f"{label} (ID {sid})"

    return out


def _filter_by_tag(raw_df: pd.DataFrame, tag_id: str) -> pd.DataFrame:
    if raw_df is None or raw_df.empty or "Tags" not in raw_df.columns:
        return pd.DataFrame()

    s = raw_df["Tags"].astype(str).str.strip()

    def _norm(x):
        try:
            fx = float(str(x))
            return str(int(fx)) if fx.is_integer() else str(x)
        except Exception:
            return str(x)

    s_norm = s.apply(_norm)
    return raw_df.loc[s_norm == str(tag_id)].copy()


def _process_trackman_file(uploaded_file, shaft_id):
    """
    Returns (raw_df, stat_dict) on success, (None, None) on failure.
    """
    try:
        name = getattr(uploaded_file, "name", "") or ""
        if name.lower().endswith(".pdf"):
            return None, None

        raw = load_trackman(uploaded_file)

        if hasattr(raw, "columns"):
            raw = raw.loc[:, ~raw.columns.duplicated()].copy()

        stat = summarize_trackman(raw, shaft_id, include_std=True)

        required_any = any(
            k in stat for k in ["Club Speed", "Ball Speed", "Smash Factor", "Carry", "Spin Rate"]
        )
        if not required_any:
            return None, None

        return raw, stat
    except Exception:
        return None, None


def _find_baseline_shaft_id_from_answers(ans: Dict[str, Any], shafts_df: pd.DataFrame) -> Optional[str]:
    """
    Attempts to match the interview's current/gamer shaft answers to Shafts sheet.
    Assumes:
      Q10 = Brand, Q11 = Flex, Q12 = Model
    Returns Shafts.ID as string, or None.
    """
    if shafts_df is None or shafts_df.empty:
        return None

    current_brand = str(ans.get("Q10", "")).strip()
    current_flex = str(ans.get("Q11", "")).strip()
    current_model = str(ans.get("Q12", "")).strip()

    if not (current_brand and current_model):
        return None

    df = shafts_df.copy()
    for c in ["ID", "Brand", "Model", "Flex"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()

    if "Brand" not in df.columns or "Model" not in df.columns or "ID" not in df.columns:
        return None

    m = (df["Brand"].str.lower() == current_brand.lower()) & (df["Model"].str.lower() == current_model.lower())
    if current_flex and "Flex" in df.columns:
        m = m & (df["Flex"].str.lower() == current_flex.lower())

    hit = df[m]
    if len(hit) >= 1:
        return str(hit.iloc[0]["ID"]).strip()

    m2 = (df["Brand"].str.lower() == current_brand.lower()) & (df["Model"].str.lower() == current_model.lower())
    hit2 = df[m2]
    if len(hit2) >= 1:
        return str(hit2.iloc[0]["ID"]).strip()

    return None


def _extract_winner_summary(intel: Any) -> Optional[Dict[str, Any]]:
    """
    Try to standardize winner info out of whatever the intelligence layer returns,
    without assuming a single fixed key.

    Handles cases where `intel` is a dict-like OR a pandas object returned by mistake.
    """
    if not isinstance(intel, dict):
        return None

    candidates = [
        "winner_summary",
        "highlighted_pick",
        "highlight_pick",
        "winner",
        "decision",
        "tour_proven_pick",
        "best_alternative",
    ]

    raw = None
    for k in candidates:
        if k in intel:
            v = intel.get(k, None)
            # Avoid pandas truthiness ValueError
            if v is None:
                continue
            if isinstance(v, (pd.DataFrame, pd.Series)):
                if len(v) == 0:
                    continue
                raw = v
                break
            if isinstance(v, (list, dict, str)) and v:
                raw = v
                break

    if isinstance(raw, dict):
        return {
            "shaft_id": raw.get("shaft_id") or raw.get("Shaft ID") or raw.get("id"),
            "shaft_label": raw.get("shaft_label") or raw.get("Shaft") or raw.get("label"),
            "headline": raw.get("headline") or raw.get("title") or "Winner selected",
            "explain": raw.get("explain") or raw.get("reason") or raw.get("message"),
            "raw": raw,
        }

    if isinstance(raw, str) and raw.strip():
        return {
            "shaft_id": None,
            "shaft_label": None,
            "headline": "Winner selected",
            "explain": raw.strip(),
            "raw": raw,
        }

    return None


def _persist_preview(df: pd.DataFrame, name: st
