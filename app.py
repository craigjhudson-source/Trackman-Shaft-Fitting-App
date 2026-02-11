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
        
        # Mapping Q01-Q21 directly from session_state
        row = [
            str(datetime.datetime.now()),
            answers.get('Q01', ''), answers.get('Q02', ''), answers.get('Q03', ''),
            answers.get('Q04', ''), answers.get('Q05', ''), answers.get('Q06', ''),
            answers.get('Q07', ''), answers.get('Q08', ''), answers.get('Q09', ''),
            answers.get('Q10', ''), answers.get('Q11', ''), answers.get('Q12', ''),
            answers.get('Q13', ''), answers.get('Q14', ''), answers.get('Q15', ''),
            answers.get('Q16', ''), answers.get('Q17', ''), answers.get('Q18', ''),
            answers.get('Q19', ''), answers.get('Q20', ''), answers.get('Q21', ''),
            t_flex, t_launch
        ]
        ws.append_row(row)
        return True
    except Exception as e:
        st.error(f"⚠️ Failed to save: {e}")
        return False

# --- 2. SESSION INITIALIZATION ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
# Initialize all question keys as empty strings so they always exist
for i in range(1, 22):
    qid = f"Q{i:02d}"
    if qid not in st.session_state: st.session_state[qid] = ""

all_data = get_data_from_gsheet()

# --- 3. INTERVIEW UI ---
if all_data and not st.session_state.interview_complete:
    st.title("Americas Best Shaft Fitting Engine")
    
    categories = all_data['Questions']['Category'].unique().tolist()
    current_cat = categories[st.session_state.form_step]
    
    st.progress((st.session_state.form_step + 1) / len(categories))
    st.subheader(f"Step {st.session_state.form_step + 1}: {current_cat}")

    q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
    
    for _, row in q_df.iterrows():
        qid, qtext, qtype, qopts = row['QuestionID'], row['QuestionText'], row['InputType'], str(row['Options'])
        
        # Build options list
        options = []
        if qtype == "Dropdown":
            if "Config:" in qopts:
                options = sorted(list(set(all_data['Config'][qopts.split(":")[1]].dropna().astype(str))))
            elif "Heads" in qopts:
                if "Brand" in qtext: options = sorted(list(set(all_data['Heads']['Manufacturer'].astype(str))))
                else: 
                    brand = st.session_state.get('Q08', '')
                    options = sorted(list(set(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].astype(str))))
            elif "Shafts" in qopts:
                brand = st.session_state.get('Q10', '')
                if "Brand" in qtext: options = sorted(list(set(all_data['Shafts']['Brand'].astype(str))))
                elif "Flex" in qtext: options = list(dict.fromkeys(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Flex'].astype(str)))
                else: options = sorted(list(set(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Model'].astype(str))))
            elif "," in qopts: options = [x.strip() for x in qopts.split(",")]
            else: options = list(all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].astype(str))

        # Render Input
        if qtype == "Dropdown":
            # Set index to match current session state if already selected
            default_idx = 0
            if st.session_state[qid] in options: default_idx = options.index(st.session_state[qid])
            st.selectbox(qtext, options, index=default_idx, key=f"input_{qid}")
        elif qtype == "Numeric":
            st.number_input(qtext, value=float(st.session_state[qid]) if st.session_state[qid] else 0.0, key=f"input_{qid}")
        else:
            st.text_input(qtext, value=st.session_state[qid], key=f"input_{qid}")

    # Navigation Logic
    st.write("---")
    col1, col2, _ = st.columns([1,1,4])
    
    if col1.button("⬅️ Back") and st.session_state.form_step > 0:
        # Save current page inputs before going back
        for _, r in q_df.iterrows():
            st.session_state[r['QuestionID']] = st.session_state[f"input_{r['QuestionID']}"]
        st.session_state.form_step -= 1
        st.rerun()

    if st.session_state.form_step < len(categories) - 1:
        if col2.button("Next ➡️"):
            # Save current page inputs to permanent session_state
            for _, r in q_df.iterrows():
                st.session_state[r['QuestionID']] = st.session_state[f"input_{r['QuestionID']}"]
            st.session_state.form_step += 1
            st.rerun()
    else:
        if col2.button("🔥 Generate Prescription"):
            # Save final page inputs
            for _, r in q_df.iterrows():
                st.session_state[r['QuestionID']] = st.session_state[f"input_{r['QuestionID']}"]
            
            # Calculate logic scores
            tf, tl = 6.0, 5.0
            for i in range(1, 22):
                qid = f"Q{i:02d}"
                val = str(st.session_state[qid])
                resp = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == val)]
                if not resp.empty:
                    act = str(resp.iloc[0]['LogicAction'])
                    if "FlexScore:" in act: tf = float(act.split(":")[1])
                    if "LaunchScore:" in act: tl = float(act.split(":")[1])
            
            if save_lead_to_gsheet(st.session_state, tf, tl):
                st.session_state.interview_complete = True
                st.rerun()

# --- 4. RESULTS PHASE ---
elif st.session_state.interview_complete:
    st.success(f"Fitting Saved for {st.session_state['Q01']}!")
    # [Prescription and Trackman Lab Code remains the same...]
    if st.button("Start New Fitting"):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()
