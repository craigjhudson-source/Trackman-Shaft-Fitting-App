import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime

# --- 1. DATA ENGINE ---
# Standardize scopes - Ensure "auth" is in the drive URL
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_data(ttl=600)
def get_data_from_gsheet():
    try:
        creds_info = st.secrets["gcp_service_account"]
        # Explicitly use the standardized SCOPES
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit'
        sh = gc.open_by_url(SHEET_URL)
        
        data = {
            'Heads': pd.DataFrame(sh.worksheet('Heads').get_all_records()),
            'Shafts': pd.DataFrame(sh.worksheet('Shafts').get_all_records()),
            'Questions': pd.DataFrame(sh.worksheet('Questions').get_all_records()),
            'Responses': pd.DataFrame(sh.worksheet('Responses').get_all_records()),
            'Config': pd.DataFrame(sh.worksheet('Config').get_all_records())
        }
        return data
    except Exception as e:
        st.error(f"📡 Data Load Error: {e}")
        return None

def save_lead_to_gsheet(answers, t_flex, t_launch):
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        ws = sh.worksheet('Fittings')
        
        # Prepare row data (Q01 to Q21)
        row = [str(datetime.datetime.now())]
        for i in range(1, 22):
            key = f"Q{i:02d}"
            row.append(answers.get(key, ""))
        row.extend([t_flex, t_launch])
        
        ws.append_row(row)
        return True
    except Exception as e:
        st.error(f"⚠️ Save Error: {e}")
        return False

# --- 2. INITIALIZATION ---
st.set_page_config(page_title="Americas Best Shaft Fitting", layout="wide")
all_data = get_data_from_gsheet()

if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state:
    st.session_state['answers'] = {f"Q{i:02d}": "" for i in range(1, 22)}

# --- 3. QUESTIONNAIRE ---
if all_data:
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine")
        
        categories = all_data['Questions']['Category'].unique().tolist()
        current_cat = categories[st.session_state.form_step]
        q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]

        # Use a Form to force-capture all fields (Fix for Auto-fill issues)
        with st.form(key=f"form_step_{st.session_state.form_step}"):
            st.subheader(f"Section: {current_cat}")
            
            for _, row in q_df.iterrows():
                qid, qtext, qtype, qopts = row['QuestionID'], row['QuestionText'], row['InputType'], str(row['Options'])
                prev_val = st.session_state['answers'].get(qid, "")

                if qtype == "Dropdown":
                    options = [""]
                    if "Config:" in qopts:
                        col = qopts.split(":")[1]
                        options += all_data['Config'][col].dropna().unique().tolist()
                    elif "Heads" in qopts:
                        if "Brand" in qtext:
                            options += sorted(all_data['Heads']['Manufacturer'].unique().tolist())
                        else:
                            brand = st.session_state['answers'].get('Q08', "")
                            if brand: options += sorted(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].unique().tolist())
                    elif "Shafts" in qopts:
                        brand = st.session_state['answers'].get('Q10', "")
                        if "Brand" in qtext:
                            options += sorted(all_data['Shafts']['Brand'].unique().tolist())
                        elif brand:
                            if "Flex" in qtext:
                                options += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Flex'].unique().tolist())
                            else:
                                options += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Model'].unique().tolist())
                    elif "," in qopts:
                        options += [x.strip() for x in qopts.split(",")]
                    else:
                        options += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].unique().tolist()
                    
                    idx = options.index(prev_val) if prev_val in options else 0
                    st.session_state['answers'][qid] = st.selectbox(qtext, options, index=idx)

                elif qtype == "Numeric":
                    val = float(prev_val) if prev_val else 0.0
                    st.session_state['answers'][qid] = st.number_input(qtext, value=val)
                
                else: # Text Inputs
                    st.session_state['answers'][qid] = st.text_input(qtext, value=str(prev_val))

            # Form Buttons
            c1, c2, _ = st.columns([1,1,4])
            if st.session_state.form_step < len(categories) - 1:
                if st.form_submit_button("Next ➡️"):
                    st.session_state.form_step += 1
                    st.rerun()
            else:
                if st.form_submit_button("🔥 Generate Prescription"):
                    # Calculate Logic
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

        # Back button (outside form)
        if st.session_state.form_step > 0:
            if st.button("⬅️ Back"):
                st.session_state.form_step -= 1
                st.rerun()

    else:
        # --- 4. RESULTS VIEW ---
        st.title(f"🎯 Fitting Results: {st.session_state['answers'].get('Q01', 'Player')}")
        
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
        
        st.success(f"Target Flex: {tf} | Target Launch: {tl}")
        recs = df_s.sort_values(['Penalty', 'Brand', 'Model']).head(5)
        st.dataframe(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Launch', 'Spin']], hide_index=True, use_container_width=True)
        
        col1, col2, _ = st.columns([1.5, 2, 4])
        if col1.button("⬅️ Back to Edit"):
            st.session_state.interview_complete = False
            st.rerun()
        if col2.button("🆕 Start New Fitting"):
            st.session_state['answers'] = {f"Q{i:02d}": "" for i in range(1, 22)}
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.rerun()
