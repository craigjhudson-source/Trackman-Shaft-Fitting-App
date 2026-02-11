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
            
            # Select Column
            curr_col = col_q1 if idx % 2 == 0 else col_q2
            
            # DETERMINE OPTIONS
            options = []
            if q_type == "Dropdown":
                if "Config:" in q_opt_raw:
                    conf_col = q_opt_raw.split(":")[1]
                    options = conf_df[conf_col].replace('', pd.NA).dropna().tolist()
                elif "Dynamic from Heads" in q_opt_raw:
                    options = sorted(all_data['Heads']['Manufacturer'].unique().tolist())
                elif "Dynamic from Shafts" in q_opt_raw:
                    options = sorted(all_data['Shafts']['Brand'].unique().tolist())
                elif "," in q_opt_raw:
                    options = [x.strip() for x in q_opt_raw.split(",")]
                else:
                    # Fallback to Responses tab
                    options = resp_df[resp_df['QuestionID'] == q_id]['ResponseOption'].tolist()

            # RENDER INPUTS
            if q_type == "Dropdown" and options:
                player_answers[q_id] = curr_col.selectbox(q_text, options, key=q_id)
            elif q_type == "Numeric":
                player_answers[q_id] = curr_col.number_input(q_text, value=0, key=q_id)
            else:
                player_answers[q_id] = curr_col.text_input(q_text, key=q_id)

    st.divider()

    # --- PHASE 2 & 3: TARGETS & RESULTS ---
    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("📊 Phase 2: Analysis Parameters")
        
        # LOGIC MAPPING from Responses Tab
        # Automatically updates Target Flex/Launch based on Interview selections
        target_flex = 6.0
        target_launch = 5.0
        
        for q_id, answer in player_answers.items():
            logic = resp_df[(resp_df['QuestionID'] == q_id) & (resp_df['ResponseOption'] == str(answer))]
            if not logic.empty:
                action = logic.iloc[0]['LogicAction']
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
            
            # PENALTY CALCULATION
            def calc_penalty(row):
                p = (abs(pd.to_numeric(row['FlexScore'], errors='coerce') - t_flex) * 40)
                p += (abs(pd.to_numeric(row['LaunchScore'], errors='coerce') - t_launch) * 20)
                return p

            df_s['Penalty'] = df_s.apply(calc_penalty, axis=1)
            results = df_s.sort_values('Penalty').head(5)
            
            st.table(results[['ShaftTag', 'FlexScore', 'LaunchScore', 'Penalty']])
            st.balloons()
