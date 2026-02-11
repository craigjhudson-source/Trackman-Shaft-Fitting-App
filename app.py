import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime

# --- 1. DATA CONNECTION ---
st.set_page_config(page_title="Patriot Golf Fitting Engine", layout="wide", page_icon="⛳")

def get_gsheet_client():
    """Helper to get the authorized gspread client."""
    creds_info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(
        creds_info, 
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
    return gspread.authorize(creds)

@st.cache_data(ttl=600)
def get_data_from_gsheet():
    try:
        gc = get_gsheet_client()
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit'
        sh = gc.open_by_url(SHEET_URL)
        
        data = {
            'Heads': pd.DataFrame(sh.worksheet('Heads').get_all_records()),
            'Shafts': pd.DataFrame(sh.worksheet('Shafts').get_all_records()),
            'Questions': pd.DataFrame(sh.worksheet('Questions').get_all_records()),
            'Responses': pd.DataFrame(sh.worksheet('Responses').get_all_records()),
            'Config': pd.DataFrame(sh.worksheet('Config').get_all_records())
        }
        for df_key in data:
            data[df_key].columns = data[df_key].columns.str.strip()
        return data
    except Exception as e:
        st.error(f"📡 Connection Error: {e}"); return None

# NEW: Function to write data back to Google Sheets
def save_response_to_gsheet(answers_dict):
    try:
        gc = get_gsheet_client()
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit'
        sh = gc.open_by_url(SHEET_URL)
        resp_sheet = sh.worksheet('Responses') # Or 'Fittings' depending on your tab name
        
        # Prepare the row data: Timestamp, Player Name (Q01), then all answers
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Create a list of all answers in order of QuestionID
        # This assumes your Responses sheet columns match your QuestionIDs
        row_to_add = [timestamp]
        # We sort by QID to ensure data always goes into the right column
        sorted_qids = sorted(answers_dict.keys())
        for qid in sorted_qids:
            row_to_add.append(str(answers_dict[qid]))
        
        resp_sheet.append_row(row_to_add)
        return True
    except Exception as e:
        st.error(f"❌ Failed to save to Google Sheets: {e}")
        return False

# --- 2. STATE MANAGEMENT ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state.answers = {}

all_data = get_data_from_gsheet()

def sync_answers(q_list):
    for qid in q_list:
        key = f"widget_{qid}"
        if key in st.session_state: 
            st.session_state.answers[qid] = st.session_state[key]

# --- 3. DYNAMIC QUESTIONNAIRE ---
if all_data:
    q_master = all_data['Questions']
    categories = list(dict.fromkeys(q_master['Category'].tolist()))
    
    if not st.session_state.interview_complete:
        st.title("Patriot Golf Performance Fitting")
        st.progress(st.session_state.form_step / len(categories))
        
        current_cat = categories[st.session_state.form_step]
        q_df = q_master[q_master['Category'] == current_cat]
        st.subheader(f"Section: {current_cat}")
        
        for _, row in q_df.iterrows():
            qid = str(row['QuestionID']).strip()
            qtext, qtype, qopts = row['QuestionText'], row['InputType'], str(row['Options']).strip()
            ans_val = st.session_state.answers.get(qid, "")
            
            if qtype == "Dropdown":
                opts = [""]
                if "Config:" in qopts:
                    col_name = qopts.split(":")[1].strip()
                    opts += all_data['Config'][col_name].dropna().astype(str).tolist()
                elif "Heads" in qopts:
                    if "Brand" in qtext:
                        opts += sorted(all_data['Heads']['Manufacturer'].unique().tolist())
                    else:
                        brand = st.session_state.get("widget_Q08", st.session_state.answers.get("Q08", ""))
                        opts += sorted(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].unique().tolist()) if brand else []
                elif "Shafts" in qopts:
                    brand = st.session_state.get("widget_Q10", st.session_state.answers.get("Q10", ""))
                    if "Brand" in qtext: 
                        opts += sorted(all_data['Shafts']['Brand'].unique().tolist())
                    elif "Flex" in qtext: 
                        opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Flex'].unique().tolist()) if brand else []
                    else: 
                        opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Model'].unique().tolist()) if brand else []
                else:
                    opts += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].astype(str).tolist()
                st.selectbox(qtext, opts, index=opts.index(str(ans_val)) if str(ans_val) in opts else 0, key=f"widget_{qid}")
            elif qtype == "Numeric":
                st.number_input(qtext, value=float(ans_val) if ans_val else 0.0, key=f"widget_{qid}")
            else:
                st.text_input(qtext, value=str(ans_val), key=f"widget_{qid}")

        st.divider()
        c1, c2, _ = st.columns([1,1,4])
        if c1.button("⬅️ Back") and st.session_state.form_step > 0:
            sync_answers(q_df['QuestionID'].tolist()); st.session_state.form_step -= 1; st.rerun()
        
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"):
                sync_answers(q_df['QuestionID'].tolist()); st.session_state.form_step += 1; st.rerun()
        else:
            # UPDATED: This button now triggers the save
            if c2.button("🔥 Generate Prescription"):
                sync_answers(q_master['QuestionID'].tolist())
                # Trigger the save function here
                success = save_response_to_gsheet(st.session_state.answers)
                if success:
                    st.session_state.interview_complete = True
                    st.rerun()
                else:
                    st.error("Could not save fitting data. Please check your connection.")

    else:
        # --- 4. MASTER FITTER REPORT ---
        # (Rest of your original reporting logic remains the same)
        st.title(f"🎯 Fitting Report: {st.session_state.answers.get('Q01', 'Player')}")
        st.success("Fitting data successfully synced to Google Sheets!")
        # ... [Rest of your code]
