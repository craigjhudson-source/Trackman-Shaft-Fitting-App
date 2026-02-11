import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime

# --- 1. CONFIGURATION & DATA CONNECTION ---
st.set_page_config(page_title="Patriot Golf Fitting Engine", layout="wide", page_icon="⛳")

# Google Sheets Scopes
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

@st.cache_data(ttl=600)
def get_data_from_gsheet():
    """Fetch all data from the Google Sheet tabs."""
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        # Replace with your actual Spreadsheet URL
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
        st.error(f"📡 Data Connection Error: {e}")
        return None

def save_lead_to_gsheet(answers, t_flex, t_launch):
    """Saves the questionnaire results to the 'Fittings' tab."""
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        ws = sh.worksheet('Fittings')
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Build the row starting with timestamp, then Q01-Q21, then calculated targets
        row = [timestamp]
        for i in range(1, 22):
            qid = f"Q{i:02d}"
            row.append(answers.get(qid, ""))
        row.extend([t_flex, t_launch])
        
        ws.append_row(row)
        return True
    except Exception as e:
        st.error(f"💾 Save Error: {e}")
        return False

# --- 2. STATE MANAGEMENT ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state.answers = {f"Q{i:02d}": "" for i in range(1, 22)}

all_data = get_data_from_gsheet()

# Helper to sync widget data to session state
def sync_answers(q_list):
    for qid in q_list:
        key = f"widget_{qid}"
        if key in st.session_state:
            st.session_state.answers[qid] = st.session_state[key]

# --- 3. QUESTIONNAIRE UI ---
if all_data:
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine")
        
        categories = all_data['Questions']['Category'].unique().tolist()
        st.progress(st.session_state.form_step / len(categories))
        
        current_cat = categories[st.session_state.form_step]
        q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
        
        st.subheader(f"Section: {current_cat}")
        
        for _, row in q_df.iterrows():
            qid, qtext, qtype, qopts = row['QuestionID'], row['QuestionText'], row['InputType'], str(row['Options'])
            ans_val = st.session_state.answers.get(qid, "")
            
            if qtype == "Dropdown":
                opts = [""]
                if "Config:" in qopts:
                    opts += all_data['Config'][qopts.split(":")[1]].dropna().unique().tolist()
                elif "Heads" in qopts:
                    if "Brand" in qtext: opts += sorted(all_data['Heads']['Manufacturer'].unique().tolist())
                    else:
                        brand = st.session_state.get("widget_Q08", st.session_state.answers.get("Q08", ""))
                        opts += sorted(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].unique().tolist()) if brand else []
                elif "Shafts" in qopts:
                    brand = st.session_state.get("widget_Q10", st.session_state.answers.get("Q10", ""))
                    if "Brand" in qtext: opts += sorted(all_data['Shafts']['Brand'].unique().tolist())
                    elif "Flex" in qtext: opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Flex'].unique().tolist()) if brand else []
                    else: opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Model'].unique().tolist()) if brand else []
                else:
                    opts += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].unique().tolist()
                
                st.selectbox(qtext, opts, index=opts.index(ans_val) if ans_val in opts else 0, key=f"widget_{qid}")
            
            elif qtype == "Numeric":
                st.number_input(qtext, value=float(ans_val) if ans_val else 0.0, key=f"widget_{qid}")
            else:
                st.text_input(qtext, value=str(ans_val), key=f"widget_{qid}")

        # Navigation
        st.divider()
        c1, c2, _ = st.columns([1,1,4])
        if c1.button("⬅️ Back") and st.session_state.form_step > 0:
            sync_answers(q_df['QuestionID'].tolist())
            st.session_state.form_step -= 1
            st.rerun()
            
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"):
                sync_answers(q_df['QuestionID'].tolist())
                st.session_state.form_step += 1
                st.rerun()
        else:
            if c2.button("🔥 Generate Prescription"):
                sync_answers([f"Q{i:02d}" for i in range(1, 22)])
                # Calculate Targets
                f_tf, f_tl = 6.0, 5.0 # Defaults
                for qid, ans in st.session_state.answers.items():
                    logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == str(ans))]
                    if not logic.empty:
                        act = str(logic.iloc[0]['LogicAction'])
                        if "FlexScore:" in act: f_tf = float(act.split(":")[1])
                        if "LaunchScore:" in act: f_tl = float(act.split(":")[1])
                st.session_state.final_tf = f_tf
                st.session_state.final_tl = f_tl
                st.session_state.interview_complete = True
                save_lead_to_gsheet(st.session_state.answers, f_tf, f_tl)
                st.rerun()

    else:
        # --- 4. MASTER FITTER RECOMMENDATION ENGINE ---
        st.title(f"🎯 Fitting Report: {st.session_state.answers.get('Q01', 'Player')}")
        
        # Player Profile Constants
        tf = st.session_state.final_tf
        tl = st.session_state.final_tl
        miss = st.session_state.answers.get('Q18', "Straight")
        carry = float(st.session_state.answers.get('Q15', 0))
        
        # Data Processing
        df_s = all_data['Shafts'].copy()
        numeric_cols = ['FlexScore', 'LaunchScore', 'StabilityIndex', 'Weight (g)', 'EI_Tip', 'Torque']
        for col in numeric_cols: df_s[col] = pd.to_numeric(df_s[col], errors='coerce')

        # Baseline Penalty (Flex & Launch)
        df_s['Penalty'] = (abs(df_s['FlexScore'] - tf) * 150) + (abs(df_s['LaunchScore'] - tl) * 30)

        # Expert Logic: Anti-Push/Right Miss
        if miss in ["Push", "Slice"]:
            # Penalize ultra-stiff tips (DG style) and favor more active tips (Modus/KBS style)
            df_s.loc[df_s['EI_Tip'] > 12.5, 'Penalty'] += 200
            df_s.loc[df_s['Torque'] < 1.6, 'Penalty'] += 100
            # Boost shafts with a softer Tip Profile
            df_s.loc[df_s['EI_Tip'] < 11.0, 'Penalty'] -= 50

        # Expert Logic: Anti-Hook/Left Miss
        if miss in ["Hook", "Pull"]:
            # Penalize high torque and soft tips
            df_s['Penalty'] += (df_s['Torque'] * 150)
            df_s.loc[df_s['StabilityIndex'] < 8.0, 'Penalty'] += 200

        # Brand Variety Boost (Ensure Top 5 has different names)
        df_s['BrandRank'] = df_s.groupby('Brand')['Penalty'].rank(method='first', ascending=True)
        df_s.loc[df_s['BrandRank'] == 1, 'Penalty'] -= 20 # Give best-in-brand a head start

        # Generate Top 5
        recs = df_s.sort_values(['Penalty', 'FlexScore'], ascending=[True, False]).head(5).copy()

        # Verdict Generator
        def generate_verdict(row):
            if miss in ["Push", "Slice"] and row['EI_Tip'] < 11.5: return "✅ Release Assistant"
            if miss in ["Hook", "Pull"] and row['StabilityIndex'] > 8.5: return "🛡️ Stability King"
            if row['Weight (g)'] < 100 and carry > 175: return "⚡ Speed Play (Lightweight)"
            if "Nippon" in row['Brand'] or "KBS" in row['Brand']: return "💎 Premium Feel"
            return "🎯 Balanced Fit"

        recs['Verdict'] = recs.apply(generate_verdict, axis=1)

        # --- DISPLAY RESULTS ---
        st.subheader("📋 Profile Summary")
        c_sum1, c_sum2, c_sum3 = st.columns(3)
        c_sum1.metric("Target Flex", tf)
        c_sum2.metric("Target Launch", tl)
        c_sum3.metric("Primary Miss", miss)

        st.divider()
        st.subheader("🚀 Recommended Prescription")
        
        # Formatting for Display
        display_df = recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Verdict', 'Launch', 'Torque']]
        st.table(display_df)

        # Narrative Summary Box
        st.info(f"""
        **Expert Analysis for {st.session_state.answers.get('Q01')}:**
        Because your primary miss is a **{miss}**, the engine prioritized shafts that help 
        {'square the clubface' if miss in ['Push', 'Slice'] else 'stabilize the clubhead'} through impact. 
        With a **{carry} yard 6-iron carry**, we matched you with a **{tf} FlexScore** profile. 
        The top recommendation (**{recs.iloc[0]['Brand']} {recs.iloc[0]['Model']}**) was selected because its 
        technical profile (Torque: {recs.iloc[0]['Torque']} | Tip Stiffness: {recs.iloc[0]['EI_Tip']}) 
        is the mathematically ideal solution to your current delivery.
        """)

        # Reset Button
        if st.button("🆕 Start New Fitting"):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.rerun()
