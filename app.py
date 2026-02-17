# app.py
from __future__ import annotations

import datetime
from typing import Dict, Any, Optional, List

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

from core.shaft_predictor import predict_shaft_winners
from core.sheet_validation import validate_sheet_data, render_report_streamlit

from ui.trackman_tab import render_trackman_tab
from ui.interview import render_interview
from ui.recommendations_tab import render_recommendations_tab


# ------------------ Page setup ------------------
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


# ------------------ DB ------------------
def get_google_creds(scopes: List[str]) -> Credentials:
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        if "private_key" in creds_dict:
            pk = creds_dict["private_key"].replace("\\n", "\n")
            if "-----BEGIN PRIVATE KEY-----" in pk:
                pk = pk[pk.find("-----BEGIN PRIVATE KEY-----") :]
            creds_dict["private_key"] = pk.strip()
        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    except Exception as e:
        st.error(f"🔐 Security Error: {e}")
        st.stop()
        raise


def cfg_float(cfg_df: pd.DataFrame, key: str, default: float) -> float:
    try:
        if cfg_df is not None and not cfg_df.empty and key in cfg_df.columns:
            val = str(cfg_df.iloc[0][key]).strip()
            return float(val)
    except Exception:
        pass
    return float(default)


@st.cache_data(ttl=600)
def get_data_from_gsheet() -> Optional[Dict[str, pd.DataFrame]]:
    try:
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
        for k in tabs:
            try:
                out[k] = get_clean_df(k)
            except Exception:
                out[k] = pd.DataFrame()
        return out

    except Exception as e:
        st.error(f"📡 Database Error: {e}")
        return None


def save_to_fittings(answers: Dict[str, Any]) -> None:
    """
    Writes a new row to the Fittings sheet by matching the sheet headers to:
      - Questions.QuestionText -> QuestionID
      - Special header mappings for sub-questions (Q16_1, Q16_2, Q19_1, Q19_2)
    This prevents the "Q01..Q29 appended in order" misalignment problem.
    """
    try:
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
        ws_q = sh.worksheet("Questions")

        # Read headers from Fittings (row 1)
        fit_headers = ws_fit.row_values(1)
        fit_headers = [str(h).strip() for h in fit_headers if str(h).strip()]

        # Build QuestionText -> QuestionID map
        q_rows = ws_q.get_all_values()
        q_headers = q_rows[0] if q_rows else []
        q_data = q_rows[1:] if len(q_rows) > 1 else []

        # Find column indices safely
        def _col_idx(name: str) -> Optional[int]:
            for i, h in enumerate(q_headers):
                if str(h).strip() == name:
                    return i
            return None

        idx_id = _col_idx("QuestionID")
        idx_text = _col_idx("QuestionText")

        text_to_qid: Dict[str, str] = {}
        if idx_id is not None and idx_text is not None:
            for r in q_data:
                if len(r) <= max(idx_id, idx_text):
                    continue
                qid = str(r[idx_id]).strip()
                qtext = str(r[idx_text]).strip()
                if qid and qtext:
                    text_to_qid[qtext] = qid

        # Special cases where Fittings headers don't match QuestionText exactly
        special_header_to_qid = {
            "Flight Satisfaction": "Q16_1",
            "Flight Change": "Q16_2",
            "Feel Satisfaction": "Q19_1",
            "Target Shaft Feel": "Q19_2",
        }

        # Build row in exact header order
        now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_out: List[Any] = []

        for h in fit_headers:
            if h.lower() == "timestamp":
                row_out.append(now_ts)
                continue

            qid = None
            if h in special_header_to_qid:
                qid = special_header_to_qid[h]
            elif h in text_to_qid:
                qid = text_to_qid[h]

            val = ""
            if qid:
                val = answers.get(qid, "")
            row_out.append(val)

        ws_fit.append_row(row_out, value_input_option="USER_ENTERED")

    except Exception as e:
        st.error(f"Error saving: {e}")


# ------------------ Admin gating ------------------
def is_admin_email(email: str, admin_df: pd.DataFrame) -> bool:
    e = str(email or "").strip().lower()
    if not e:
        return False
    if admin_df is None or admin_df.empty:
        return False
    if "Email" not in admin_df.columns:
        return False

    df = admin_df.copy()
    df["Email"] = df["Email"].astype(str).str.strip().str.lower()

    if "Active" in df.columns:

        def _is_active(v: Any) -> bool:
            s = str(v).strip().lower()
            return s in {"true", "yes", "1", "y", "active"}

        df = df[df["Active"].apply(_is_active)]

    return e in set(df["Email"].tolist())


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
if "selected_tag_ids" not in st.session_state:
    st.session_state.selected_tag_ids = []
if "baseline_tag_id" not in st.session_state:
    st.session_state.baseline_tag_id = None
if "lab_controls" not in st.session_state:
    st.session_state.lab_controls = {
        "length_matched": False,
        "swing_weight_matched": False,
        "grip_matched": False,
        "same_head": False,
        "same_ball": False,
    }
if "show_sheet_validation" not in st.session_state:
    st.session_state.show_sheet_validation = False


# ------------------ App Flow ------------------
all_data = get_data_from_gsheet()
if not all_data:
    st.stop()

cfg = all_data.get("Config", pd.DataFrame())
admin_df = all_data.get("Admin", pd.DataFrame())

admin_email = str(st.session_state.answers.get("Q02", "")).strip()
is_admin = is_admin_email(admin_email, admin_df)

report = validate_sheet_data(all_data)

if is_admin:
    st.session_state.show_sheet_validation = st.toggle(
        "Admin: Show sheet validation",
        value=bool(st.session_state.show_sheet_validation),
    )
    if st.session_state.show_sheet_validation:
        render_report_streamlit(report, title="Sheet Validation", show_info=True)

if report.errors:
    if is_admin:
        st.error("Sheet has fatal errors. Fix the Google Sheet and reload.")
    else:
        st.error("Configuration issue. Please contact your fitter/administrator.")
    st.stop()

WARN_FACE_TO_PATH_SD = cfg_float(cfg, "WARN_FACE_TO_PATH_SD", 3.0)
WARN_CARRY_SD = cfg_float(cfg, "WARN_CARRY_SD", 10.0)
WARN_SMASH_SD = cfg_float(cfg, "WARN_SMASH_SD", 0.10)
MIN_SHOTS = int(cfg_float(cfg, "MIN_SHOTS", 8))

q_master = all_data["Questions"]
if q_master is None or q_master.empty or "Category" not in q_master.columns:
    st.error("Questions sheet is missing or invalid.")
    st.stop()

categories = list(dict.fromkeys(q_master["Category"].astype(str).tolist()))


# ------------------ Interview ------------------
if not st.session_state.interview_complete:
    render_interview(
        all_data=all_data,
        q_master=q_master,
        categories=categories,
        save_to_fittings_fn=save_to_fittings,
    )


# ------------------ Results / Dashboard ------------------
else:
    ans = st.session_state.answers
    p_name, p_email = ans.get("Q01", "Player"), ans.get("Q02", "")
    st.session_state.environment = (ans.get("Q22") or st.session_state.environment or "Indoors (Mat)").strip()

    is_admin = is_admin_email(p_email, admin_df)

    st.title(f"⛳ Results: {p_name}")

    c_nav1, c_nav2, _ = st.columns([1, 1, 4])
    if c_nav1.button("✏️ Edit Fitting"):
        st.session_state.interview_complete = False
        st.session_state.email_sent = False
        st.rerun()

    if c_nav2.button("🆕 New Fitting"):
        st.session_state.clear()
        st.rerun()

    st.divider()
    tab_report, tab_lab = st.tabs(["📄 Recommendations", "🧪 Trackman Lab"])

    try:
        carry_6i = float(ans.get("Q15", 150))
    except Exception:
        carry_6i = 150.0

    all_winners = predict_shaft_winners(all_data["Shafts"], carry_6i)

    if "Model" in all_data["Descriptions"].columns and "Blurb" in all_data["Descriptions"].columns:
        desc_map = dict(zip(all_data["Descriptions"]["Model"], all_data["Descriptions"]["Blurb"]))
    else:
        desc_map = {}

    verdicts = {}
    for k in all_winners:
        try:
            verdicts[f"{k}: {all_winners[k].iloc[0]['Model']}"] = desc_map.get(
                all_winners[k].iloc[0]["Model"], "Optimized."
            )
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
        if is_admin:
            show = st.toggle("Admin: Show sheet validation (Lab)", value=False)
            if show:
                render_report_streamlit(report, title="Sheet Validation", show_info=True)

        render_trackman_tab(
            all_data=all_data,
            answers=st.session_state.answers,
            all_winners=all_winners,
            MIN_SHOTS=MIN_SHOTS,
            WARN_FACE_TO_PATH_SD=WARN_FACE_TO_PATH_SD,
            WARN_CARRY_SD=WARN_CARRY_SD,
            WARN_SMASH_SD=WARN_SMASH_SD,
        )
