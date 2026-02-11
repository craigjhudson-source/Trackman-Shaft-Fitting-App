import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime

# --- 1. DATA CONNECTION ---
st.set_page_config(page_title="Patriot Golf Fitting Engine", layout="wide", page_icon="⛳")

@st.cache_data(ttl=600)
def get_data_from_gsheet():
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        gc = gspread.authorize(creds)
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
            if c2.button("🔥 Generate Prescription"):
                sync_answers(q_master['QuestionID'].tolist())
                st.session_state.interview_complete = True; st.rerun()

    else:
        # --- 4. MASTER FITTER REPORT ---
        st.title(f"🎯 Fitting Report: {st.session_state.answers.get('Q01', 'Player')}")
        
        with st.expander("📋 View Full Input Verification Summary", expanded=False):
            ver_cols = st.columns(3)
            for i, cat in enumerate(categories):
                with ver_cols[i % 3]:
                    st.markdown(f"**{cat}**")
                    cat_qs = q_master[q_master['Category'] == cat]
                    for _, q_row in cat_qs.iterrows():
                        ans = st.session_state.answers.get(str(q_row['QuestionID']).strip(), "—")
                        st.caption(f"{q_row['QuestionText']}: **{ans}**")

        # ENGINE LOGIC
        f_tf, f_tl, min_w, curr_w = 5.0, 5.0, 0, 115
        primary_miss = st.session_state.answers.get('Q17', '')
        carry_6i = 0.0

        try:
            carry_6i = float(st.session_state.answers.get('Q15', 0))
            if carry_6i >= 180: min_w, f_tf = 118, 7.0
            elif carry_6i >= 160: min_w, f_tf = 105, 6.0
            elif carry_6i < 140: f_tf = 4.0 
        except: pass

        # BRACKETING
        ideal_w = 115
        if carry_6i < 125: ideal_w = 70
        elif carry_6i < 145: ideal_w = 90
        elif carry_6i < 165: ideal_w = 105
        elif carry_6i < 185: ideal_w = 120
        else: ideal_w = 130

        c_brand, c_model = st.session_state.answers.get('Q10', ''), st.session_state.answers.get('Q12', '')
        curr_shaft_data = all_data['Shafts'][(all_data['Shafts']['Brand'] == c_brand) & (all_data['Shafts']['Model'] == c_model)]
        if not curr_shaft_data.empty:
            curr_w = pd.to_numeric(curr_shaft_data.iloc[0]['Weight (g)'], errors='coerce')

        is_misfit = abs(curr_w - ideal_w) > 25

        df_all = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'Weight (g)', 'Torque', 'StabilityIndex']:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce')
        
        wedge_terms = ['Wedge', 'Hi-Rev', 'Spinner', 'Onyx', 'Vokey', 'Full Face']
        df_all = df_all[~df_all['Model'].str.contains('|'.join(wedge_terms), case=False)]

        def score_shafts(df_in, use_weight_logic=True):
            df_in['Flex_Penalty'] = abs(df_in['FlexScore'] - f_tf) * 800.0
            df_in['Launch_Penalty'] = abs(df_in['LaunchScore'] - f_tl) * 75.0
            
            if is_misfit and use_weight_logic:
                df_in['Weight_Penalty'] = abs(df_in['Weight (g)'] - ideal_w) * 15
            elif use_weight_logic:
                df_in['Weight_Penalty'] = df_in['Weight (g)'].apply(lambda x: abs(x - curr_w) * 5 if abs(x - curr_w) > 35 else 0)
            else:
                df_in['Weight_Penalty'] = 0
            
            if "Push" in primary_miss:
                df_in['Miss_Correction'] = (df_in['Torque'] * 500.0) + ((10 - df_in['StabilityIndex']) * 200.0)
            elif "Slice" in primary_miss or primary_miss == "Scattered":
                df_in['Miss_Correction'] = (abs(df_in['Torque'] - 3.5) * 200.0) 
            else:
                df_in['Miss_Correction'] = 0
                
            return df_in['Flex_Penalty'] + df_in['Launch_Penalty'] + df_in['Weight_Penalty'] + df_in['Miss_Correction']

        # COMBINED CALCULATION
        df_main = df_all[df_all['Weight (g)'] >= min_w].copy()
        df_main['Total_Score'] = score_shafts(df_main, use_weight_logic=True)
        
        df_graph = df_all[df_all['Material'].str.contains('Graphite|Carbon', case=False, na=False)].copy()
        df_graph['Total_Score'] = score_shafts(df_graph, use_weight_logic=False)

        # Concatenate and take top 7 overall
        combined_recs = pd.concat([df_main, df_graph]).drop_duplicates(subset=['Brand', 'Model', 'Flex'])
        combined_recs = combined_recs.sort_values('Total_Score').head(7)

        st.subheader("🚀 Top Recommended Prescription")
        if is_misfit:
            st.warning(f"⚠️ **Performance Alert:** Player is currently using a {curr_w}g shaft. Based on carry distance, logic has shifted to favor the {ideal_w}g performance bracket.")
        
        # Display table with Material column
        st.table(combined_recs[['Brand', 'Model', 'Material', 'Flex', 'Weight (g)', 'Launch', 'Torque']].reset_index(drop=True))

        st.subheader("🔬 Expert Engineering Analysis")
        traits = {
            "Zelos": "Ultra-lightweight Japanese steel designed to maximize clubhead speed for smoother tempos.",
            "NEO": "Active tip section specifically engineered to increase launch and spin for modern distance irons.",
            "Modus3 Tour 105": "Lightweight tour-profile steel; provides speed without losing the 'traditional' feel.",
            "Recoil": "Ion-plated graphite designed with high-torque recovery for squaring the face at impact.",
            "Steelfiber": "Graphite core with a steel wire wrap; the ultimate bridge between weight and feel.",
            "MMT": "Metal Mesh Technology; braids 304 stainless steel into the tip for steel-like consistency in graphite."
        }
        for i, (idx, row) in enumerate(combined_recs.iterrows(), 1):
            brand_model = f"{row['Brand']} {row['Model']}"
            blurb = next((v for k, v in traits.items() if k in brand_model), "Selected for optimal weight-to-speed ratio and dynamic stability.")
            st.markdown(f"**{i}. {brand_model} ({row['Flex']})**")
            st.caption(f"{blurb}")

        st.divider()
        b1, b2, _ = st.columns([1,1,4])
        if b1.button("✏️ Edit Survey"):
            st.session_state.interview_complete = False; st.session_state.form_step = 0; st.rerun()
        if b2.button("🆕 New Fitting"):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.rerun()
