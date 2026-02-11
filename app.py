import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
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
        
        # HARD-CODED COLUMN ORDER (A to X)
        # This ensures the Sheet is always organized exactly how you designed it.
        row = [
            str(datetime.datetime.now()),     # A: Timestamp
            answers.get('Q01', ''),          # B: Name
            answers.get('Q02', ''),          # C: Email
            answers.get('Q03', ''),          # D: Phone
            answers.get('Q04', ''),          # E: Player Handedness
            answers.get('Q05', ''),          # F: Glove Size
            answers.get('Q06', ''),          # G: Current Grip Size
            answers.get('Q07', ''),          # H: Current Ball
            answers.get('Q08', ''),          # I: Current Head Brand
            answers.get('Q09', ''),          # J: Current Head Model
            answers.get('Q10', ''),          # K: Current Shaft Brand
            answers.get('Q11', ''),          # L: Current Shaft Flex
            answers.get('Q12', ''),          # M: Current Shaft Model
            answers.get('Q13', ''),          # N: Club Length
            answers.get('Q14', ''),          # O: Swing Weight
            float(answers.get('Q15', 0)),    # P: Current 6i Carry (Number)
            answers.get('Q16', ''),          # Q: Current Flight
            answers.get('Q17', ''),          # R: Target Flight
            answers.get('Q18', ''),          # S: Primary Miss
            answers.get('Q19', ''),          # T: Current Shaft Feel
            answers.get('Q20', ''),          # U: Target Shaft Feel
            answers.get('Q21', ''),          # V: Feel Priority
            t_flex,                          # W: Engine Flex Score
            t_launch                         # X: Engine Launch Score
        ]
        ws.append_row(row)
        return True
    except Exception as e:
        st.error(f"⚠️ Failed to save to Sheet: {e}")
        return False

# --- 2. INITIALIZATION & STATE ---
st.set_page_config(page_title="Americas Best Shaft Fitting", layout="wide")
all_data = get_data_from_gsheet()

if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False

# This is the "Safety Guard" for types
if all_data and 'initialized' not in st.session_state:
    for _, row in all_data['Questions'].iterrows():
        qid = row['QuestionID']
        if row['InputType'] == "Numeric":
            st.session_state[qid] = 0.0
        else:
            st.session_state[qid] = ""
    st.session_state['initialized'] = True

# --- 3. UI LAYOUT ---
if all_data:
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine")
        
        # Categorize steps based on your Questions sheet
        categories = all_data['Questions']['Category'].unique().tolist()
        current_cat = categories[st.session_state.form_step]
        
        st.progress((st.session_state.form_step + 1) / len(categories))
        st.subheader(f"Section: {current_cat}")

        q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
        
        for _, row in q_df.iterrows():
            qid, qtext, qtype, qopts = row['QuestionID'], row['QuestionText'], row['InputType'], str(row['Options'])
            
            # --- INPUT RENDERING ---
            if qtype == "Dropdown":
                options = [""] # Blank default
                if "Config:" in qopts:
                    options += sorted(list(all_data['Config'][qopts.split(":")[1]].dropna().unique()))
                elif "Heads" in qopts:
                    if "Brand" in qtext: options += sorted(list(all_data['Heads']['Manufacturer'].unique()))
                    else:
                        brand = st.session_state.get('Q08', '')
                        options += sorted(list(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].unique()))
                elif "Shafts" in qopts:
                    brand = st.session_state.get('Q10', '')
                    if "Brand" in qtext: options += sorted(list(all_data['Shafts']['Brand'].unique()))
                    elif "Flex" in qtext: options += list(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Flex'].unique())
                    else: options += sorted(list(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Model'].unique()))
                elif "," in qopts: options += [x.strip() for x in qopts.split(",")]
                else: options += list(all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].unique())
                
                # Persistence logic for Dropdowns
                curr_val = st.session_state.get(qid, "")
                idx = options.index(curr_val) if curr_val in options else 0
                st.selectbox(qtext, options, index=idx, key=qid)
            
            elif qtype == "Numeric":
                # Ensure the value is NEVER a string to fix the TypeError
                val = st.session_state.get(qid, 0.0)
                if not isinstance(val, (int, float)): val = 0.0
                st.number_input(qtext, value=float(val), key=qid)
            else:
                st.text_input(qtext, value=st.session_state.get(qid, ""), key=qid)

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
                # Run Logic Calculations
                tf, tl = 6.0, 5.0 # Default scores
                for i in range(1, 22):
                    cid = f"Q{i:02d}"
                    ans = str(st.session_state.get(cid, ""))
                    logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == cid) & (all_data['Responses']['ResponseOption'] == ans)]
                    if not logic.empty:
                        act = str(logic.iloc[0]['LogicAction'])
                        if "FlexScore:" in act: tf = float(act.split(":")[1])
                        if "LaunchScore:" in act: tl = float(act.split(":")[1])
                
                # Save and complete
                if save_lead_to_gsheet(st.session_state, tf, tl):
                    st.session_state.interview_complete = True
                    st.rerun()

    # --- 4. RESULTS & RE-EDITING ---
    else:
        st.title(f"🎯 Fitting Results for {st.session_state.get('Q01', 'Player')}")
        
        # Display Current Target Scores
        tf, tl = 6.0, 5.0
        for i in range(1, 22):
            cid = f"Q{i:02d}"
            ans = str(st.session_state.get(cid, ""))
            logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == cid) & (all_data['Responses']['ResponseOption'] == ans)]
            if not logic.empty:
                act = str(logic.iloc[0]['LogicAction'])
                if "FlexScore:" in act: tf = float(act.split(":")[1])
                if "LaunchScore:" in act: tl = float(act.split(":")[1])

        df_s = all_data['Shafts'].copy()
        df_s['Penalty'] = (abs(pd.to_numeric(df_s['FlexScore'], errors='coerce') - tf) * 40) + \
                          (abs(pd.to_numeric(df_s['LaunchScore'], errors='coerce') - tl) * 20)
        
        st.info(f"Prescription Profile: Flex Target {tf} | Launch Target {tl}")
        recs = df_s.sort_values('Penalty').head(5)
        st.dataframe(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Penalty']], hide_index=True, use_container_width=True)
        
        st.divider()
        col_edit, col_new = st.columns(2)
        
        if col_edit.button("✏️ Edit/Change Answers"):
            # This keeps the data in memory but moves you back to page 1
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.rerun()
            
        if col_new.button("🆕 Start New Fitting"):
            # This wipes everything
            for k in list(st.session_state.keys()):
                if k.startswith("Q"):
                    q_info = all_data['Questions'][all_data['Questions']['QuestionID'] == k]
                    if not q_info.empty and q_info.iloc[0]['InputType'] == "Numeric":
                        st.session_state[k] = 0.0
                    else:
                        st.session_state[k] = ""
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.rerun()
