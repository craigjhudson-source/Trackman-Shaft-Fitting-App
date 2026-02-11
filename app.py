import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime

# --- 1. CONFIGURATION & DATA CONNECTION ---
st.set_page_config(page_title="Patriot Golf Fitting Engine", layout="wide", page_icon="⛳")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

@st.cache_data(ttl=600)
def get_data_from_gsheet():
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit'
        sh = gc.open_by_url(SHEET_URL)
        return {
            'Heads': pd.DataFrame(sh.worksheet('Heads').get_all_records()),
            'Shafts': pd.DataFrame(sh.worksheet('Shafts').get_all_records()),
            'Questions': pd.DataFrame(sh.worksheet('Questions').get_all_records()),
            'Responses': pd.DataFrame(sh.worksheet('Responses').get_all_records()),
            'Config': pd.DataFrame(sh.worksheet('Config').get_all_records())
        }
    except Exception as e:
        st.error(f"📡 Data Connection Error: {e}"); return None

def save_lead_to_gsheet(answers, t_flex, t_launch):
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        ws = sh.worksheet('Fittings')
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp] + [answers.get(f"Q{i:02d}", "") for i in range(1, 22)] + [t_flex, t_launch]
        ws.append_row(row); return True
    except: return False

# --- 2. STATE MANAGEMENT ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state.answers = {f"Q{i:02d}": "" for i in range(1, 22)}

all_data = get_data_from_gsheet()

def sync_answers(q_list):
    for qid in q_list:
        key = f"widget_{qid}"
        if key in st.session_state: st.session_state.answers[qid] = st.session_state[key]

# --- 3. QUESTIONNAIRE UI ---
if all_data:
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine")
        categories = all_data['Questions']['Category'].unique().tolist()
        st.progress(st.session_state.form_step / len(categories))
        current_cat = categories[st.session_state.form_step]
        q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
        
        for _, row in q_df.iterrows():
            qid, qtext, qtype, qopts = row['QuestionID'], row['QuestionText'], row['InputType'], str(row['Options'])
            ans_val = st.session_state.answers.get(qid, "")
            if qtype == "Dropdown":
                opts = [""]
                if "Config:" in qopts: opts += all_data['Config'][qopts.split(":")[1]].dropna().unique().tolist()
                elif "Heads" in qopts:
                    brand = st.session_state.get("widget_Q08", st.session_state.answers.get("Q08", ""))
                    opts += sorted(all_data['Heads']['Manufacturer'].unique().tolist()) if "Brand" in qtext else sorted(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].unique().tolist()) if brand else []
                elif "Shafts" in qopts:
                    brand = st.session_state.get("widget_Q10", st.session_state.answers.get("Q10", ""))
                    if "Brand" in qtext: opts += sorted(all_data['Shafts']['Brand'].unique().tolist())
                    elif "Flex" in qtext: opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Flex'].unique().tolist()) if brand else []
                    else: opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Model'].unique().tolist()) if brand else []
                else: opts += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].unique().tolist()
                st.selectbox(qtext, opts, index=opts.index(ans_val) if ans_val in opts else 0, key=f"widget_{qid}")
            elif qtype == "Numeric": st.number_input(qtext, value=float(ans_val) if ans_val else 0.0, key=f"widget_{qid}")
            else: st.text_input(qtext, value=str(ans_val), key=f"widget_{qid}")

        st.divider()
        c1, c2, _ = st.columns([1,1,4])
        if c1.button("⬅️ Back") and st.session_state.form_step > 0:
            sync_answers(q_df['QuestionID'].tolist()); st.session_state.form_step -= 1; st.rerun()
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"):
                sync_answers(q_df['QuestionID'].tolist()); st.session_state.form_step += 1; st.rerun()
        else:
            if c2.button("🔥 Generate Prescription"):
                sync_answers([f"Q{i:02d}" for i in range(1, 22)])
                f_tf, f_tl = 6.0, 5.0
                for qid, ans in st.session_state.answers.items():
                    logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == str(ans))]
                    if not logic.empty:
                        act = str(logic.iloc[0]['LogicAction'])
                        if "FlexScore:" in act: f_tf = float(act.split(":")[1])
                        if "LaunchScore:" in act: f_tl = float(act.split(":")[1])
                st.session_state.update({'final_tf': f_tf, 'final_tl': f_tl, 'interview_complete': True}); save_lead_to_gsheet(st.session_state.answers, f_tf, f_tl); st.rerun()

    else:
        # --- 4. MASTER FITTER RESULTS VIEW ---
        st.title(f"🎯 Fitting Report: {st.session_state.answers.get('Q01', 'Player')}")
        
        # RESTORED: Input Verification Summary
        st.subheader("📋 Input Verification Summary")
        sum_col1, sum_col2 = st.columns(2)
        with sum_col1:
            st.markdown("##### **Player & Current Setup**")
            st.write(f"**Current Head:** {st.session_state.answers.get('Q08', '')} {st.session_state.answers.get('Q09', '')}")
            st.write(f"**Current Shaft:** {st.session_state.answers.get('Q10', '')} {st.session_state.answers.get('Q12', '')}")
        with sum_col2:
            st.markdown("##### **Performance & Goals**")
            carry = float(st.session_state.answers.get('Q15', 0))
            miss = st.session_state.answers.get('Q18', "Straight")
            st.write(f"**6i Carry:** :red[{carry} yards]"); st.write(f"**Primary Miss:** :orange[{miss}]")
        
        st.divider()

        # Engine Logic
        tf, tl = st.session_state.final_tf, st.session_state.final_tl
        df_s = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'StabilityIndex', 'Weight (g)', 'EI_Tip', 'Torque']:
            df_s[col] = pd.to_numeric(df_s[col], errors='coerce')

        df_s['Penalty'] = (abs(df_s['FlexScore'] - tf) * 150) + (abs(df_s['LaunchScore'] - tl) * 30)
        if miss in ["Push", "Slice"]:
            df_s.loc[df_s['EI_Tip'] > 12.5, 'Penalty'] += 200
            df_s.loc[df_s['Torque'] < 1.6, 'Penalty'] += 100
        if miss in ["Hook", "Pull"]:
            df_s['Penalty'] += (df_s['Torque'] * 150)
            df_s.loc[df_s['StabilityIndex'] < 8.0, 'Penalty'] += 200

        df_s['BrandRank'] = df_s.groupby('Brand')['Penalty'].rank(method='first')
        df_s.loc[df_s['BrandRank'] == 1, 'Penalty'] -= 20
        recs = df_s.sort_values(['Penalty', 'FlexScore'], ascending=[True, False]).head(5).copy()

        def generate_verdict(row):
            if miss in ["Push", "Slice"] and row['EI_Tip'] < 11.5: return "✅ Release Assistant"
            if miss in ["Hook", "Pull"] and row['StabilityIndex'] > 8.5: return "🛡️ Stability King"
            if row['Weight (g)'] < 100 and carry > 175: return "⚡ Speed Play (Lightweight)"
            return "🎯 Balanced Fit"

        recs['Verdict'] = recs.apply(generate_verdict, axis=1)

        st.subheader("🚀 Recommended Prescription")
        st.table(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Verdict', 'Launch', 'Torque']])

        # Narrative Summary
        st.info(f"**Expert Analysis for {st.session_state.answers.get('Q01')}:** Because your primary miss is a **{miss}**, the engine prioritized shafts that help {'square the clubface' if miss in ['Push', 'Slice'] else 'stabilize the clubhead'}. With a **{carry} yd** carry, we matched you with a **{tf} FlexScore**. Top pick **{recs.iloc[0]['Brand']}** selected for its ideal Torque/Tip ratio.")

        # RESTORED: Navigation Buttons
        st.divider()
        b1, b2, _ = st.columns([1,1,4])
        if b1.button("✏️ Edit Survey"):
            st.session_state.interview_complete = False; st.session_state.form_step = 0; st.rerun()
        if b2.button("🆕 New Fitting"):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.rerun()
