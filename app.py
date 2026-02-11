import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import re

# --- 1. CONFIG & AUTH ---
st.set_page_config(page_title="Patriot Fitting App", layout="wide")

def get_data_from_gsheet():
    try:
        creds_info = st.secrets["gcp_service_account"]
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        gc = gspread.authorize(creds)
        
        # Opening your Master Database
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
        df_raw = pd.read_excel(file)
        # Find header row
        header_idx = df_raw.index[df_raw.iloc[:, 0] == 'Club Speed [mph]'].tolist()[0]
        df = pd.read_excel(file, skiprows=header_idx + 1)
        df = df.dropna(subset=['Club Speed [mph]'])
        
        return {
            "speed": df['Club Speed [mph]'].mean(),
            "launch": df['Launch Angle [deg]'].mean(),
            "spin": df['Spin Rate [rpm]'].mean(),
            "carry": df['Carry Flat - Length [yds]'].mean()
        }
    except:
        st.error("⚠️ Trackman Format Error: Please ensure you are uploading a standard Excel export.")
        return None

# --- 3. UI ---
all_data = get_data_from_gsheet()

if all_data:
    st.title("🇺🇸 Patriot Fitting Engine")
    
    with st.sidebar:
        st.header("1. Feel Priority")
        feel_label = st.select_slider(
            "How much does 'Feel' matter?",
            options=["1 - Do. Not. Care!", "2 - Sort of Meh", "3 - Either way", "4 - I mean yeah, mostly", "5 - America, Fuck Yeah!"],
            value="3 - Either way"
        )
        priority_map = {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0, "5": 5.0}
        feel_val = priority_map.get(feel_label[0], 3.0)

    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("2. Trackman Data")
        tm_file = st.file_uploader("Upload Trackman Excel", type="xlsx")
        
        if tm_file:
            stats = process_trackman(tm_file)
            if stats:
                st.info(f"Analyzed {tm_file.name}")
                st.metric("Avg Club Speed", f"{stats['speed']:.1f} mph")
                st.metric("Avg Carry", f"{stats['carry']:.1f} yds")
                
                # Formula: Speed / 10 - 4.0
                suggested_flex = round((stats['speed'] / 10) - 4.0, 1)
                t_flex = st.number_input("Target FlexScore", value=float(suggested_flex), step=0.1)
                
                # Logic: If spin is high, aim for a lower launch score
                suggested_launch = 5.0
                if stats['spin'] > 2800: suggested_launch = 3.5
                t_launch = st.number_input("Target LaunchScore", value=float(suggested_launch), step=0.5)

    with col2:
        st.subheader("3. Shaft Recommendations")
        if tm_file and st.button("🔥 Generate Fitting Report"):
            
            # SCORING ENGINE
            feel_mult = 0.25 + (feel_val * 0.25)
            flex_weight = 40 * feel_mult
            
            df_s = all_data['Shafts'].copy()
            for c in ['FlexScore', 'LaunchScore', 'StabilityIndex']:
                df_s[c] = pd.to_numeric(df_s[c], errors='coerce').fillna(0)
            
            # Calculate total penalty (Lower is better)
            df_s['Penalty'] = df_s.apply(
                lambda r: (abs(r['FlexScore'] - t_flex) * flex_weight) + 
                          (abs(r['LaunchScore'] - t_launch) * 15), axis=1
            )
            
            # Display Results
            results = df_s.sort_values('Penalty').head(5)
            st.dataframe(results[['ShaftTag', 'Penalty', 'FlexScore', 'LaunchScore']], hide_index=True)
            
            st.success(f"Fitting optimized for {feel_label}")
            st.balloons()
