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

st.markdown(
    """
    <style>
    [data-testid="stTable"] { font-size: 12px !important; }
    .profile-bar { background-color: #142850; color: white; padding: 20px; border-radius: 10px; margin-bottom: 25px; }
    .profile-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
    .verdict-text { font-style: italic; color: #444; margin-bottom: 25px; font-size: 13px; border-left: 3px solid #b40000; padding-left: 10px; }
    .rec-warn { border-left: 4px solid #b40000; padding-left: 10px; margin: 6px 0; }
    .rec-info { border-left: 4px solid #2c6bed; padding-left: 10px; margin: 6px 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------ DB ------------------
def get_google_creds(scopes):
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


def cfg_float(cfg_df: pd.DataFrame, key: str, default: float) -> float:
    """
    Reads a float from Config sheet using FIRST ROW values.
    Config tab layout: columns are keys; row 2 contains values (index 0 here).
    """
    try:
        if key in cfg_df.columns and len(cfg_df) >= 1:
            val = str(cfg_df.iloc[0][key]).strip()
            return float(val)
    except Exception:
        pass
    return float(default)


@st.cache_data(ttl=600)
def get_data_from_gsheet():
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

        def get_clean_df(ws_name):
            rows = sh.worksheet(ws_name).get_all_values()
            df = pd.DataFrame(
                rows[1:],
                columns=[
                    h.strip() if h.strip() else f"Col_{i}"
                    for i, h in enumerate(rows[0])
                ],
            )
            return df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)

        return {
            k: get_clean_df(k)
            for k in ["Heads", "Shafts", "Questions", "Responses", "Config", "Descriptions"]
        }
    except Exception as e:
        st.error(f"📡 Database Error: {e}")
        return None


def save_to_fittings(answers):
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
            answers.get(f"Q{i:02d}", "") for i in range(1, 23)  # includes Q22
        ]
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

if "environment" not in st.session_state:
    st.session_state.environment = "Indoors (Mat)"

if "lab_controls" not in st.session_state:
    st.session_state.lab_controls = {
        "length_matched": False,
        "swing_weight_matched": False,
        "grip_matched": False,
        "same_head": False,
        "same_ball": False,
    }


def sync_all():
    for key in list(st.session_state.keys()):
        if key.startswith("widget_"):
            st.session_state.answers[key.replace("widget_", "")] = st.session_state[key]


def controls_complete() -> bool:
    return all(bool(v) for v in st.session_state.lab_controls.values())


# ------------------ App Flow ------------------
all_data = get_data_from_gsheet()
if not all_data:
    st.stop()

cfg = all_data["Config"]

WARN_FACE_TO_PATH_SD = cfg_float(cfg, "WARN_FACE_TO_PATH_SD", 2.0)
WARN_CARRY_SD = cfg_float(cfg, "WARN_CARRY_SD", 10.0)
WARN_SMASH_SD = cfg_float(cfg, "WARN_SMASH_SD", 0.15)

# ✅ MIN_SHOTS now comes from Config
MIN_SHOTS = int(cfg_float(cfg, "MIN_SHOTS", 5))

q_master = all_data["Questions"]
categories = list(dict.fromkeys(q_master["Category"].tolist()))


# ------------------ Interview ------------------
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
                        sorted(
                            all_data["Heads"][all_data["Heads"]["Manufacturer"] == brand_val]["Model"]
                            .unique()
                            .tolist()
                        )
                        if brand_val
                        else ["Select Brand First"]
                    )

            elif "Shafts" in qopts:
                s_brand = st.session_state.answers.get("Q10", "")
                s_flex = st.session_state.answers.get("Q11", "")
                if "Brand" in qtext:
                    opts += sorted(all_data["Shafts"]["Brand"].unique().tolist())
                elif "Flex" in qtext:
                    opts += (
                        sorted(all_data["Shafts"][all_data["Shafts"]["Brand"] == s_brand]["Flex"].unique().tolist())
                        if s_brand
                        else ["Select Brand First"]
                    )
                elif "Model" in qtext:
                    if s_brand and s_flex:
                        opts += sorted(
                            all_data["Shafts"][
                                (all_data["Shafts"]["Brand"] == s_brand)
                                & (all_data["Shafts"]["Flex"] == s_flex)
                            ]["Model"]
                            .unique()
                            .tolist()
                        )
                    else:
                        opts += ["Select Brand/Flex First"]

            elif "Config:" in qopts:
                col = qopts.split(":")[1].strip()
                if col in all_data["Config"].columns:
                    opts += all_data["Config"][col].dropna().tolist()

            else:
                opts += (
                    all_data["Responses"][all_data["Responses"]["QuestionID"] == qid]["ResponseOption"]
                    .tolist()
                )

            opts = list(dict.fromkeys([str(x) for x in opts if x]))
            st.selectbox(
                qtext,
                opts,
                index=opts.index(str(ans_val)) if str(ans_val) in opts else 0,
                key=f"widget_{qid}",
                on_change=sync_all,
            )

        elif qtype == "Numeric":
            st.number_input(
                qtext,
                value=float(ans_val) if ans_val else 0.0,
                key=f"widget_{qid}",
                on_change=sync_all,
            )
        else:
            st.text_input(
                qtext,
                value=str(ans_val),
                key=f"widget_{qid}",
                on_change=sync_all,
            )

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

            # Sync environment from Q22 if present
            if st.session_state.answers.get("Q22"):
                st.session_state.environment = st.session_state.answers["Q22"]

            save_to_fittings(st.session_state.answers)
            st.session_state.interview_complete = True
            st.rerun()


# ------------------ Results / Dashboard ------------------
else:
    ans = st.session_state.answers
    p_name, p_email = ans.get("Q01", "Player"), ans.get("Q02", "")

    st.session_state.environment = ans.get("Q22") or st.session_state.environment or "Indoors (Mat)"

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

    # -------- Phase 1 Predictor --------
    try:
        carry_6i = float(ans.get("Q15", 150))
    except Exception:
        carry_6i = 150.0

    all_winners = predict_shaft_winners(all_data["Shafts"], carry_6i)

    desc_map = dict(zip(all_data["Descriptions"]["Model"], all_data["Descriptions"]["Blurb"]))
    verdicts = {
        f"{k}: {all_winners[k].iloc[0]['Model']}":
        desc_map.get(all_winners[k].iloc[0]["Model"], "Optimized.")
        for k in all_winners
    }

    # -------- Report Tab --------
    with tab_report:
        st.markdown(
            f"""<div class="profile-bar"><div class="profile-grid">
            <div><b>CARRY:</b> {ans.get('Q15','')}yd | <b>FLIGHT:</b> {ans.get('Q16','')} | <b>TARGET:</b> {ans.get('Q17','')}</div>
            <div><b>HEAD:</b> {ans.get('Q08','')} {ans.get('Q09','')}</div>
            <div><b>CURRENT:</b> {ans.get('Q12','')} ({ans.get('Q11','')}) | <b>MISS:</b> {ans.get('Q18','')}</div>
            <div><b>SPECS:</b> {ans.get('Q13','')} L / {ans.get('Q14','')} SW | <b>GRIP/BALL:</b> {ans.get('Q06','')}/{ans.get('Q07','')}</div>
            <div><b>ENVIRONMENT:</b> {st.session_state.environment}</div>
            </div></div>""",
            unsafe_allow_html=True,
        )

        v_items = list(verdicts.items())
        col1, col2 = st.columns(2)
        for i, (cat, c_name) in enumerate(
            [("Balanced", "⚖️ Balanced"), ("Maximum Stability", "🛡️ Stability"),
             ("Launch & Height", "🚀 Launch"), ("Feel & Smoothness", "☁️ Feel")]
        ):
            with col1 if i < 2 else col2:
                st.subheader(c_name)
                st.table(all_winners[cat])
                st.markdown(f"<div class='verdict-text'><b>Verdict:</b> {v_items[i][1]}</div>", unsafe_allow_html=True)

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
                ok = send_email_with_pdf(p_email, p_name, pdf_bytes, environment=st.session_state.environment)
                if ok is True:
                    st.success(f"📬 Sent to {p_email}!")
                    st.session_state.email_sent = True
                else:
                    st.error(f"Email failed: {ok}")

    # -------- TrackMan Lab Tab --------
    with tab_lab:
        st.header("🧪 Trackman Lab (Controlled Testing)")

        st.caption(
            f"Quality rules: MIN_SHOTS={MIN_SHOTS} | "
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

                if not stat:
                    st.error("Could not parse TrackMan file. Check export format.")
                else:
                    shot_count = int(float(stat.get("Shot Count", 0) or 0))
                    if shot_count < MIN_SHOTS:
                        st.error(
                            f"Not enough shots to log: {shot_count} found. "
                            f"Minimum is {MIN_SHOTS}. Export at least {MIN_SHOTS} valid shots (Use In Stat = TRUE)."
                        )
                    else:
                        stat["Shaft ID"] = selected_s
                        stat["Controlled"] = "Yes"
                        stat["Environment"] = st.session_state.environment
                        stat["Timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        st.session_state.tm_lab_data.append(stat)
                        st.rerun()

            if tm_file is not None and not controls_complete():
                st.info("Finish Lab Controls above to enable logging.")

        with c_res:
            if not st.session_state.tm_lab_data:
                st.info("Upload files to begin correlation.")
            else:
                lab_df = pd.DataFrame(st.session_state.tm_lab_data)

                preferred_cols = [
                    "Timestamp", "Shaft ID", "Controlled", "Environment", "Shot Count",
                    "Club Speed", "Ball Speed", "Smash Factor", "Carry", "Spin Rate",
                    "Launch Angle", "Landing Angle", "Face To Path", "Dynamic Lie",
                    "Carry Side", "Total Side",
                    "Club Speed SD", "Ball Speed SD", "Smash Factor SD", "Carry SD", "Spin Rate SD",
                    "Face To Path SD", "Dynamic Lie SD",
                ]
                show_cols = [c for c in preferred_cols if c in lab_df.columns] + [
                    c for c in lab_df.columns if c not in preferred_cols
                ]
                st.table(lab_df[show_cols])

                # Baseline must meet min shots
                baseline_row = None
                if (lab_df["Shaft ID"] == "Current Baseline").any():
                    try:
                        baseline_candidate = lab_df[lab_df["Shaft ID"] == "Current Baseline"].iloc[-1]
                        b_shots = int(float(baseline_candidate.get("Shot Count", 0) or 0))
                        if b_shots >= MIN_SHOTS:
                            baseline_row = baseline_candidate
                        else:
                            st.info(
                                f"Baseline loaded but below MIN_SHOTS ({b_shots} < {MIN_SHOTS}). "
                                "Phase 6 deltas will be skipped until baseline is re-tested."
                            )
                    except Exception:
                        baseline_row = None

                # Candidates must meet min shots
                cand = lab_df[lab_df["Shaft ID"] != "Current Baseline"].copy()
                if "Shot Count" in cand.columns:
                    def _shots_ok(x):
                        try:
                            return int(float(x or 0)) >= MIN_SHOTS
                        except Exception:
                            return False
                    cand = cand[cand["Shot Count"].apply(_shots_ok)]

                if len(cand) < 1:
                    st.warning(f"Add at least 1 candidate shaft test with Shot Count ≥ {MIN_SHOTS}.")
                elif "Smash Factor" not in cand.columns:
                    st.warning("Smash Factor missing from TrackMan export — cannot pick a winner.")
                else:
                    top_idx = cand["Smash Factor"].astype(float).idxmax()
                    winner_row = cand.loc[top_idx]
                    winner_name = winner_row.get("Shaft ID", "Winner")

                    # ---------- SD Threshold Gating ----------
                    def _f(row, k):
                        try:
                            return float(row.get(k, 0) or 0)
                        except Exception:
                            return 0.0

                    ftp_sd = _f(winner_row, "Face To Path SD")
                    carry_sd = _f(winner_row, "Carry SD")
                    smash_sd = _f(winner_row, "Smash Factor SD")

                    issues = []
                    if ftp_sd and ftp_sd > WARN_FACE_TO_PATH_SD:
                        issues.append(f"Face-to-Path SD {ftp_sd:.2f} > {WARN_FACE_TO_PATH_SD:.2f}")
                    if carry_sd and carry_sd > WARN_CARRY_SD:
                        issues.append(f"Carry SD {carry_sd:.1f} > {WARN_CARRY_SD:.1f}")
                    if smash_sd and smash_sd > WARN_SMASH_SD:
                        issues.append(f"Smash SD {smash_sd:.3f} > {WARN_SMASH_SD:.3f}")

                    if issues:
                        st.warning("⚠️ Data quality is not good enough to declare a winner yet.")
                        st.write("**Re-test recommended:**")
                        for it in issues:
                            st.write(f"- {it}")
                        st.info(
                            "Tip: tighten controls (same target/ball/head, remove obvious mishits using Use In Stat, "
                            "and collect more shots)."
                        )
                    else:
                        st.success(
                            f"🏆 **Efficiency Winner:** {winner_name} "
                            f"(Smash {winner_row.get('Smash Factor','')})"
                        )

                        if "Face To Path SD" in cand.columns:
                            try:
                                most_stable = cand.loc[cand["Face To Path SD"].astype(float).idxmin()]["Shaft ID"]
                                st.info(f"🛡️ **Most Stable (Face-to-Path SD):** {most_stable}")
                            except Exception:
                                pass

                        st.subheader("Phase 6 Optimization Suggestions")

                        recs = phase6_recommendations(
                            winner_row,
                            baseline_row=baseline_row,
                            club="6i",
                            environment=st.session_state.environment,
                        )
                        st.session_state.phase6_recs = recs

                        for r in recs:
                            css = "rec-warn" if r["severity"] == "warn" else "rec-info"
                            st.markdown(
                                f"<div class='{css}'><b>{r['type']}:</b> {r['text']}</div>",
                                unsafe_allow_html=True,
                            )
