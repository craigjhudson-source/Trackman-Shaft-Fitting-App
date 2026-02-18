# ui/trackman_tab.py
from __future__ import annotations

import datetime
from typing import Dict, Any, Optional, List

import pandas as pd
import streamlit as st

from core.trackman import load_trackman, summarize_trackman, debug_trackman
from core.trackman_display import render_trackman_session

UI_INTEL_AVAILABLE = True
try:
    from ui.intelligence import render_intelligence_block
except Exception:
    UI_INTEL_AVAILABLE = False


def _ensure_lab_controls() -> None:
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


def _ensure_persistence_defaults() -> None:
    st.session_state.setdefault("tm_preview_df", None)
    st.session_state.setdefault("tm_preview_name", None)
    st.session_state.setdefault("tm_preview_time", None)

    # legacy mirrors
    st.session_state.setdefault("tm_last_preview_df", None)
    st.session_state.setdefault("tm_last_preview_name", None)
    st.session_state.setdefault("tm_last_preview_time", None)

    st.session_state.setdefault("tm_data_version", 0)
    st.session_state.setdefault("tm_lab_data", [])
    st.session_state.setdefault("answers", {})
    st.session_state.setdefault("environment", "Indoors (Mat)")

    st.session_state.setdefault("goal_recommendations", None)
    st.session_state.setdefault("goal_recs", None)
    st.session_state.setdefault("phase6_recs", None)
    st.session_state.setdefault("winner_summary", None)


def _controls_complete() -> bool:
    _ensure_lab_controls()
    return all(bool(v) for v in st.session_state.lab_controls.values())


def _bump_tm_refresh() -> None:
    try:
        st.session_state.tm_data_version = int(st.session_state.get("tm_data_version", 0)) + 1
    except Exception:
        st.session_state.tm_data_version = 1
    st.session_state.tm_last_update = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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

    def _norm(x: Any) -> str:
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


def _extract_winner_summary(intel: Any) -> Optional[Dict[str, Any]]:
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
            if v is None:
                continue
            if isinstance(v, (pd.DataFrame, pd.Series)) and len(v) == 0:
                continue
            if isinstance(v, (list, dict, str)) and not v:
                continue
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


def _persist_preview(df: pd.DataFrame, name: str) -> None:
    """
    ✅ FIXED: previously this function got truncated during paste and caused SyntaxError.
    Persist preview into canonical keys + legacy mirrors.
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    st.session_state.tm_preview_df = df
    st.session_state.tm_preview_name = name
    st.session_state.tm_preview_time = ts

    # legacy mirrors (in case any older UI reads these)
    st.session_state.tm_last_preview_df = df
    st.session_state.tm_last_preview_name = name
    st.session_state.tm_last_preview_time = ts


def render_trackman_tab(
    *,
    all_data: Dict[str, pd.DataFrame],
    answers: Dict[str, Any],
    all_winners: Dict[str, pd.DataFrame],
    MIN_SHOTS: int,
    WARN_FACE_TO_PATH_SD: float,
    WARN_CARRY_SD: float,
    WARN_SMASH_SD: float,
) -> None:
    _ensure_lab_controls()
    _ensure_persistence_defaults()

    st.header("🧪 Trackman Lab (Controlled Testing)")

    st.caption(
        f"Quality signals (not enforced): "
        f"MIN_SHOTS={MIN_SHOTS} | "
        f"WARN_FACE_TO_PATH_SD={WARN_FACE_TO_PATH_SD} | "
        f"WARN_CARRY_SD={WARN_CARRY_SD} | "
        f"WARN_SMASH_SD={WARN_SMASH_SD}"
    )

    env_choice = st.radio(
        "Testing environment",
        ["Indoors (Mat)", "Outdoors (Turf)"],
        horizontal=True,
        index=0 if st.session_state.environment == "Indoors (Mat)" else 1,
    )
    st.session_state.environment = env_choice
    st.session_state.answers["Q22"] = env_choice

    with st.expander("✅ Lab Controls (required before logging)", expanded=True):
        st.session_state.lab_controls["length_matched"] = st.checkbox(
            "Length matched (same playing length)",
            value=st.session_state.lab_controls["length_matched"],
        )
        st.session_state.lab_controls["swing_weight_matched"] = st.checkbox(
            "Swing weight matched",
            value=st.session_state.lab_controls["swing_weight_matched"],
        )
        st.session_state.lab_controls["grip_matched"] = st.checkbox(
            "Grip matched",
            value=st.session_state.lab_controls["grip_matched"],
        )
        st.session_state.lab_controls["same_head"] = st.checkbox(
            "Same head used",
            value=st.session_state.lab_controls["same_head"],
        )
        st.session_state.lab_controls["same_ball"] = st.checkbox(
            "Same ball used",
            value=st.session_state.lab_controls["same_ball"],
        )

    if _controls_complete():
        st.success("Controls confirmed. Logged data will be marked as controlled.")
    else:
        st.warning("Complete all controls before logging data (prevents bad correlation).")

    c_up, c_res = st.columns([1, 2])

    with c_up:
        shaft_map = _shaft_label_map(all_data["Shafts"])

        # Your existing behavior (default assign)
        test_list = ["Current Baseline"] + [
            all_winners[k].iloc[0]["Model"]
            for k in all_winners
            if not all_winners[k].empty
        ]
        selected_s = st.selectbox("Default Assign (if no Tags in file):", test_list, index=0)

        tm_file = st.file_uploader("Upload Trackman CSV/Excel/PDF", type=["csv", "xlsx", "pdf"])

        can_log = tm_file is not None and _controls_complete()
        raw_preview: Optional[pd.DataFrame] = None

        if tm_file is not None:
            name = getattr(tm_file, "name", "") or ""
            if name.lower().endswith(".pdf"):
                st.info("PDF uploaded (accepted but not parsed). Export as CSV/XLSX for analysis.")
            else:
                raw_preview, _ = _process_trackman_file(tm_file, selected_s)
                if raw_preview is not None and not raw_preview.empty:
                    _persist_preview(raw_preview, name)

        # If uploader is empty (tab switch), show persisted preview
        if tm_file is None and st.session_state.tm_preview_df is not None:
            st.subheader("Last Preview (Persisted)")
            st.caption(
                f"{st.session_state.tm_preview_name or 'Previous Upload'} "
                f"• {st.session_state.tm_preview_time or ''}"
            )
            render_trackman_session(st.session_state.tm_preview_df)
            st.info("Upload the file again to log it to the lab. (Preview persists for reference.)")

        if tm_file is not None and raw_preview is None:
            st.error("Could not parse TrackMan file for preview. Showing debug below.")
            with st.expander("🔎 TrackMan Debug (columns + preview)", expanded=True):
                dbg = debug_trackman(tm_file)
                if not dbg.get("ok"):
                    st.error(f"Debug failed: {dbg.get('error')}")
                else:
                    st.write(f"Rows after cleanup: {dbg.get('rows_after_cleanup')}")
                    st.write("Detected columns (first 200):")
                    st.code("\n".join(dbg.get("columns", [])))
                    prev = dbg.get("head_preview")
                    if isinstance(prev, pd.DataFrame):
                        st.dataframe(prev, use_container_width=True)

        elif raw_preview is not None:
            render_trackman_session(raw_preview)

            tag_ids = _extract_tag_ids(raw_preview)
            if tag_ids:
                st.markdown("## Shaft selection from TrackMan Tags")
                tag_options = [shaft_map.get(tid, f"Unknown Shaft (ID {tid})") for tid in tag_ids]

                selected_labels = st.multiselect(
                    "Select which shafts were hit in this upload:",
                    options=tag_options,
                    default=tag_options,
                    key="tag_selected_labels",
                )

                label_to_id = {shaft_map.get(tid, f"Unknown Shaft (ID {tid})"): tid for tid in tag_ids}
                st.session_state["selected_tag_ids"] = [label_to_id[x] for x in selected_labels if x in label_to_id]
            else:
                st.session_state["selected_tag_ids"] = []

        if st.button("➕ Add") and can_log:
            name = getattr(tm_file, "name", "") or ""
            if name.lower().endswith(".pdf"):
                st.warning(
                    "PDF uploads are accepted, but **not parsed**.\n\n"
                    "Please export TrackMan as **CSV or XLSX** for analysis."
                )
            else:
                raw, _ = _process_trackman_file(tm_file, selected_s)
                if raw is None or raw.empty:
                    st.error("Could not parse TrackMan file (no required metrics found).")
                else:
                    # Minimal add behavior preserved from your previous version:
                    stat = summarize_trackman(raw, selected_s, include_std=True)
                    stat["Shaft ID"] = str(selected_s)
                    stat["Shaft Label"] = str(selected_s)
                    stat["Controlled"] = "Yes"
                    stat["Environment"] = st.session_state.environment
                    stat["Timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    st.session_state.tm_lab_data.append(stat)

                    _bump_tm_refresh()
                    st.rerun()

        if tm_file is not None and not _controls_complete():
            st.info("Finish Lab Controls above to enable logging.")

    # ---------- Results / Intelligence ----------
    with c_res:
        if not st.session_state.tm_lab_data:
            st.info("Upload files to begin correlation.")
            return

        lab_df = pd.DataFrame(st.session_state.tm_lab_data)
        st.dataframe(lab_df, use_container_width=True, hide_index=True, height=420)

        st.divider()

        if not UI_INTEL_AVAILABLE:
            st.error("Intelligence module not available (ui/intelligence.py import failed).")
            return

        intel = render_intelligence_block(
            lab_df=lab_df,
            baseline_shaft_id=None,
            answers=st.session_state.answers,
            environment=st.session_state.environment,
            MIN_SHOTS=MIN_SHOTS,
            WARN_FACE_TO_PATH_SD=WARN_FACE_TO_PATH_SD,
            WARN_CARRY_SD=WARN_CARRY_SD,
            WARN_SMASH_SD=WARN_SMASH_SD,
        )

        if isinstance(intel, dict):
            if intel.get("phase6_recs"):
                st.session_state.phase6_recs = intel["phase6_recs"]

            # Canonical goal recommendations output
            if intel.get("goal_recommendations") is not None:
                st.session_state.goal_recommendations = intel.get("goal_recommendations")
                st.session_state.goal_recs = st.session_state.goal_recommendations  # legacy mirror
            elif intel.get("goal_recs") is not None:
                st.session_state.goal_recommendations = intel.get("goal_recs")
                st.session_state.goal_recs = intel.get("goal_recs")

            ws = _extract_winner_summary(intel)
            if ws:
                st.session_state.winner_summary = ws

                if st.session_state.get("goal_recommendations") is None:
                    payload = {
                        "source": "trackman_intelligence",
                        "winner_summary": ws,
                        "environment": st.session_state.get("environment"),
                        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    st.session_state.goal_recommendations = payload
                    st.session_state.goal_recs = payload
