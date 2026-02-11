import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import datetime

# --- 1. DATA ENGINE ---
@st.cache_data(ttl=600)
def get_data_from_gsheet():
    try:
        creds_info = st.secrets["gcp_service_account"]
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        gc = gspread.authorize(creds)
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit'
        sh = gc.open_by_url(SHEET_URL)
        data = {}
        for tab in ['Heads', 'Shafts', 'Questions', 'Responses', 'Config']:
            ws = sh.worksheet(tab)
            data[tab] = pd.DataFrame(ws.get_all_records())
        return data
    except Exception as e:
        st.error(f"📡 Data Load Error: {e}")
        return None

def save_lead_to_gsheet(answers, t_flex, t_launch):
    try:
        creds_info = st.secrets["gcp_service_account"]
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        ws = sh.worksheet('Fittings')
        
        # FIXED COLUMN ORDER - Matches your Fittings Tab exactly
        row = [
            str(datetime.datetime.now()),
            answers.get('Q01', ''), answers.get('Q02', ''), answers.get('Q03', ''), # Name, Email, Phone
            answers.get('Q04', ''), answers.get('Q05', ''), answers.get('Q06', ''), # Hand, Glove, Grip
            answers.get('Q07', ''), answers.get('Q08', ''), answers.get('Q09', ''), # Ball, Head Brand, Model
            answers.get('Q10', ''), answers.get('Q11', ''), answers.get('Q12', ''), # Shaft Brand, Flex, Model
            answers.get('Q13', ''), answers.get('Q14', ''), answers.get('Q15', ''), # Length, SW, Carry
            answers.get('Q16', ''), answers.get('Q17', ''), answers.get('Q18', ''), # Flight, Target, Miss
            answers.get('Q19', ''), answers.get('Q20', ''), answers.get('Q21', ''), # Feel, Target Feel, Priority
            t_flex, t_launch
        ]
        ws.append_row(row)
        return True
    except Exception as e:
        st.error(f"⚠️ Sheet Sync Failed: {e}")
        return False

# --- 2. STATE MANAGEMENT ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False

# Initialize all Q-keys so they never error out
for i in range(1, 22):
    key = f"Q{i:02d}"
    if key not in st.session_state: st.session_state[key] = ""

all_data = get_data_from_gsheet()

# --- 3. UI LAYOUT ---
if all_data:
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine")
        
        categories = ["Personal", "Current Club", "Performance", "Feel"]
        current_cat = categories[st.session_state.form_step]
        
        st.progress((st.session_state.form_step + 1) / len(categories))
        st.subheader(f"Section: {current_cat}")

        # Filter questions for this category
        q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
        
        # Use a form to capture all inputs at once for this page
        with st.container():
            for _, row in q_df.iterrows():
                qid, qtext, qtype, qopts = row['QuestionID'], row['QuestionText'], row['InputType'], str(row['Options'])
                
                # Logic for Dropdowns (Brands/Models/Configs)
                if qtype == "Dropdown":
                    options = []
                    if "Config:" in qopts:
                        options = list(all_data['Config'][qopts.split(":")[1]].dropna().unique())
                    elif "Heads" in qopts:
                        if "Brand" in qtext: options = sorted(list(all_data['Heads']['Manufacturer'].unique()))
                        else:
                            brand = st.session_state.get('Q08', '')
                            options = sorted(list(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].unique()))
                    elif "Shafts" in qopts:
                        brand = st.session_state.get('Q10', '')
                        if "Brand" in qtext: options = sorted(list(all_data['Shafts']['Brand'].unique()))
                        elif "Flex" in qtext: options = list(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Flex'].unique())
                        else: options = sorted(list(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Model'].unique()))
                    elif "," in qopts: options = [x.strip() for x in qopts.split(",")]
                    
                    # Ensure selection persists
                    idx = 0
                    if st.session_state[qid] in options: idx = options.index(st.session_state[qid])
                    st.selectbox(qtext, options, index=idx, key=qid)
                
                elif qtype == "Numeric":
                    val = float(st.session_state[qid]) if st.session_state[qid] else 0.0
                    st.number_input(qtext, value=val, key=qid)
                else:
                    st.text_input(qtext, value=st.session_state[qid], key=qid)

        st.write("---")
        c1, c2, _ = st.columns([1,1,4])
        if st.session_state.form_step > 0:
            if c1.button("⬅️ Back"):
                st.session_state.form_step -= 1
                st.rerun()
        
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"):
                st.session_state.form_step += 1
                st.rerun()
        else:
            if c2.button("🔥 Generate Prescription"):
                # Calculate Target Scores
                tf, tl = 6.0, 5.0 # Defaults
                for i in range(1, 22):
                    curr_qid = f"Q{i:02d}"
                    ans = str(st.session_state[curr_qid])
                    logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == curr_qid) & (all_data['Responses']['ResponseOption'] == ans)]
                    if not logic.empty:
                        act = str(logic.iloc[0]['LogicAction'])
                        if "FlexScore:" in act: tf = float(act.split(":")[1])
                        if "LaunchScore:" in act: tl = float(act.split(":")[1])
                
                # Save to Google Sheet
                if save_lead_to_gsheet(st.session_state, tf, tl):
                    st.session_state.interview_complete = True
                    st.rerun()

    # --- 4. RESULTS & EDITING ---
    else:
        st.title(f"🎯 Results for {st.session_state['Q01']}")
        
        # Calculate scores for display
        tf, tl = 6.0, 5.0
        for i in range(1, 22):
            curr_qid = f"Q{i:02d}"
            ans = str(st.session_state[curr_qid])
            logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == curr_qid) & (all_data['Responses']['ResponseOption'] == ans)]
            if not logic.empty:
                act = str(logic.iloc[0]['LogicAction'])
                if "FlexScore:" in act: tf = float(act.split(":")[1])
                if "LaunchScore:" in act: tl = float(act.split(":")[1])

        df_s = all_data['Shafts'].copy()
        df_s['Penalty'] = (abs(pd.to_numeric(df_s['FlexScore'], errors='coerce') - tf) * 40) + \
                          (abs(pd.to_numeric(df_s['LaunchScore'], errors='coerce') - tl) * 20)
        
        recs = df_s.sort_values('Penalty').head(5)
        st.subheader("Top 5 Recommended Shafts")
        st.table(recs[['Brand', 'Model', 'Flex', 'Penalty']])
        
        st.divider()
        col_edit, col_new = st.columns(2)
        if col_edit.button("✏️ Edit Answers (Go Back)"):
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.rerun()
            
        if col_new.button("🆕 Start New Fitting"):
            for i in range(1, 22): st.session_state[f"Q{i:02d}"] = ""
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.rerun()
