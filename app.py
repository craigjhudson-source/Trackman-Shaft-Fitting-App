import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# --- 1. CONFIG & AUTH ---
st.set_page_config(page_title="Patriot Fitting Engine", layout="wide")

def get_data_from_gsheet():
    try:
        creds_info = st.secrets["gcp_service_account"]
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        gc = gspread.authorize(creds)
        
        # Open your specific sheet
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

# --- 2. TRACKMAN PARSER ---
def process_trackman(file):
    try:
        if file.name.endswith('.csv'):
            df_raw = pd.read_csv(file)
        else:
            df_raw = pd.read_excel(file)
            
        # Search for the row containing 'Club Speed [mph]'
        header_row = None
        for i in range(min(len(df_raw), 50)): # Check first 50 rows
            if 'Club Speed [mph]' in df_raw.iloc[i].values:
                header_row = i
                break
        
        if header_row is not None:
            # Re-read the file with correct headers
            file.seek(0) # Reset file pointer to start
            if file.name.endswith('.csv'):
                df = pd.read_csv(file, skiprows=header_row + 1)
            else:
                df = pd.read_excel(file, skiprows=header_row + 1)
                
            df = df.dropna(subset=['Club Speed [mph]'])
            
            return {
                "speed": pd.to_numeric(df['Club Speed [mph]'], errors='coerce').mean(),
                "launch": pd.to_numeric(df['Launch Angle [deg]'], errors='coerce').mean(),
                "spin": pd.to_numeric(df['Spin Rate [rpm]'], errors='coerce').mean(),
                "carry": pd.to_numeric(df['Carry Flat - Length [yds]'], errors='coerce').mean()
            }
    except Exception as e:
        st.error(f"⚠️ Parsing Error: {e}")
        return None

# --- 3. MAIN UI LOGIC ---
all_data = get_data_from_gsheet()

if all_data:
    st.title("🇺🇸 Patriot Fitting Engine")
    
    with st.sidebar:
        st.header("1. Feel Priority")
        feel_label = st.select_slider(
            "Impact of Feel:",
            options=["1 - Low", "2 - Med-Low", "3 - Neutral", "4 - High", "5 - Pure Feel"],
            value="3 - Neutral"
        )
        priority_map = {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0, "5": 5.0}
        feel_val = priority_map.get(feel_label[0], 3.0)

    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("2. Trackman Data")
        tm_file = st.file_uploader("Upload Trackman Export", type=["xlsx", "csv"])
        
        if tm_file:
            stats = process_trackman(tm_file)
            if stats:
                st.metric("Avg Club Speed", f"{stats['speed']:.1f} mph")
                # Auto-calculate targets
                s_flex = round((stats['speed'] / 10) - 4.0, 1)
                t_flex = st.number_input("Target FlexScore", value=float(s_flex), step=0.1)
                t_launch = st.number_input("Target LaunchScore", value=5.0, step=0.5)

    with col2:
        st.subheader("3. Results")
        if tm_file and st.button("Generate Report"):
            # Scoring
            df_s = all_data['Shafts'].copy()
            df_s['Penalty'] = df_s.apply(
                lambda r: (abs(pd.to_numeric(r['FlexScore'], errors='coerce') - t_flex) * 40) + 
                          (abs(pd.to_numeric(r['LaunchScore'], errors='coerce') - t_launch) * 15), axis=1
            )
            results = df_s.sort_values('Penalty').head(5)
            st.dataframe(results[['ShaftTag', 'FlexScore', 'LaunchScore']], hide_index=True)
            st.balloons()
