import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import datetime

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

def save_lead_to_gsheet(answers, t_flex, t_launch):
    try:
        creds_info = st.secrets["gcp_service_account"]
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        gc = gspread.authorize(creds)
        
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        ws = sh.worksheet('Fittings')
        
        # This order matches your "Fittings" tab headers exactly
        row = [
            str(datetime.datetime.now()), 
            answers.get('Q01', ''), answers.get('Q02', ''), answers.get('Q03', ''),
            answers.get('Q04', ''), answers.get('Q05', ''), answers.get('Q06', ''),
            answers.get('Q07', ''), answers.get('Q08', ''), answers.get('Q09', ''),
            answers.get('Q10', ''), answers.get('Q11', ''), answers.get('Q12', ''),
            answers.get('Q13', ''), answers.get('Q14', ''), answers.get('Q15', ''),
            answers.get('Q16', ''), answers.get('Q17', ''), answers.get('Q18', ''),
            answers.get('Q19', ''), answers.get('Q20', ''), answers.get('Q21', ''),
            t_flex, t_launch
        ]
        ws.append_row(row)
        return True
    except Exception as e:
        st.error(f"⚠️ Failed to save data: {e}")
        return False

# --- Helper Functions for Dropdowns ---
def get_ordered_list(series):
    return list(dict.fromkeys([str(x) for x in series.dropna() if str(x).strip() != ""]))

def get_sorted_list(series):
    return sorted(get_ordered_list(series))

# --- 2. APP SETUP ---
st.set_page_config(page_title="Americas Best Shaft Fitting Engine", layout="wide")

if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False

all_data = get_data_from_gsheet()

if all_data:
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine Powered By Greggory")
        st.header("📋 Phase 1: Player Interview")
        
        categories = all_data['Questions']['Category'].unique().tolist()
        current_cat = categories[st.session_state.form_step]

        st.progress((st.session_state.form_step + 1) / len(categories))
        st.subheader(f"Section: {current_cat}")

        q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
        col_q1, col_q2 = st.columns(2)
        
        for idx, row in q_df.reset_index().iterrows():
            q_id, q_text, q_type = row['QuestionID'], row['QuestionText'], row['InputType']
            q_opt_raw = str(row['Options'])
            curr_col = col_q1 if idx % 2 == 0 else col_q2
            
            # Setup dynamic options
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
                elif "," in q_opt_raw:
                    options = [x.strip() for x in q_opt_raw.split(",")]
                else:
                    options = get_ordered_list(all_data['Responses'][all_data['Responses']['QuestionID'] == q_id]['ResponseOption'])

            # Render input using the QuestionID as the key to bind it to session_state
            if q_type == "Dropdown" and options:
                curr_col.selectbox(q_text, options, key=q_id)
            elif q_type == "Numeric":
                curr_col.number_input(q_text, key=q_id)
            else:
                curr_col.text_input(q_text, key=q_id)

        st.write("---")
        b_col1, b_col2, _ = st.columns([1, 1, 4])
        if st.session_state.form_step > 0:
            if b_col1.button("⬅️ Back"): st.session_state.form_step -= 1; st.rerun()
        
        if st.session_state.form_step < len(categories) - 1:
            if b_col2.button("Next ➡️"): st.session_state.form_step += 1; st.rerun()
        else:
            if b_col2.button("🔥 Generate Prescription"):
                # 1. Calc Targets
                t_f, t_l = 6.0, 5.0
                for qid in all_data['Questions']['QuestionID']:
                    val = str(st.session_state.get(qid, ''))
                    logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == val)]
                    if not logic.empty:
                        action = str(logic.iloc[0]['LogicAction'])
                        if "Target FlexScore:" in action: t_f = float(action.split(":")[1])
                        if "Target LaunchScore:" in action: t_l = float(action.split(":")[1])
                
                # 2. Save and Move
                if save_lead_to_gsheet(st.session_state, t_f, t_l):
                    st.session_state.interview_complete = True
                    st.rerun()

    # --- PHASE 3: RESULTS ---
    else:
        player_name = st.session_state.get('Q01', 'Player')
        st.title(f"🎯 Fitting Prescription: {player_name}")
        
        # Re-calc targets for display
        t_flex, t_launch = 6.0, 5.0
        for q_id in all_data['Questions']['QuestionID']:
            val = str(st.session_state.get(q_id, ''))
            logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == q_id) & (all_data['Responses']['ResponseOption'] == val)]
            if not logic.empty:
                action = str(logic.iloc[0]['LogicAction'])
                if "Target FlexScore:" in action: t_flex = float(action.split(":")[1])
                if "Target LaunchScore:" in action: t_launch = float(action.split(":")[1])

        # Penalty Logic
        df_s = all_data['Shafts'].copy()
        df_s['FlexScore'] = pd.to_numeric(df_s['FlexScore'], errors='coerce')
        df_s['LaunchScore'] = pd.to_numeric(df_s['LaunchScore'], errors='coerce')
        df_s['Penalty'] = (abs(df_s['FlexScore'] - t_flex) * 40) + (abs(df_s['LaunchScore'] - t_launch) * 20)
        
        # Baseline Logic
        c_brand, c_model, c_flex = st.session_state.get('Q10'), st.session_state.get('Q12'), st.session_state.get('Q11')
        baseline = df_s[(df_s['Brand'] == c_brand) & (df_s['Model'] == c_model) & (df_s['Flex'] == c_flex)]
        
        col_res1, col_res2 = st.columns(2)
        with col_res1:
            st.subheader("📉 Current Baseline")
            if not baseline.empty:
                b = baseline.iloc[0]
                st.metric(f"{b['Brand']} {b['Model']}", f"Penalty: {round(b['Penalty'], 1)}")
            else:
                st.info(f"Baseline: {c_brand} {c_model} ({c_flex}) not in scoring database.")

        with col_res2:
            st.subheader("🏆 Prescription (Top 5)")
            recs = df_s.sort_values('Penalty').head(5)
            st.dataframe(recs[['Brand', 'Model', 'Flex', 'Penalty']], use_container_width=True, hide_index=True)

        st.divider()
        st.header("🔬 Phase 2: Trackman Testing Lab")
        tm_file = st.file_uploader("Upload Trackman Export", type=["csv"])
        
        if tm_file:
            tm_df = pd.read_csv(tm_file)
            metrics = ["Carry Flat - Length [yds]", "Ball Speed [mph]", "Launch Angle [deg]", "Spin Rate [rpm]"]
            if "ShaftTag" in tm_df.columns:
                summary = tm_df.groupby("ShaftTag")[metrics].mean().reset_index()
                st.dataframe(summary.style.highlight_max(subset=["Ball Speed [mph]", "Carry Flat - Length [yds]"], color="lightgreen"))
                fig = px.bar(summary, x="ShaftTag", y="Carry Flat - Length [yds]", title="Average Carry (yds)")
                st.plotly_chart(fig, use_container_width=True)

        if st.button("🔄 Start New Fitting"):
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.rerun()
