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
        # Your specific Sheet URL
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
        
        # Mapping 21 questions (Q01-Q21) + Results (W, X)
        row = [
            str(datetime.datetime.now()),     # A: Timestamp
            answers.get('Q01', ''),          # B: Name
            answers.get('Q02', ''),          # C: Email
            answers.get('Q03', ''),          # D: Phone
            answers.get('Q04', ''),          # E: Handedness
            answers.get('Q05', ''),          # F: Glove Size
            answers.get('Q06', ''),          # G: Grip Size
            answers.get('Q07', ''),          # H: Ball
            answers.get('Q08', ''),          # I: Head Brand
            answers.get('Q09', ''),          # J: Head Model
            answers.get('Q10', ''),          # K: Shaft Brand
            answers.get('Q11', ''),          # L: Shaft Flex
            answers.get('Q12', ''),          # M: Shaft Model
            answers.get('Q13', ''),          # N: Club Length
            answers.get('Q14', ''),          # O: Swing Weight
            answers.get('Q15', 0),           # P: Carry
            answers.get('Q16', ''),          # Q: Current Flight
            answers.get('Q17', ''),          # R: Target Flight
            answers.get('Q18', ''),          # S: Miss
            answers.get('Q19', ''),          # T: Current Feel
            answers.get('Q20', ''),          # U: Target Feel
            answers.get('Q21', ''),          # V: Priority
            t_flex,                          # W: Result Flex
            t_launch                         # X: Result Launch
        ]
        ws.append_row(row)
        return True
    except Exception as e:
        st.error(f"⚠️ Failed to save to Sheet: {e}")
        return False

# --- 2. INITIALIZATION ---
st.set_page_config(page_title="Americas Best Shaft Fitting", layout="wide")
all_data = get_data_from_gsheet()

if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state:
    st.session_state['answers'] = {f"Q{i:02d}": "" for i in range(1, 22)}
    st.session_state['answers']['Q15'] = 0.0

# --- 3. QUESTIONNAIRE ---
if all_data:
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine")
        
        categories = all_data['Questions']['Category'].unique().tolist()
        current_cat = categories[st.session_state.form_step]
        
        st.progress((st.session_state.form_step + 1) / len(categories))
        st.subheader(f"Section: {current_cat}")

        q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
        
        # Render current page's questions
        for _, row in q_df.iterrows():
            qid, qtext, qtype, qopts = row['QuestionID'], row['QuestionText'], row['InputType'], str(row['Options'])
            
            if qtype == "Dropdown":
                options = [""] 
                if "Config:" in qopts:
                    col_name = qopts.split(":")[1]
                    options += all_data['Config'][col_name].dropna().unique().tolist()
                elif "Heads" in qopts:
                    if "Brand" in qtext: 
                        options += sorted(all_data['Heads']['Manufacturer'].unique().tolist())
                    else:
                        brand = st.session_state['answers'].get('Q08', '')
                        models = all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].unique().tolist()
                        options += sorted(models)
                elif "Shafts" in qopts:
                    brand = st.session_state['answers'].get('Q10', '')
                    if "Brand" in qtext: 
                        options += sorted(all_data['Shafts']['Brand'].unique().tolist())
                    elif "Flex" in qtext: 
                        flexes = all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Flex'].unique().tolist()
                        options += sorted(flexes)
                    else: 
                        models = all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Model'].unique().tolist()
                        options += sorted(models)
                elif "," in qopts: 
                    options += [x.strip() for x in qopts.split(",")]
                else: 
                    options += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].unique().tolist()
                
                # Retrieve previous answer if exists
                prev_val = st.session_state['answers'].get(qid, "")
                idx = options.index(prev_val) if prev_val in options else 0
                st.selectbox(qtext, options, index=idx, key=f"widget_{qid}")
            
            elif qtype == "Numeric":
                prev_val = float(st.session_state['answers'].get(qid, 0.0))
                st.number_input(qtext, value=prev_val, key=f"widget_{qid}")
            
            else: # Text (Name, Email, Phone)
                prev_val = str(st.session_state['answers'].get(qid, ""))
                st.text_input(qtext, value=prev_val, key=f"widget_{qid}")

        st.divider()
        c1, c2, _ = st.columns([1,1,4])

        # Logic for buttons to save state
        def save_current_page():
            for _, r in q_df.iterrows():
                qid = r['QuestionID']
                st.session_state['answers'][qid] = st.session_state[f"widget_{qid}"]

        if st.session_state.form_step > 0:
            if c1.button("⬅️ Back"):
                save_current_page()
                st.session_state.form_step -= 1
                st.rerun()
        
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"):
                save_current_page()
                st.session_state.form_step += 1
                st.rerun()
        else:
            if c2.button("🔥 Generate Prescription"):
                save_current_page()
                # Run Logic
                tf, tl = 6.0, 5.0
                for qid, ans in st.session_state['answers'].items():
                    logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == str(ans))]
                    if not logic.empty:
                        act = str(logic.iloc[0]['LogicAction'])
                        if "FlexScore:" in act: tf = float(act.split(":")[1])
                        if "LaunchScore:" in act: tl = float(act.split(":")[1])
                
                if save_lead_to_gsheet(st.session_state['answers'], tf, tl):
                    st.session_state.interview_complete = True
                    st.rerun()

    else:
        # --- 4. RESULTS VIEW ---
        st.title(f"🎯 Results for {st.session_state['answers'].get('Q01', 'Player')}")
        
        # Calculate scores again for display
        tf, tl = 6.0, 5.0
        for qid, ans in st.session_state['answers'].items():
            logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == str(ans))]
            if not logic.empty:
                act = str(logic.iloc[0]['LogicAction'])
                if "FlexScore:" in act: tf = float(act.split(":")[1])
                if "LaunchScore:" in act: tl = float(act.split(":")[1])

        df_s = all_data['Shafts'].copy()
        df_s['Penalty'] = (abs(pd.to_numeric(df_s['FlexScore'], errors='coerce') - tf) * 40) + \
                          (abs(pd.to_numeric(df_s['LaunchScore'], errors='coerce') - tl) * 20)
        
        st.success(f"Profile: Target Flex {tf} | Target Launch {tl}")
        recs = df_s.sort_values(['Penalty', 'Brand', 'Model']).head(5)
        st.dataframe(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Penalty']], hide_index=True, use_container_width=True)
        
        st.divider()
        col1, col2, _ = st.columns([1.5, 2, 4])
        
        if col1.button("⬅️ Back to Edit"):
            st.session_state.interview_complete = False
            st.rerun()
            
        if col2.button("🆕 Start New Fitting"):
            st.session_state['answers'] = {f"Q{i:02d}": "" for i in range(1, 22)}
            st.session_state['answers']['Q15'] = 0.0
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.rerun()
