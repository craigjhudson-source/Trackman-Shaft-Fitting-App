import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px

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

def get_ordered_list(series):
    return list(dict.fromkeys([str(x) for x in series.dropna() if str(x).strip() != ""]))

def get_sorted_list(series):
    return sorted(get_ordered_list(series))

# --- 2. APP SETUP ---
st.set_page_config(page_title="Patriot Fitting Engine", layout="wide")

if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False

all_data = get_data_from_gsheet()

if all_data:
    # --- PHASE 1: THE INTERVIEW ---
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine Powered By Greggory")
        st.header("📋 Phase 1: Player Interview")
        
        categories = all_data['Questions']['Category'].unique().tolist()
        total_steps = len(categories)
        current_cat = categories[st.session_state.form_step]

        st.progress((st.session_state.form_step + 1) / total_steps)
        st.subheader(f"Section: {current_cat}")

        q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
        col_q1, col_q2 = st.columns(2)
        
        for idx, row in q_df.reset_index().iterrows():
            q_id, q_text, q_type = row['QuestionID'], row['QuestionText'], row['InputType']
            q_opt_raw = str(row['Options'])
            
            if q_id not in st.session_state: st.session_state[q_id] = "" if q_type != "Numeric" else 0.0
            curr_col = col_q1 if idx % 2 == 0 else col_q2
            
            options = []
            if q_type == "Dropdown":
                if "Config:" in q_opt_raw: 
                    options = get_ordered_list(all_data['Config'][q_opt_raw.split(":")[1]])
                elif "Heads" in q_opt_raw:
                    brand_sel = st.session_state.get('Q08', '')
                    options = get_sorted_list(all_data['Heads']['Manufacturer']) if "Brand" in q_text else get_sorted_list(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand_sel]['Model'])
                elif "Shafts" in q_opt_raw:
                    brand_sel = st.session_state.get('Q10', '')
                    if "Brand" in q_text: options = get_sorted_list(all_data['Shafts']['Brand'])
                    elif "Flex" in q_text: options = get_ordered_list(all_data['Shafts'][all_data['Shafts']['Brand'] == brand_sel]['Flex'])
                    else: options = get_sorted_list(all_data['Shafts'][all_data['Shafts']['Brand'] == brand_sel]['Model'])
                elif "," in q_opt_raw: options = [x.strip() for x in q_opt_raw.split(",")]
                else: options = get_ordered_list(all_data['Responses'][all_data['Responses']['QuestionID'] == q_id]['ResponseOption'])

            if q_type == "Dropdown" and options:
                st.selectbox(q_text, options, key=q_id, on_change=st.rerun if "Brand" in q_text else None)
            elif q_type == "Numeric":
                st.number_input(q_text, key=q_id)
            else:
                st.text_input(q_text, placeholder=str(row.get('Placeholder','')), key=q_id)

        st.write("---")
        b_col1, b_col2, _ = st.columns([1, 1, 4])
        if st.session_state.form_step > 0:
            if b_col1.button("⬅️ Back"): st.session_state.form_step -= 1; st.rerun()
        if st.session_state.form_step < total_steps - 1:
            if b_col2.button("Next ➡️"): st.session_state.form_step += 1; st.rerun()
        else:
            if b_col2.button("🔥 Generate Prescription"): st.session_state.interview_complete = True; st.rerun()

    # --- PHASE 3: THE PRESCRIPTION & TESTING ---
    else:
        player_name = st.session_state.get('Q01', 'Player')
        st.title(f"🎯 Prescription: {player_name}")
        
        # 1. Target Score Calculation
        t_flex, t_launch = 6.0, 5.0
        for q_id in all_data['Questions']['QuestionID']:
            ans = str(st.session_state.get(q_id, ''))
            logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == q_id) & (all_data['Responses']['ResponseOption'] == ans)]
            if not logic.empty:
                action = str(logic.iloc[0]['LogicAction'])
                if "Target FlexScore:" in action: t_flex = float(action.split(":")[1])
                if "Target LaunchScore:" in action: t_launch = float(action.split(":")[1])

        # 2. Score All Shafts
        df_s = all_data['Shafts'].copy()
        df_s['Penalty'] = ((abs(pd.to_numeric(df_s['FlexScore'], errors='coerce') - t_flex) * 40) + 
                          (abs(pd.to_numeric(df_s['LaunchScore'], errors='coerce') - t_launch) * 20))
        
        # 3. Display Baseline vs. Prescription
        c_brand, c_model, c_flex = st.session_state.get('Q10'), st.session_state.get('Q12'), st.session_state.get('Q11')
        baseline = df_s[(df_s['Brand'] == c_brand) & (df_s['Model'] == c_model) & (df_s['Flex'] == c_flex)]
        
        col_res1, col_res2 = st.columns(2)
        with col_res1:
            st.subheader("📉 Current Baseline")
            if not baseline.empty:
                b = baseline.iloc[0]
                st.metric(f"{b['Brand']} {b['Model']}", f"Penalty: {round(b['Penalty'], 1)}")
                st.caption(f"Flex: {b['Flex']} | FlexScore: {b['FlexScore']} | Launch: {b['LaunchScore']}")
            else:
                st.info(f"Baseline: {c_brand} {c_model} ({c_flex})")

        with col_res2:
            st.subheader("🏆 Prescription (Top 5)")
            recs = df_s.sort_values('Penalty').head(5)
            st.dataframe(recs[['Brand', 'Model', 'Flex', 'Penalty']], use_container_width=True, hide_index=True)

        st.divider()

        # --- TESTING LAB (TRACKMAN ANALYSIS) ---
        st.header("🔬 Phase 2: Trackman Testing Lab")
        st.write("Pull the shafts listed above. Upload the Trackman export below to find the winner.")
        
        tm_file = st.file_uploader("Upload Trackman CSV", type=["csv"])
        
        if tm_file:
            tm_df = pd.read_csv(tm_file)
            # Standard Trackman column cleaning
            metrics = ["Carry Flat - Length [yds]", "Ball Speed [mph]", "Launch Angle [deg]", "Spin Rate [rpm]"]
            if all(m in tm_df.columns for m in metrics):
                summary = tm_df.groupby("ShaftTag")[metrics].mean().reset_index()
                st.subheader("📊 Performance Comparison")
                st.dataframe(summary.style.highlight_max(subset=["Carry Flat - Length [yds]", "Ball Speed [mph]"], color="lightgreen"), use_container_width=True)
                
                # Visual Chart
                fig = px.bar(summary, x='ShaftTag', y='Carry Flat - Length [yds]', color='ShaftTag', title="Carry Distance Comparison")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("CSV uploaded, but columns don't match standard Trackman export.")

        if st.button("🔄 Start New Fitting"):
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.rerun()
