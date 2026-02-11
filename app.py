import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# --- 1. THE ENGINE ---

def get_data_from_gsheet():
    try:
        creds_info = st.secrets["gcp_service_account"]
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        gc = gspread.authorize(creds)
        
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit'
        sh = gc.open_by_url(SHEET_URL)
        
        data = {}
        for tab in ['Heads', 'Shafts', 'Questions', 'Responses']:
            ws = sh.worksheet(tab)
            data[tab] = pd.DataFrame(ws.get_all_records())
        return data
    except Exception as e:
        st.error(f"📡 Data Load Error: {e}")
        return None

# --- 2. APP CONFIG ---
st.set_page_config(page_title="Patriot Fitting Engine", layout="wide")
all_data = get_data_from_gsheet()

if all_data:
    st.title("🇺🇸 Patriot Fitting Engine")
    
    # --- PHASE 1: DYNAMIC INTERVIEW ---
    st.header("📋 Phase 1: Player Interview")
    
    player_answers = {}
    
    with st.expander("Step 1: Complete Player Profile", expanded=True):
        # We loop through your 'Questions' tab
        questions_df = all_data['Questions']
        responses_df = all_data['Responses']
        
        col_q1, col_q2 = st.columns(2)
        
        for index, row in questions_df.iterrows():
            q_text = row['QuestionText']  # Assuming your column is named 'QuestionText'
            q_id = row['QuestionID']      # Assuming your column is named 'QuestionID'
            
            # Filter the Responses tab for options related to this QuestionID
            options = responses_df[responses_df['QuestionID'] == q_id]['ResponseText'].tolist()
            
            # Alternate placing questions in Column 1 and Column 2
            current_col = col_q1 if index % 2 == 0 else col_q2
            
            if options:
                player_answers[q_id] = current_col.selectbox(q_text, options)
            else:
                player_answers[q_id] = current_col.text_input(q_text)

    st.divider()

    # --- PHASE 2: TARGETS & DATA ---
    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("📊 Phase 2: Targets")
        
        # We can now use player_answers to set defaults
        # Example: If a specific question ID (e.g., Q1) is about "Miss"
        default_launch = 5.0
        if player_answers.get('Q1') == "Too High":
            default_launch = 3.5
            
        t_flex = st.number_input("Target FlexScore", value=6.0, step=0.1)
        t_launch = st.number_input("Target LaunchScore", value=default_launch, step=0.5)
        
        st.write("---")
        tm_file = st.file_uploader("Upload Trackman Data (Optional)", type=["xlsx", "csv"])

    with col2:
        st.subheader("🏆 Phase 3: Recommendations")
        if st.button("🔥 Run Full Analysis"):
            df_s = all_data['Shafts'].copy()
            
            # The Math
            df_s['Penalty'] = df_s.apply(
                lambda r: (abs(pd.to_numeric(r['FlexScore'], errors='coerce') - t_flex) * 40) + 
                          (abs(pd.to_numeric(r['LaunchScore'], errors='coerce') - t_launch) * 20), axis=1
            )
            
            results = df_s.sort_values('Penalty').head(5)
            st.table(results[['ShaftTag', 'FlexScore', 'LaunchScore', 'Penalty']])
            st.balloons()
