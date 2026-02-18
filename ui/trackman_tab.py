from __future__ import annotations

import datetime
from typing import Dict, Any, Optional, List

import pandas as pd
import streamlit as st

from core.trackman import load_trackman, summarize_trackman, debug_trackman
from core.trackman_display import render_trackman_session
from core.pretest_shortlist import build_pretest_shortlist

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


def _ensure_preview_persistence_defaults() -> None:
    st.session_state.setdefault("tm_last_preview_df", None)
    st.session_state.setdefault("tm_last_preview_name", None)
    st.session_state.setdefault("tm_last_preview_time", None)


def _bump_tm_refresh() -> None:
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


def _process_trackman_file(uploaded_file, shaft_id: str):
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

        # IMPORTANT: pass real shaft_id (Shafts!ID)
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
    Attempts to match the interview's current/gamer answers to Shafts sheet.
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


def render_trackman_tab(
    *,
    all_data: Dict[str, pd.DataFrame],
    answers: Dict[str, Any],
    all_winners: Dict[str, pd.DataFrame],  # kept but no longer used for ID mapping
    MIN_SHOTS: int,
    WARN_FACE_TO_PATH_SD: float,
    WARN_CARRY_SD: float,
    WARN_SMASH_SD: float,
) -> None:
    _ensure_lab_controls()
    _ensure_preview_persistence_defaults()

    st.session_state.setdefault("environment", "Indoors (Mat)")
    st.session_state.setdefault("answers", {})
    st.session_state.setdefault("tm_lab_data", [])
    st.session_state.setdefault("goal_recs", None)

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
        shafts_df = all_data.get("Shafts", pd.DataFrame())
        shaft_map = _shaft_label_map(shafts_df)

        baseline_id = _find_baseline_shaft_id_from_answers(answers, shafts_df)
        baseline_label = shaft_map.get(str(baseline_id), "Current Baseline") if baseline_id else "Current Baseline"

        # NEW: default assign list from interview-driven pretest shortlist (real IDs)
        pretest = build_pretest_shortlist(shafts_df, answers, n=3)
        pretest_ids = []
        if isinstance(pretest, pd.DataFrame) and not pretest.empty and "ID" in pretest.columns:
            pretest_ids = [str(x).strip() for x in pretest["ID"].tolist() if str(x).strip()]

        options_labels = [baseline_label]
        label_to_id: Dict[str, str] = {}

        if baseline_id:
            label_to_id[baseline_label] = str(baseline_id)

        for sid in pretest_ids:
            lab = shaft_map.get(str(sid), f"Unknown Shaft (ID {sid})")
            if lab not in options_labels:
                options_labels.append(lab)
            label_to_id[lab] = str(sid)

        selected_label = st.selectbox("Default Assign (if no Tags in file):", options_labels, index=0)
        selected_default_id = label_to_id.get(selected_label, str(baseline_id) if baseline_id else "BASELINE")

        tm_file = st.file_uploader(
            "Upload Trackman CSV/Excel/PDF",
            type=["csv", "xlsx", "pdf"],
        )

        can_log = tm_file is not None and _controls_complete()
        raw_preview = None

        if tm_file is not None:
            name = getattr(tm_file, "name", "") or ""
            if name.lower().endswith(".pdf"):
                st.info("PDF uploaded (accepted but not parsed). Export as CSV/XLSX for analysis.")
            else:
                raw_preview, _ = _process_trackman_file(tm_file, selected_default_id)

                if raw_preview is not None and not raw_preview.empty:
                    st.session_state.tm_last_preview_df = raw_preview
                    st.session_state.tm_last_preview_name = name
                    st.session_state.tm_last_preview_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if tm_file is None and st.session_state.tm_last_preview_df is not None:
            st.subheader("Last Preview (Persisted)")
            st.caption(
                f"{st.session_state.tm_last_preview_name or 'Previous Upload'} "
                f"• {st.session_state.tm_last_preview_time or ''}"
            )
            render_trackman_session(st.session_state.tm_last_preview_df)
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
                        prev = prev.copy()
                        prev.columns = [str(c) for c in prev.columns]
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

                label_to_id2 = {shaft_map.get(tid, f"Unknown Shaft (ID {tid})"): tid for tid in tag_ids}
                st.session_state["selected_tag_ids"] = [label_to_id2[x] for x in selected_labels if x in label_to_id2]

                selected_tag_ids = st.session_state.get("selected_tag_ids", [])
                baseline_default_id = None
                if baseline_id and str(baseline_id) in selected_tag_ids:
                    baseline_default_id = str(baseline_id)
                elif selected_tag_ids:
                    baseline_default_id = str(selected_tag_ids[0])

                if selected_tag_ids:
                    baseline_options = [shaft_map.get(str(tid), f"Unknown Shaft (ID {tid})") for tid in selected_tag_ids]
                    label_to_id_selected = {
                        shaft_map.get(str(tid), f"Unknown Shaft (ID {tid})"): str(tid) for tid in selected_tag_ids
                    }
                    default_label = shaft_map.get(str(baseline_default_id), baseline_options[0])

                    st.markdown("### Baseline for comparison")
                    st.caption("Used for deltas, confidence scoring, and optimizer comparisons.")

                    picked_label = st.selectbox(
                        "Select the baseline shaft (usually the gamer):",
                        options=baseline_options,
                        index=baseline_options.index(default_label) if default_label in baseline_options else 0,
                        key="baseline_tag_label",
                    )
                    st.session_state["baseline_tag_id"] = label_to_id_selected.get(picked_label, baseline_default_id)
                else:
                    st.session_state["baseline_tag_id"] = None

                st.markdown("## Split session by shaft (Tags)")
                for sid in selected_tag_ids:
                    sub = _filter_by_tag(raw_preview, sid)
                    label = shaft_map.get(str(sid), f"Unknown Shaft (ID {sid})")
                    with st.expander(label, expanded=False):
                        if sub is None or sub.empty:
                            st.warning("No shots found for this Tag.")
                        else:
                            render_trackman_session(sub)
                            st.caption(f"Shots in this group: {len(sub)}")
            else:
                st.session_state["selected_tag_ids"] = []
                st.session_state["baseline_tag_id"] = None

        if st.button("➕ Add") and can_log:
            name = getattr(tm_file, "name", "") or ""
            if name.lower().endswith(".pdf"):
                st.warning(
                    "PDF uploads are accepted, but **not parsed**.\n\n"
                    "Please export TrackMan as **CSV or XLSX** for analysis."
                )
            else:
                raw, _ = _process_trackman_file(tm_file, selected_default_id)
                if raw is None or raw.empty:
                    st.error("Could not parse TrackMan file (no required metrics found).")
                else:
                    selected_tag_ids = st.session_state.get("selected_tag_ids", [])
                    if "Tags" in raw.columns and selected_tag_ids:
                        logged_any = False
                        for sid in selected_tag_ids:
                            sub = _filter_by_tag(raw, sid)
                            if sub is None or sub.empty:
                                continue

                            stat = summarize_trackman(sub, str(sid), include_std=True)
                            stat["Shaft ID"] = str(sid)
                            stat["Shaft Label"] = shaft_map.get(str(sid), f"Unknown (ID {sid})")
                            stat["Controlled"] = "Yes"
                            stat["Environment"] = st.session_state.environment
                            stat["Timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            stat["Baseline Tag"] = st.session_state.get("baseline_tag_id", None)

                            st.session_state.tm_lab_data.append(stat)
                            logged_any = True

                        if not logged_any:
                            st.error("No shots matched the selected Tag IDs.")
                        else:
                            _bump_tm_refresh()
                            st.rerun()
                    else:
                        stat = summarize_trackman(raw, str(selected_default_id), include_std=True)
                        stat["Shaft ID"] = str(selected_default_id)
                        stat["Shaft Label"] = shaft_map.get(str(selected_default_id), str(selected_label))
                        stat["Controlled"] = "Yes"
                        stat["Environment"] = st.session_state.environment
                        stat["Timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        stat["Baseline Tag"] = None
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

        preferred_cols = [
            "Timestamp",
            "Shaft ID",
            "Shaft Label",
            "Baseline Tag",
            "Controlled",
            "Environment",
            "Shot Count",
            "Club Speed",
            "Ball Speed",
            "Smash Factor",
            "Carry",
            "Spin Rate",
            "Launch Angle",
            "Landing Angle",
            "Face To Path",
            "Dynamic Lie",
            "Carry Side",
            "Total Side",
            "Club Speed SD",
            "Ball Speed SD",
            "Smash Factor SD",
            "Carry SD",
            "Spin Rate SD",
            "Face To Path SD",
            "Dynamic Lie SD",
        ]
        show_cols = [c for c in preferred_cols if c in lab_df.columns] + [c for c in lab_df.columns if c not in preferred_cols]
        st.dataframe(lab_df[show_cols], use_container_width=True, hide_index=True, height=420)

        st.divider()

        baseline_shaft_id = st.session_state.get("baseline_tag_id", None)

        if not UI_INTEL_AVAILABLE:
            st.error("Intelligence module not available (ui/intelligence.py import failed).")
            return

        intel = render_intelligence_block(
            lab_df=lab_df,
            baseline_shaft_id=str(baseline_shaft_id) if baseline_shaft_id else None,
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

            if "goal_recs" in intel and intel.get("goal_recs") is not None:
                st.session_state.goal_recs = intel.get("goal_recs")

            ws = _extract_winner_summary(intel)
            if ws:
                st.session_state.winner_summary = ws

                if st.session_state.get("goal_recs") is None:
                    st.session_state.goal_recs = {
                        "source": "trackman_intelligence",
                        "winner_summary": ws,
                        "baseline_tag_id": st.session_state.get("baseline_tag_id"),
                        "environment": st.session_state.get("environment"),
                        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
            else:
                st.session_state.setdefault("winner_summary", None)
                st.session_state.setdefault("goal_recs", None)
