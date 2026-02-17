# app.py
from __future__ import annotations

from typing import Dict, Any, Optional, List

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

from core.shaft_predictor import predict_shaft_winners
from core.sheet_validation import validate_sheet_data, render_report_streamlit
from core.fittings_writer import build_questiontext_to_qid, build_fittings_row, FittingMeta

from ui.interview import render_interview
from ui.trackman_tab import render_trackman_tab
from ui.recommendations_tab import render_recommendations_tab


st.set_page_config(page_title="Tour Proven Shaft Fitting", layout="wide", page_icon="⛳")

st.markdown(
    """
<style>
[data-testid="stTable"] { font-size: 12px !important; }
.profile-bar { background-color: #142850; color: white; padding: 20px; border-radius: 10px; margin-bottom: 25px; }
.profile-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
.verdict-text { font-style: italic; color: #bfbfbf; margin-bottom: 25px; font-size: 13px; border-left: 3px solid #b40000; padding-left: 10px; }
.rec-warn { border-left: 4px solid #b40000; padding-left: 10px; margin: 6px 0; }
.rec-info { border-left: 4px solid #2c6bed; padding-left: 10px; margin: 6px 0; }
.smallcap { color: #9aa0a6; font-size: 12px; }
</style>
""",
    unsafe_allow_html=True,
)


def get_google_creds(scopes: List[str]) -> Credentials:
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in creds_dict:
        pk = creds_dict["private_key"].replace("\\n", "\n")
        if "-----BEGIN PRIVATE KEY-----" in pk:
            pk = pk[pk.find("-----BEGIN PRIVATE KEY-----") :]
        creds_dict["private_key"] = pk.strip()
    return Credentials.from_service_account_info(creds_dict, scopes=scopes)


def cfg_float(cfg_df: pd.DataFrame, key: str, default: float) -> float:
    try:
        if cfg_df is not None and not cfg_df.empty and key in cfg_df.columns:
            return float(str(cfg_df.iloc[0][key]).strip())
    except Exception:
        pass
    return float(default)


@st.cache_data(ttl=600)
def get_data_from_gsheet() -> Optional[Dict[str, pd.DataFrame]]:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = get_google_creds(scopes)
    gc = gspread.authorize(creds)

    sh = gc.open_by_url(
        "https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit"
    )

    def get_clean_df(ws_name: str) -> pd.DataFrame:
        rows = sh.worksheet(ws_name).get_all_values()
        if not rows or len(rows) < 2:
            return pd.DataFrame()
        headers = [(h.strip() if str(h).strip() else f"Col_{i}") for i, h in enumerate(rows[0])]
        df = pd.DataFrame(rows[1:], columns=headers)
        for c in df.columns:
            if df[c].dtype == "object":
                df[c] = df[c].astype(str).str.strip()
        return df

    tabs = ["Heads", "Shafts", "Questions", "Responses", "Config", "Descriptions", "Fittings", "Admin"]
    out: Dict[str, pd.DataFrame] = {}
    for t in tabs:
        try:
            out[t] = get_clean_df(t)
        except Exception:
            out[t] = pd.DataFrame()
    return out


def save_to_fittings(answers: Dict[str, Any], all_data: Dict[str, pd.DataFrame]) -> None:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = get_google_creds(scopes)
    gc = gspread.authorize(creds)

    sh = gc.open_by_url(
        "https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit"
    )
    ws_fit = sh.worksheet("Fittings")

    fit_headers = [h for h in ws_fit.row_values(1) if str(h).strip()]

    q_df = all_data.get("Questions", pd.DataFrame())
    q_rows: List[Dict[str, Any]] = []
    if q_df is not None and not q_df.empty:
        q_rows = q_df.to_dict(orient="records")

    questiontext_to_qid = build_questiontext_to_qid(q_rows)

    now_ts = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    meta = FittingMeta(
        timestamp=now_ts,
        name=str(answers.get("Q01", "")).strip(),
        email=str(answers.get("Q02", "")).strip(),
        phone=str(answers.get("Q03", "")).strip(),
    )

    row_out = build_fittings_row(
        fittings_headers=fit_headers,
        questiontext_to_qid=questiontext_to_qid,
        answers=answers,
        meta=meta,
    )

    ws_fit.append_row(row_out, value_input_option="USER_ENTERED")


# ------------------ Session defaults ------------------
if "form_step" not in st.session_state:
    st.session_state.form_step = 0
if "interview_complete" not in st.session_state:
    st.session_state.interview_complete = False
if "answers" not in st.session_state:
    st.session_state.answers = {}
if "email_sent" not in st.session_state:
    st.session_state.email_sent = False
if "tm_lab_data" not in st.session_state:
    st.session_state.tm_lab_data = []
if "phase6_recs" not in st.session_state:
    st.session_state.phase6_recs = None
if "winner_summary" not in st.session_state:
    st.session_state.winner_summary = None
if "environment" not in st.session_state:
    st.session_state.environment = "Indoors (Mat)"

# ✅ HOTFIX: Trackman tab expects this to exist
if "lab_controls" not in st.session_state or not isinstance(st.session_state.get("lab_controls"), dict):
    st.session_state.lab_controls = {}
# Ensure the specific key that crashed exists
st.session_state.lab_controls.setdefault("length_matched", False)


# ------------------ Load sheet ------------------
all_data = get_data_from_gsheet()
if not all_data:
    st.stop()

report = validate_sheet_data(all_data)
render_report_streamlit(report, title="Sheet Validation", show_info=False)
if report.errors:
    st.error("Sheet has fatal errors. Fix the Google Sheet and reload.")
    st.stop()

cfg = all_data.get("Config", pd.DataFrame())
WARN_FACE_TO_PATH_SD = cfg_float(cfg, "WARN_FACE_TO_PATH_SD", 3.0)
WARN_CARRY_SD = cfg_float(cfg, "WARN_CARRY_SD", 10.0)
WARN_SMASH_SD = cfg_float(cfg, "WARN_SMASH_SD", 0.10)
MIN_SHOTS = int(cfg_float(cfg, "MIN_SHOTS", 8))

q_master = all_data.get("Questions", pd.DataFrame())
if q_master is None or q_master.empty or "Category" not in q_master.columns:
    st.error("Questions sheet is missing or invalid.")
    st.stop()

categories = list(dict.fromkeys(q_master["Category"].astype(str).tolist()))


# ------------------ Interview ------------------
if not st.session_state.interview_complete:

    def _save(answers: Dict[str, Any]) -> None:
        save_to_fittings(answers, all_data)

    render_interview(all_data=all_data, q_master=q_master, categories=categories, save_to_fittings_fn=_save)

else:
    ans = st.session_state.answers

    p_name, p_email = ans.get("Q01", "Player"), ans.get("Q02", "")
    st.session_state.environment = (ans.get("Q22") or st.session_state.environment or "Indoors (Mat)").strip()

    st.title(f"⛳ Results: {p_name}")

    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button("✏️ Edit Fitting"):
        st.session_state.interview_complete = False
        st.session_state.email_sent = False
        st.rerun()

    if c2.button("🆕 New Fitting"):
        st.session_state.clear()
        st.rerun()

    st.divider()
    tab_report, tab_lab = st.tabs(["📄 Recommendations", "🧪 Trackman Lab"])

    try:
        carry_6i = float(ans.get("Q15", 150))
    except Exception:
        carry_6i = 150.0

    all_winners = predict_shaft_winners(all_data["Shafts"], carry_6i)

    verdicts: Dict[str, str] = {}
    desc = all_data.get("Descriptions", pd.DataFrame())
    if desc is not None and not desc.empty and "Model" in desc.columns and "Blurb" in desc.columns:
        desc_map = dict(zip(desc["Model"], desc["Blurb"]))
    else:
        desc_map = {}

    for k in all_winners:
        try:
            verdicts[f"{k}: {all_winners[k].iloc[0]['Model']}"] = desc_map.get(all_winners[k].iloc[0]["Model"], "Optimized.")
        except Exception:
            verdicts[f"{k}:"] = "Optimized."

    with tab_report:
        render_recommendations_tab(
            p_name=p_name,
            p_email=p_email,
            ans=ans,
            all_winners=all_winners,
            verdicts=verdicts,
            environment=st.session_state.environment,
        )

    with tab_lab:
        render_trackman_tab(
            all_data=all_data,
            answers=st.session_state.answers,
            all_winners=all_winners,
            MIN_SHOTS=MIN_SHOTS,
            WARN_FACE_TO_PATH_SD=WARN_FACE_TO_PATH_SD,
            WARN_CARRY_SD=WARN_CARRY_SD,
            WARN_SMASH_SD=WARN_SMASH_SD,
        )
