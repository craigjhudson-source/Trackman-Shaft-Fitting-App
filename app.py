import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime

from utils import create_pdf_bytes, send_email_with_pdf

from core.trackman import load_trackman, summarize_trackman
from core.phase6_optimizer import phase6_recommendations


st.set_page_config(page_title="Tour Proven Shaft Fitting", layout="wide", page_icon="⛳")

st.markdown("""
    <style>
    [data-testid="stTable"] { font-size: 12px !important; }
    .profile-bar { background-color: #142850; color: white; padding: 20px; border-radius: 10px; margin-bottom: 25px; }
    .profile-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
    .verdict-text { font-style: italic; color: #444; margin-bottom: 25px; font-size: 13px; border-left: 3px solid #b40000; padding-left: 10px; }
    .rec-warn { border-left: 4px solid #b40000; padding-left: 10px; margin: 6px 0; }
    .rec-info { border-left: 4px solid #2c6bed; padding-left: 10px; margin: 6px 0; }
    </style>
""", unsafe_allow_html=True)


# ------------------ DB ------------------
def get_google_creds(scopes):
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        if "private_key" in creds_dict:
            pk = creds_dict["private_key"].replace("\\n", "\n")
            if "-----BEGIN PRIVATE KEY-----" in pk:
                pk = pk[pk.find("-----BEGIN PRIVATE KEY-----"):]
            creds_dict["private_key"] = pk.strip()
        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    except Exception as e:
        st.error(f"🔐 Security Error: {e}")
        st.stop()


@st.cache_data(ttl=600)
def get_data_from_gsheet():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = get_google_creds(scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url("https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit")

        def get_clean_df(ws_name):
            rows = sh.worksheet(ws_name).get_all_values()
            df = pd.DataFrame(rows[1:], columns=[h.strip() if h.strip() else f"Col_{i}" for i, h in enumerate(rows[0])])
            return df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)

        return {k: get_clean_df(k) for k in ["Heads", "Shafts", "Questions", "Responses", "Config", "Descriptions"]}
    except Exception as e:
        st.error(f"📡 Database Error: {e}")
        return None


def save_to_fittings(answers):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = get_google_creds(scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url("https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit")
        worksheet = sh.worksheet("Fittings")
        row = [datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")] + [answers.get(f"Q{i:02d}", "") for i in range(1, 22)]
        worksheet.append_row(row)
    except Exception as e:
        st.error(f"Error saving: {e}")


# ------------------ TrackMan ------------------
def process_trackman_file(uploaded_file, shaft_id):
    try:
        raw = load_trackman(uploaded_file)
        return summarize_trackman(raw, shaft_id, include_std=True)
    except Exception:
        return None


# ------------------ Session ------------------
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

if "lab_controls" not in st.session_state:
    st.session_state.lab_controls = {
        "length_matched": False,
        "swing_weight_matched": False,
        "grip_matched": False,
        "same_head": False,
        "same_ball": False,
    }


def sync_all():
    for key in st.session_state:
        if key.startswith("widget_"):
            st.session_state.answers[key.replace("widget_", "")] = st.session_state[key]


def controls_complete() -> bool:
    return all(bool(v) for v in st.session_state.lab_controls.values())


# ------------------ App Flow ------------------
all_data = get_data_from_gsheet()
if not all_data:
    st.stop()

q_master = all_data["Questions"]
categories = list(dict.fromkeys(q_master["Category"].tolist()))

if not st.session_state.interview_complete:
    st.title("⛳ Tour Proven Fitting Interview")
    current_cat = categories[st.session_state.form_step]
    q_df = q_master[q_master["Category"] == current_cat]

    for _, row in q_df.iterrows():
        qid = str(row["QuestionID"]).strip()
        qtext = row["QuestionText"]
        qtype = row["InputType"]
        qopts = str(row["Options"]).strip()
        ans_val = st.session_state.answers.get(qid, "")

        if qtype == "Dropdown":
            opts = [""]

            if "Heads" in qopts:
                brand_val = st.session_state.answers.get("Q08", "")
                if "Brand" in qtext:
                    opts += sorted(all_data["Heads"]["Manufacturer"].unique().tolist())
                else:
                    opts += (
                        sorted(all_data["Heads"][all_data["Heads"]["Manufacturer"] == brand_val]["Model"].unique().tolist())
                        if brand_val else ["Select Brand First"]
                    )

            elif "Shafts" in qopts:
                s_brand, s_flex = st.session_state.answers.get("Q10", ""), st.session_state.answers.get("Q11", "")
                if "Brand" in qtext:
                    opts += sorted(all_data["Shafts"]["Brand"].unique().tolist())
                elif "Flex" in qtext:
                    opts += sorted(all_data["Shafts"][all_data["Shafts"]["Brand"] == s_brand]["Flex"].unique().tolist()) if s_brand else ["Select Brand First"]
                elif "Model" in qtext:
                    if s_brand and s_flex:
                        opts += sorted(all_data["Shafts"][(all_data["Shafts"]["Brand"] == s_brand) & (all_data["Shafts"]["Flex"] == s_flex)]["Model"].unique().tolist())
                    else:
                        opts += ["Select Brand/Flex First"]

            elif "Config:" in qopts:
                col = qopts.split(":")[1].strip()
                if col in all_data["Config"].columns:
                    opts += all_data["Config"][col].dropna().tolist()

            else:
                opts += all_data["Responses"][all_data["Responses"]["QuestionID"] == qid]["ResponseOption"].tolist()

            opts = list(dict.fromkeys([str(x) for x in opts if x]))
            st.selectbox(
                qtext,
                opts,
                index=opts.index(str(ans_val)) if str(ans_val) in opts else 0,
                key=f"widget_{qid}",
                on_change=sync_all,
            )

        elif qtype == "Numeric":
            st.number_input(qtext, value=float(ans_val) if ans_val else 0.0, key=f"widget_{qid}", on_change=sync_all)
        else:
            st.text_input(qtext, value=str(ans_val), key=f"widget_{qid}", on_change=sync_all)

    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button("⬅️ Back") and st.session_state.form_step > 0:
        sync_all()
        st.session_state.form_step -= 1
        st.rerun()

    if st.session_state.form_step < len(categories) - 1:
        if c2.button("Next ➡️"):
            sync_all()
            st.session_state.form_step += 1
            st.rerun()
    else:
        if c2.button("🔥 Calculate"):
            sync_all()
