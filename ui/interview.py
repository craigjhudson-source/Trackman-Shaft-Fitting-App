# ui/interview.py
from __future__ import annotations

from typing import Any, Dict, List, Callable

import pandas as pd
import streamlit as st


def _norm_qid(qid: Any) -> str:
    """
    Normalize QuestionID so we never lose answers due to Q16.1 vs Q16_1.
    We store everything as underscore form: Q16_1, Q19_2, etc.
    """
    s = "" if qid is None else str(qid).strip()
    return s.replace(".", "_")


def _sync_all() -> None:
    # Persist all widget_* values into the single source of truth answers dict.
    for key in list(st.session_state.keys()):
        if key.startswith("widget_"):
            qid = key.replace("widget_", "")
            st.session_state.answers[qid] = st.session_state[key]


def should_show_question(qid: str, answers: Dict[str, Any]) -> bool:
    """
    Visibility logic for follow-ups.
    Uses normalized IDs only (underscore form).

    Correct sheet-driven rules:
      - Q16_3 shows only when Q16_2 is No/Unsure
      - Q19_3 shows only when Q19_2 is No/Unsure
    """
    qid = _norm_qid(qid)

    # Flight: "If not, do you want it higher or lower?" depends on "Are you happy...?"
    if qid == "Q16_3":
        a = str(answers.get("Q16_2", "")).strip().lower()
        return a in {"no", "unsure"}

    # Feel: "If not, what do you want it to feel like?" depends on "Are you happy...?"
    if qid == "Q19_3":
        a = str(answers.get("Q19_2", "")).strip().lower()
        return a in {"no", "unsure"}

    return True


def render_interview(
    *,
    all_data: Dict[str, pd.DataFrame],
    q_master: pd.DataFrame,
    categories: List[str],
    save_to_fittings_fn: Callable[[Dict[str, Any]], None],
) -> None:
    st.title("⛳ Tour Proven Fitting Interview")

    # Current category step
    current_cat = categories[st.session_state.form_step]
    q_df = q_master[q_master["Category"].astype(str) == str(current_cat)]

    for _, row in q_df.iterrows():
        qid_raw = row.get("QuestionID", "")
        qid = _norm_qid(qid_raw)
        if not qid:
            continue

        # Ensure session answers dict always uses normalized keys
        if qid not in st.session_state.answers:
            st.session_state.answers[qid] = st.session_state.answers.get(str(qid_raw).strip(), "")

        if not should_show_question(qid, st.session_state.answers):
            continue

        qtext = str(row.get("QuestionText", "")).strip()
        qtype = str(row.get("InputType", "")).strip()
        qopts = str(row.get("Options", "")).strip()
        ans_val = st.session_state.answers.get(qid, "")

        if qtype == "Dropdown":
            opts: List[str] = [""]

            # Heads dynamic dropdowns
            if "Heads" in qopts:
                brand_val = st.session_state.answers.get("Q08", "")

                if "Brand" in qtext:
                    if "Manufacturer" in all_data["Heads"].columns:
                        opts += sorted(all_data["Heads"]["Manufacturer"].dropna().unique().tolist())
                    else:
                        opts += sorted(all_data["Heads"].iloc[:, 0].dropna().unique().tolist())
                else:
                    if "Manufacturer" in all_data["Heads"].columns and "Model" in all_data["Heads"].columns:
                        if brand_val:
                            opts += sorted(
                                all_data["Heads"][all_data["Heads"]["Manufacturer"] == brand_val]["Model"]
                                .dropna()
                                .unique()
                                .tolist()
                            )
                        else:
                            opts += ["Select Brand First"]
                    else:
                        opts += ["Select Brand First"]

            # Shafts dynamic dropdowns
            elif "Shafts" in qopts:
                s_brand = st.session_state.answers.get("Q10", "")
                s_flex = st.session_state.answers.get("Q11", "")

                if "Brand" in qtext:
                    if "Brand" in all_data["Shafts"].columns:
                        opts += sorted(all_data["Shafts"]["Brand"].dropna().unique().tolist())

                elif "Flex" in qtext:
                    if s_brand and "Flex" in all_data["Shafts"].columns and "Brand" in all_data["Shafts"].columns:
                        opts += sorted(
                            all_data["Shafts"][all_data["Shafts"]["Brand"] == s_brand]["Flex"]
                            .dropna()
                            .unique()
                            .tolist()
                        )
                    else:
                        opts += ["Select Brand First"]

                elif "Model" in qtext:
                    if (
                        s_brand
                        and s_flex
                        and "Brand" in all_data["Shafts"].columns
                        and "Flex" in all_data["Shafts"].columns
                        and "Model" in all_data["Shafts"].columns
                    ):
                        opts += sorted(
                            all_data["Shafts"][
                                (all_data["Shafts"]["Brand"] == s_brand) & (all_data["Shafts"]["Flex"] == s_flex)
                            ]["Model"]
                            .dropna()
                            .unique()
                            .tolist()
                        )
                    else:
                        opts += ["Select Brand/Flex First"]

            # Config-driven dropdowns
            elif qopts.lower().startswith("config:"):
                col = qopts.split(":", 1)[1].strip()
                if col in all_data["Config"].columns:
                    opts += [str(x).strip() for x in all_data["Config"][col].dropna().tolist() if str(x).strip()]

            # Responses fallback (if you still have it)
            else:
                resp_df = all_data.get("Responses", pd.DataFrame())
                if (
                    resp_df is not None
                    and not resp_df.empty
                    and "QuestionID" in resp_df.columns
                    and "ResponseOption" in resp_df.columns
                ):
                    opts += (
                        resp_df[resp_df["QuestionID"].astype(str).str.strip().apply(_norm_qid) == qid]["ResponseOption"]
                        .astype(str)
                        .tolist()
                    )

            opts = list(dict.fromkeys([str(x) for x in opts if str(x).strip() != ""]))

            st.selectbox(
                qtext,
                opts,
                index=opts.index(str(ans_val)) if str(ans_val) in opts else 0,
                key=f"widget_{qid}",
                on_change=_sync_all,
            )

        elif qtype == "Numeric":
            try:
                v = float(ans_val) if str(ans_val).strip() else 0.0
            except Exception:
                v = 0.0
            st.number_input(qtext, value=v, key=f"widget_{qid}", on_change=_sync_all)

        else:
            st.text_input(qtext, value=str(ans_val), key=f"widget_{qid}", on_change=_sync_all)

    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button("⬅️ Back") and st.session_state.form_step > 0:
        _sync_all()
        st.session_state.form_step -= 1
        st.rerun()

    if st.session_state.form_step < len(categories) - 1:
        if c2.button("Next ➡️"):
            _sync_all()
            st.session_state.form_step += 1
            st.rerun()
    else:
        if c2.button("🔥 Calculate"):
            _sync_all()

            # Environment question optional
            if st.session_state.answers.get("Q22"):
                st.session_state.environment = str(st.session_state.answers["Q22"]).strip()

            save_to_fittings_fn(st.session_state.answers)
            st.session_state.interview_complete = True
            st.rerun()
