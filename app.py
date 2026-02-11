import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# --- 1. THE ENGINE (Functions) ---

def get_data_from_gsheet():
    try:
        creds_info = st.secrets["gcp_service_account"]
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        gc = gspread.authorize(creds)
        
        # Your Master Sheet
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

def process_trackman(file):
    try:
        if file.name.endswith('.csv'):
            df_raw = pd.read_csv(file)
        else:
            df_raw = pd.read_excel(file)
            
        header_row = None
        for i in range(min(len(df_raw), 50)):
            if 'Club Speed [mph]' in df_raw.iloc[i].values:
                header_row = i
                break
        
        if header_row is not None:
            file.seek(0)
            if file.name.endswith('.csv'):
                df = pd.read_csv(file, skiprows=header_row + 1)
            else:
                df = pd.read_excel(file, skiprows=header_row + 1)
            df = df.dropna(subset=['Club Speed [mph]'])
            return {
                "speed": pd.to_numeric(df['Club Speed [mph]'], errors='coerce').mean(),
                "launch": pd.to_numeric(df['Launch Angle [deg]'], errors='coerce').mean(),
                "spin": pd.to_numeric(df['Spin Rate [rpm]'], errors='coerce').mean()
            }
    except Exception as e:
        st.error(f"⚠️ Parsing Error: {e}")
        return None

# --- 2. APP CONFIG ---
st.set_page_config(page_title="Patriot Fitting Engine", layout="wide")

# --- 3. THE DASHBOARD (UI) ---
all_data = get_data_from_gsheet()

if all_data:
    st.title("🇺🇸 Patriot Fitting Engine")
    
    # PHASE 1: THE INTERVIEW
    st.header("📋 Phase 1: Player Interview")
    with st.expander("Step 1: Baseline & Goals", expanded=True):
        col_int1, col_int2 = st.columns(2)
        with col_int1:
            player_name = st.text_input("Player Name", "John Doe")
            current_miss = st.selectbox("Typical Big Miss", ["Slice/Fade", "Hook/Draw", "Thin", "Heavy", "Too High", "Too Low"])
        with col_int2:
            desired_outcome = st.multiselect("Goals", ["Distance", "Tighten Dispersion", "Lower Flight", "Higher Flight", "More Feel"])

    st.divider()

    # PHASE 2 & 3: DATA & RECOMMENDATIONS
    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("📊 Phase 2: Trackman Data")
        tm_file = st.file_uploader("Upload Trackman Export", type=["xlsx", "csv"])
        
        # Auto-adjust logic for targets
        initial_launch = 5.0
        if "Lower Flight" in desired_outcome or current_miss == "Too High":
            initial_launch = 3.5
        elif "Higher Flight" in desired_outcome or current_miss == "Too Low":
            initial_launch = 6.5

        st.subheader("🎯 Refine Targets")
        t_flex = st.number_input("Target FlexScore", value=6.0, step=0.1)
        t_launch = st.number_input("Target LaunchScore", value=initial_launch, step=0.5)

    with col2:
        st.subheader("🏆 Phase 3: Recommendations")
        if st.button("🔥 Run Full Analysis"):
            df_s = all_data['Shafts'].copy()
            # The Math: Lower Penalty is better
            df_s['Penalty'] = df_s.apply(
                lambda r: (abs(pd.to_numeric(r['FlexScore'], errors='coerce') - t_flex) * 40) + 
                          (abs(pd.to_numeric(r['LaunchScore'], errors='coerce') - t_launch) * 20), axis=1
            )
            results = df_s.sort_values('Penalty').head(5)
            
            st.table(results[['ShaftTag', 'FlexScore', 'LaunchScore', 'Penalty']])
            st.success(f"Analysis Complete for {player_name}")
            st.balloons()
