import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# --- 1. DATA ENGINE ---
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

# Helper to safely clean and sort lists (Prevents TypeErrors)
def safe_list(series):
    # Converts all to string, drops empty values, gets unique, and sorts
    return sorted([str(x) for x in series.dropna().unique() if str(x).strip() != ""])

# --- 2. APP SETUP ---
st.set_page_config(page_title="Patriot Fitting Engine", layout="wide")
all_data = get_data_from_gsheet()

if all_data:
    st.title("🇺🇸 Patriot Fitting Engine")
    
    # --- PHASE 1: DYNAMIC INTERVIEW ---
    st.header("📋 Phase 1: Player Interview")
    player_answers = {}
    
    with st.expander("Step 1: Complete Player Profile", expanded=True):
        q_df = all_data['Questions']
        resp_df = all_data['Responses']
        conf_df = all_data['Config']
        
        col_q1, col_q2 = st.columns(2)
        
        for idx, row in q_df.iterrows():
            q_id = row['QuestionID']
            q_text = row['QuestionText']
            q_type = row['InputType']
            q_opt_raw = str(row['Options'])
            
            curr_col = col_q1 if idx % 2 == 0 else col_q2
            options = []

            # --- IMPROVED DYNAMIC DROPDOWN LOGIC ---
            if q_type == "Dropdown":
                if "Config:" in q_opt_raw:
                    conf_col = q_opt_raw.split(":")[1]
                    options = safe_list(conf_df[conf_col])
                
                # HEADS LOGIC (Q06 = Brand, Q07 = Model)
                elif "Heads" in q_opt_raw:
                    if "Brand" in q_text or "Manufacturer" in q_text:
                        options = safe_list(all_data['Heads']['Manufacturer'])
                    else: 
                        options = safe_list(all_data['Heads']['Model'])
                
                # SHAFTS LOGIC (Q08 = Brand, Q09 = Flex, Q10 = Model)
                elif "Shafts" in q_opt_raw:
                    if "Brand" in q_text:
                        options = safe_list(all_data['Shafts']['Brand'])
                    elif "Flex" in q_text:
                        options = safe_list(all_data['Shafts']['Flex'])
                    else: 
                        options = safe_list(all_data['Shafts']['Model'])
                
                elif "," in q_opt_raw:
                    options = [x.strip() for x in q_opt_raw.split(",")]
                else:
                    options = safe_list(resp_df[resp_df['QuestionID'] == q_id]['ResponseOption'])

          # RENDER INPUTS
            # We look for a placeholder in your sheet; if it's empty, we use an empty string
            placeholder_text = str(row['Placeholder']) if 'Placeholder' in q_df.columns else ""

            if q_type == "Dropdown" and options:
                player_answers[q_id] = curr_col.selectbox(q_text, options, key=q_id)
            
            elif q_type == "Numeric":
                # Note: Numeric inputs use 'value', text inputs use 'placeholder'
                # If you want a numeric example, it has to be a real number
                try:
                    p_val = int(placeholder_text) if placeholder_text.isdigit() else 0
                except:
                    p_val = 0
                player_answers[q_id] = curr_col.number_input(q_text, value=p_val, key=q_id)
            
            else:
                # This applies the example text to Email, Phone, and Name
                player_answers[q_id] = curr_col.text_input(
                    q_text, 
                    placeholder=placeholder_text, 
                    key=q_id
                )

    st.divider()

    # --- PHASE 2 & 3: TARGETS & RESULTS ---
    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("📊 Phase 2: Analysis Parameters")
        
        # Pull Logic from the Responses Tab
        target_flex = 6.0
        target_launch = 5.0
        
        for q_id, answer in player_answers.items():
            logic = resp_df[(resp_df['QuestionID'] == q_id) & (resp_df['ResponseOption'] == str(answer))]
            if not logic.empty:
                action = str(logic.iloc[0]['LogicAction'])
                if "Target FlexScore:" in action:
                    target_flex = float(action.split(":")[1])
                if "Target LaunchScore:" in action:
                    target_launch = float(action.split(":")[1])

        t_flex = st.number_input("Final Target Flex", value=target_flex, step=0.1)
        t_launch = st.number_input("Final Target Launch", value=target_launch, step=0.5)
        
        st.write("---")
        tm_file = st.file_uploader("Upload Trackman Data", type=["xlsx", "csv"])

    with col2:
        st.subheader("🏆 Phase 3: Recommendations")
        if st.button("🔥 Run Analysis"):
            df_s = all_data['Shafts'].copy()
            
            def calc_penalty(row):
                # Standard weighting: Flex is 2x as important as Launch
                p = (abs(pd.to_numeric(row['FlexScore'], errors='coerce') - t_flex) * 40)
                p += (abs(pd.to_numeric(row['LaunchScore'], errors='coerce') - t_launch) * 20)
                return p

            df_s['Penalty'] = df_s.apply(calc_penalty, axis=1)
            results = df_s.sort_values('Penalty').head(5)
            
            st.table(results[['ShaftTag', 'FlexScore', 'LaunchScore', 'Penalty']])
            st.balloons()
