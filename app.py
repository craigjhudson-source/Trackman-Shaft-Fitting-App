import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime

from utils import create_pdf_bytes, send_email_with_pdf

from core.trackman import load_trackman, summarize_trackman
from core.phase6_optimizer import phase6_recommendations
from core.shaft_predictor import predict_shaft_winners



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

# ✅ NEW: environment default
if "environment" not in st.session_state:
    st.session_state.environment = "Indoor (mat)"

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
            save_to_fittings(st.session_state.answers)
            st.session_state.interview_complete = True
            st.rerun()

else:
    ans = st.session_state.answers
    p_name, p_email = ans.get("Q01", "Player"), ans.get("Q02", "")
    st.title(f"⛳ Results: {p_name}")

    # --- Environment selector (Indoor vs Outdoor) ---
if "fit_environment" not in st.session_state:
    st.session_state.fit_environment = "Indoor"

st.session_state.fit_environment = st.radio(
    "Fitting Environment",
    ["Indoor (Mat / Simulator)", "Outdoor (Turf / Range)"],
    horizontal=True,
)

fit_env = "Indoor" if "Indoor" in st.session_state.fit_environment else "Outdoor"


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

    # -------- Phase 1 Predictor --------
    try:
        carry_6i = float(ans.get("Q15", 150))
    except Exception:
        carry_6i = 150.0

    f_tf, ideal_w = (8.5, 130) if carry_6i >= 195 else (7.0, 125) if carry_6i >= 180 else (6.0, 110) if carry_6i >= 165 else (5.0, 95)

    df_all = all_data["Shafts"].copy()
    for col in ["FlexScore", "Weight (g)", "StabilityIndex", "LaunchScore", "EI_Mid"]:
        df_all[col] = pd.to_numeric(df_all[col], errors="coerce").fillna(0)

    def get_top_3(mode):
        df_t = df_all.copy()
        df_t["Penalty"] = abs(df_t["FlexScore"] - f_tf) * 200 + abs(df_t["Weight (g)"] - ideal_w) * 15
        if carry_6i >= 180:
            df_t.loc[df_t["FlexScore"] < 6.5, "Penalty"] += 4000
        if mode == "Maximum Stability":
            df_t["Penalty"] -= (df_t["StabilityIndex"] * 600)
        elif mode == "Launch & Height":
            df_t["Penalty"] -= (df_t["LaunchScore"] * 500)
        elif mode == "Feel & Smoothness":
            df_t["Penalty"] += (df_t["EI_Mid"] * 400)
        return df_t.sort_values("Penalty").head(3)[["Brand", "Model", "Flex", "Weight (g)"]]

    all_winners = {k: get_top_3(k) for k in ["Balanced", "Maximum Stability", "Launch & Height", "Feel & Smoothness"]}
    desc_map = dict(zip(all_data["Descriptions"]["Model"], all_data["Descriptions"]["Blurb"]))
    verdicts = {f"{k}: {all_winners[k].iloc[0]['Model']}": desc_map.get(all_winners[k].iloc[0]["Model"], "Optimized.") for k in all_winners}

    # -------- Report Tab --------
    with tab_report:
        st.markdown(
            f"""<div class="profile-bar"><div class="profile-grid">
            <div><b>CARRY:</b> {ans.get('Q15','')}yd | <b>FLIGHT:</b> {ans.get('Q16','')} | <b>TARGET:</b> {ans.get('Q17','')}</div>
            <div><b>HEAD:</b> {ans.get('Q08','')} {ans.get('Q09','')}</div>
            <div><b>CURRENT:</b> {ans.get('Q12','')} ({ans.get('Q11','')}) | <b>MISS:</b> {ans.get('Q18','')}</div>
            <div><b>SPECS:</b> {ans.get('Q13','')} L / {ans.get('Q14','')} SW | <b>GRIP/BALL:</b> {ans.get('Q06','')}/{ans.get('Q07','')}</div>
            </div></div>""",
            unsafe_allow_html=True,
        )

        v_items = list(verdicts.items())
        col1, col2 = st.columns(2)
        for i, (cat, c_name) in enumerate(
            [("Balanced", "⚖️ Balanced"), ("Maximum Stability", "🛡️ Stability"), ("Launch & Height", "🚀 Launch"), ("Feel & Smoothness", "☁️ Feel")]
        ):
            with col1 if i < 2 else col2:
                st.subheader(c_name)
                st.table(all_winners[cat])
                st.markdown(f"<div class='verdict-text'><b>Verdict:</b> {v_items[i][1]}</div>", unsafe_allow_html=True)

        # ✅ Safe PDF sending (uses stored Phase-6 recs if available)
        if not st.session_state.email_sent and p_email:
            with st.spinner("Dispatching PDF..."):
                pdf_bytes = create_pdf_bytes(
                    p_name,
                    all_winners,
                    ans,
                    verdicts,
                    phase6_recs=st.session_state.get("phase6_recs", None),
                )
                if send_email_with_pdf(p_email, p_name, pdf_bytes) is True:
                    st.success(f"📬 Sent to {p_email}!")
                    st.session_state.email_sent = True

    # -------- TrackMan Lab Tab --------
    with tab_lab:
        st.header("🧪 Trackman Lab (Controlled Testing)")

        # ✅ NEW: Indoor/Outdoor toggle
        st.session_state.environment = st.radio(
            "Testing environment",
            ["Indoor (mat)", "Outdoor (turf)"],
            horizontal=True,
            index=0 if st.session_state.environment == "Indoor (mat)" else 1,
        )

        with st.expander("✅ Lab Controls (required before logging)", expanded=True):
            st.session_state.lab_controls["length_matched"] = st.checkbox("Length matched (same playing length)", value=st.session_state.lab_controls["length_matched"])
            st.session_state.lab_controls["swing_weight_matched"] = st.checkbox("Swing weight matched", value=st.session_state.lab_controls["swing_weight_matched"])
            st.session_state.lab_controls["grip_matched"] = st.checkbox("Grip matched", value=st.session_state.lab_controls["grip_matched"])
            st.session_state.lab_controls["same_head"] = st.checkbox("Same head used", value=st.session_state.lab_controls["same_head"])
            st.session_state.lab_controls["same_ball"] = st.checkbox("Same ball used", value=st.session_state.lab_controls["same_ball"])

            if controls_complete():
                st.success("Controls confirmed. Logged data will be marked as controlled.")
            else:
                st.warning("Complete all controls before logging data (prevents bad correlation).")

        c_up, c_res = st.columns([1, 2])

        with c_up:
            test_list = ["Current Baseline"] + [all_winners[k].iloc[0]["Model"] for k in all_winners]
            selected_s = st.selectbox("Assign Data to:", test_list)

            tm_file = st.file_uploader("Upload Trackman CSV/Excel", type=["csv", "xlsx"])

            can_log = tm_file is not None and controls_complete()
            if st.button("➕ Add") and can_log:
                stat = process_trackman_file(tm_file, selected_s)
                if stat:
                    stat["Controlled"] = "Yes"
                    stat["Timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    st.session_state.tm_lab_data.append(stat)
                    st.rerun()
                else:
                    st.error("Could not parse TrackMan file. (Export format may be unexpected.)")

            if tm_file is not None and not controls_complete():
                st.info("Finish Lab Controls above to enable logging.")

        with c_res:
            if not st.session_state.tm_lab_data:
                st.info("Upload files to begin correlation.")
            else:
                lab_df = pd.DataFrame(st.session_state.tm_lab_data)

                preferred_cols = [
                    "Timestamp", "Shaft ID", "Controlled",
                    "Club Speed", "Ball Speed", "Smash Factor", "Carry", "Spin Rate",
                    "Launch Angle", "Landing Angle", "Face To Path", "Dynamic Lie",
                    "Carry Side", "Total Side",
                    "Club Speed SD", "Ball Speed SD", "Smash Factor SD", "Carry SD", "Spin Rate SD",
                    "Face To Path SD", "Dynamic Lie SD",
                ]
                show_cols = [c for c in preferred_cols if c in lab_df.columns] + [c for c in lab_df.columns if c not in preferred_cols]
                st.table(lab_df[show_cols])

                baseline_row = None
                if (lab_df["Shaft ID"] == "Current Baseline").any():
                    baseline_row = lab_df[lab_df["Shaft ID"] == "Current Baseline"].iloc[-1]

                cand = lab_df[lab_df["Shaft ID"] != "Current Baseline"].copy()
                if len(cand) >= 1 and "Smash Factor" in cand.columns:
                    top_idx = cand["Smash Factor"].astype(float).idxmax()
                    winner_row = cand.loc[top_idx]
                    winner_name = winner_row["Shaft ID"]
                    st.success(f"🏆 **Efficiency Winner:** {winner_name} (Smash {winner_row.get('Smash Factor','')})")

                    if "Face To Path SD" in cand.columns:
                        try:
                            most_stable = cand.loc[cand["Face To Path SD"].astype(float).idxmin()]["Shaft ID"]
                            st.info(f"🛡️ **Most Stable (Face-to-Path SD):** {most_stable}")
                        except Exception:
                            pass

                    st.subheader("Phase 6 Optimization Suggestions")

                    # ✅ UPDATED: pass environment into Phase 6 optimizer
                    recs = phase6_recommendations(
                        winner_row,
                        baseline_row=baseline_row,
                        club="6i",
                        environment=st.session_state.environment,
                    )

                    st.session_state.phase6_recs = recs  # ✅ store for PDF use

                    for r in recs:
                        css = "rec-warn" if r["severity"] == "warn" else "rec-info"
                        st.markdown(f"<div class='{css}'><b>{r['type']}:</b> {r['text']}</div>", unsafe_allow_html=True)
                else:
                    st.info("Log at least 1 candidate shaft file (and ideally baseline) to select a winner + Phase 6 recommendations.")
