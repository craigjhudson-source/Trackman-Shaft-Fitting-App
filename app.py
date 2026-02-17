# app.py
from __future__ import annotations

import datetime
from typing import Dict, Any, Optional, List

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

from utils import create_pdf_bytes, send_email_with_pdf
from core.phase6_optimizer import phase6_recommendations
from core.shaft_predictor import predict_shaft_winners

# Sheet validation (non-crashing warnings)
from core.sheet_validation import validate_sheet_data, render_report_streamlit

# NEW: TrackMan tab extracted
from ui.trackman_tab import render_trackman_tab


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

        # We include Fittings for schema validation (and future writeback)
        tabs = ["Heads", "Shafts", "Questions", "Responses", "Config", "Descriptions", "Fittings"]
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
        worksheet = sh.worksheet("Fittings")

        row = [datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")] + [
            answers.get(f"Q{i:02d}", "") for i in range(1, 30)
        ]
        worksheet.append_row(row)
    except Exception as e:
        st.error(f"Error saving: {e}")


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


def sync_all() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith("widget_"):
            st.session_state.answers[key.replace("widget_", "")] = st.session_state[key]


def should_show_question(qid: str, answers: Dict[str, Any]) -> bool:
    """
    Decision-tree visibility for sub-questions.
    Hides follow-ups unless satisfaction is answered and is not Yes.
    """
    qid = str(qid).strip()

    # Flight follow-up only if NOT happy with flight
    if qid == "Q16_2":
        a = str(answers.get("Q16_1", "")).strip().lower()
        return a in {"no", "unsure"}

    # Feel follow-up only if NOT happy with feel
    if qid == "Q19_2":
        a = str(answers.get("Q19_1", "")).strip().lower()
        return a in {"no", "unsure"}

    return True


# ------------------ App Flow ------------------
all_data = get_data_from_gsheet()
if not all_data:
    st.stop()

# Validate sheet structure + show friendly banners.
report = validate_sheet_data(all_data)
render_report_streamlit(report)
if report.errors:
    st.stop()

cfg = all_data["Config"]

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
    st.title("⛳ Tour Proven Fitting Interview")

    current_cat = categories[st.session_state.form_step]
    q_df = q_master[q_master["Category"].astype(str) == str(current_cat)]

    for _, row in q_df.iterrows():
        qid = str(row.get("QuestionID", "")).strip()
        if not qid:
            continue

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

            # Responses sheet fallback (will be empty if you archived Responses)
            else:
                resp_df = all_data.get("Responses", pd.DataFrame())
                if (
                    resp_df is not None
                    and not resp_df.empty
                    and "QuestionID" in resp_df.columns
                    and "ResponseOption" in resp_df.columns
                ):
                    opts += (
                        resp_df[resp_df["QuestionID"].astype(str).str.strip() == qid]["ResponseOption"]
                        .astype(str)
                        .tolist()
                    )

            opts = list(dict.fromkeys([str(x) for x in opts if str(x).strip() != ""]))

            st.selectbox(
                qtext,
                opts,
                index=opts.index(str(ans_val)) if str(ans_val) in opts else 0,
                key=f"widget_{qid}",
                on_change=sync_all,
            )

        elif qtype == "Numeric":
            try:
                v = float(ans_val) if str(ans_val).strip() else 0.0
            except Exception:
                v = 0.0
            st.number_input(qtext, value=v, key=f"widget_{qid}", on_change=sync_all)

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
            if st.session_state.answers.get("Q22"):
                st.session_state.environment = str(st.session_state.answers["Q22"]).strip()
            save_to_fittings(st.session_state.answers)
            st.session_state.interview_complete = True
            st.rerun()


# ------------------ Results / Dashboard ------------------
else:
    ans = st.session_state.answers
    p_name, p_email = ans.get("Q01", "Player"), ans.get("Q02", "")
    st.session_state.environment = (ans.get("Q22") or st.session_state.environment or "Indoors (Mat)").strip()

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

    # -------- Predictor --------
    try:
        carry_6i = float(ans.get("Q15", 150))
    except Exception:
        carry_6i = 150.0

    all_winners = predict_shaft_winners(all_data["Shafts"], carry_6i)

    # Verdict blurbs
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

    # -------- Report Tab --------
    with tab_report:
        st.markdown(
            f"""<div class="profile-bar"><div class="profile-grid">
<div><b>CARRY:</b> {ans.get('Q15','')}yd</div>
<div><b>HEAD:</b> {ans.get('Q08','')} {ans.get('Q09','')}</div>
<div><b>CURRENT:</b> {ans.get('Q12','')} ({ans.get('Q11','')})</div>
<div><b>SPECS:</b> {ans.get('Q13','')} L / {ans.get('Q14','')} SW</div>
<div><b>GRIP/BALL:</b> {ans.get('Q06','')}/{ans.get('Q07','')}</div>
<div><b>ENVIRONMENT:</b> {st.session_state.environment}</div>
</div></div>""",
            unsafe_allow_html=True,
        )

        v_items = list(verdicts.items())
        col1, col2 = st.columns(2)
        cats = [
            ("Balanced", "⚖️ Balanced"),
            ("Maximum Stability", "🛡️ Stability"),
            ("Launch & Height", "🚀 Launch"),
            ("Feel & Smoothness", "☁️ Feel"),
        ]
        for i, (cat, c_name) in enumerate(cats):
            with col1 if i < 2 else col2:
                st.subheader(c_name)
                if cat in all_winners:
                    st.table(all_winners[cat])
                    blurb = v_items[i][1] if i < len(v_items) else "Optimized."
                    st.markdown(
                        f"<div class='verdict-text'><b>Verdict:</b> {blurb}</div>",
                        unsafe_allow_html=True,
                    )

        if not st.session_state.email_sent and p_email:
            with st.spinner("Dispatching PDF..."):
                pdf_bytes = create_pdf_bytes(
                    p_name,
                    all_winners,
                    ans,
                    verdicts,
                    phase6_recs=st.session_state.get("phase6_recs", None),
                    environment=st.session_state.environment,
                )
                ok = send_email_with_pdf(
                    p_email, p_name, pdf_bytes, environment=st.session_state.environment
                )
                if ok is True:
                    st.success(f"📬 Sent to {p_email}!")
                    st.session_state.email_sent = True
                else:
                    st.error(f"Email failed: {ok}")

    # -------- TrackMan Lab Tab --------
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
