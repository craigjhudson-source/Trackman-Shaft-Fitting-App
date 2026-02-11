import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

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

# HELPER: Keeps the EXACT order from your spreadsheet (Used for Config/Glove Size)
def get_ordered_list(series):
    # Removes empty cells but keeps the sequence from the sheet
    return list(dict.fromkeys([str(x) for x in series.dropna() if str(x).strip() != ""]))

# HELPER: Sorts Alphabetically (Used for Brands and Models)
def get_sorted_list(series):
    return sorted(get_ordered_list(series))

# --- 2. APP SETUP ---
st.set_page_config(page_title="Patriot Fitting Engine", layout="wide")

if 'form_step' not in st.session_state:
    st.session_state.form_step = 0

all_data = get_data_from_gsheet()

if all_data:
    st.title("🇺🇸 Patriot Fitting Engine")
    
    # --- PHASE 1: STEP-THROUGH INTERVIEW ---
    st.header("📋 Phase 1: Player Interview")
    
    categories = all_data['Questions']['Category'].unique().tolist()
    total_steps = len(categories)
    current_cat = categories[st.session_state.form_step]

    st.progress((st.session_state.form_step + 1) / total_steps)
    st.subheader(f"Step {st.session_state.form_step + 1}: {current_cat}")

    q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
    resp_df = all_data['Responses']
    conf_df = all_data['Config']
    
    col_q1, col_q2 = st.columns(2)
    
    for idx, row in q_df.reset_index().iterrows():
        q_id = row['QuestionID']
        q_text = row['QuestionText']
        q_type = row['InputType']
        q_opt_raw = str(row['Options'])
        placeholder_text = str(row['Placeholder']) if 'Placeholder' in row else ""
        
        curr_col = col_q1 if idx % 2 == 0 else col_q2
        options = []

        # --- SMART DROPDOWN LOGIC ---
        if q_type == "Dropdown":
            # If it's from the Config tab, use the ORDERED list
            if "Config:" in q_opt_raw:
                conf_col = q_opt_raw.split(":")[1]
                options = get_ordered_list(conf_df[conf_col])
            
            # If it's Brands or Models, use the ALPHABETICAL list (Easier to find)
            elif "Heads" in q_opt_raw:
                options = get_sorted_list(all_data['Heads']['Manufacturer']) if "Brand" in q_text else get_sorted_list(all_data['Heads']['Model'])
            elif "Shafts" in q_opt_raw:
                if "Brand" in q_text: options = get_sorted_list(all_data['Shafts']['Brand'])
                elif "Flex" in q_text: options = get_ordered_list(all_data['Shafts']['Flex']) # Flex should be ordered!
                else: options = get_sorted_list(all_data['Shafts']['Model'])
            
            # Static comma-separated lists
            elif "," in q_opt_raw:
                options = [x.strip() for x in q_opt_raw.split(",")]
            else:
                options = get_ordered_list(resp_df[resp_df['QuestionID'] == q_id]['ResponseOption'])

        # Render Inputs
        if q_id not in st.session_state:
            st.session_state[q_id] = 0.0 if q_type == "Numeric" else ""

        if q_type == "Dropdown" and options:
            default_idx = options.index(st.session_state[q_id]) if st.session_state[q_id] in options else 0
            st.session_state[q_id] = curr_col.selectbox(q_text, options, index=default_idx, key=f"in_{q_id}")
        elif q_type == "Numeric":
            st.session_state[q_id] = curr_col.number_input(q_text, value=float(st.session_state[q_id]), key=f"in_{q_id}")
        else:
            st.session_state[q_id] = curr_col.text_input(q_text, value=st.session_state[q_id], placeholder=placeholder_text, key=f"in_{q_id}")

    # Navigation
    btn_col1, btn_col2, _ = st.columns([1, 1, 4])
    with btn_col1:
        if st.session_state.form_step > 0:
            if st.button("⬅️ Back"):
                st.session_state.form_step -= 1
                st.rerun()
    with btn_col2:
        if st.session_state.form_step < total_steps - 1:
            if st.button("Next ➡️"):
                st.session_state.form_step += 1
                st.rerun()

    st.divider()

    # --- PHASE 2 & 3: ANALYSIS ---
    col1, col2 = st.columns([1, 1.2])
    with col1:
        st.subheader("📊 Phase 2: Analysis Parameters")
        target_flex, target_launch = 6.0, 5.0
        for q_id in all_data['Questions']['QuestionID']:
            if q_id in st.session_state:
                ans = str(st.session_state[q_id])
                logic = resp_df[(resp_df['QuestionID'] == q_id) & (resp_df['ResponseOption'] == ans)]
                if not logic.empty:
                    action = str(logic.iloc[0]['LogicAction'])
                    if "Target FlexScore:" in action: target_flex = float(action.split(":")[1])
                    if "Target LaunchScore:" in action: target_launch = float(action.split(":")[1])

        t_flex = st.number_input("Final Target Flex", value=target_flex, step=0.1)
        t_launch = st.number_input("Final Target Launch", value=target_launch, step=0.5)
        tm_file = st.file_uploader("Upload Trackman Export", type=["xlsx", "csv"])

    with col2:
        st.subheader("🏆 Phase 3: Recommendations")
        if st.button("🔥 Run Analysis"):
            df_s = all_data['Shafts'].copy()
            df_s['Penalty'] = df_s.apply(lambda r: (abs(pd.to_numeric(r['FlexScore'], errors='coerce') - t_flex) * 40) + (abs(pd.to_numeric(r['LaunchScore'], errors='coerce') - t_launch) * 20), axis=1)
            results = df_s.sort_values('Penalty').head(5)
            st.table(results[['ShaftTag', 'FlexScore', 'LaunchScore', 'Penalty']])
            st.balloons()
