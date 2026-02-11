import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime

# --- 1. DATA CONNECTION & CLEANING ---
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
    
    if not st.session_state.interview_complete:
        st.title("Patriot Golf Performance Fitting")
        categories = list(dict.fromkeys(q_master['Category'].tolist()))
        st.progress(st.session_state.form_step / len(categories))
        current_cat = categories[st.session_state.form_step]
        q_df = q_master[q_master['Category'] == current_cat]
        st.subheader(f"Section: {current_cat}")
        
        for _, row in q_df.iterrows():
            qid, qtext, qtype, qopts = str(row['QuestionID']).strip(), row['QuestionText'], row['InputType'], str(row['Options']).strip()
            ans_val = st.session_state.answers.get(qid, "")
            
            if qtype == "Dropdown":
                opts = [""]
                if "Config:" in qopts:
                    col_name = qopts.split(":")[1].strip()
                    if col_name in all_data['Config'].columns:
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
            sync_answers(q_df['QuestionID'].tolist())
            st.session_state.form_step -= 1; st.rerun()
        
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"):
                sync_answers(q_df['QuestionID'].tolist())
                st.session_state.form_step += 1; st.rerun()
        else:
            if c2.button("🔥 Generate Prescription"):
                sync_answers(q_master['QuestionID'].tolist())
                
                # --- CORE LOGIC CONSTANTS ---
                f_tf, f_tl = 6.0, 5.0
                anti_left, push_miss = False, False
                min_w, max_w = 0, 200

                # 1. SPEED-BASED WEIGHT FLOOR
                try:
                    carry_6i = float(st.session_state.answers.get('Q15', 0))
                    if carry_6i >= 180: min_w = 118 # Floor for high speed
                    elif carry_6i >= 165: min_w = 105
                except: pass

                # 2. RESPONSE LOGIC LOOP
                for qid, ans in st.session_state.answers.items():
                    logic_rows = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & 
                                                       (all_data['Responses']['ResponseOption'] == str(ans))]
                    for _, l_row in logic_rows.iterrows():
                        act = str(l_row['LogicAction'])
                        if "Target FlexScore:" in act: 
                            try: f_tf = float(act.split("FlexScore:")[1].split(";")[0])
                            except: pass
                        if "Target LaunchScore:" in act: 
                            try: f_tl = float(act.split("LaunchScore:")[1].split(";")[0])
                            except: pass
                        if "Anti-Left: True" in act: anti_left = True
                        if "Primary Miss: Push" in act or str(ans) == "Push": push_miss = True

                # 3. TOUR-SPEED FLEX UPGRADE
                try:
                    if float(st.session_state.answers.get('Q15', 0)) > 180:
                        f_tf = 7.0 # Force X-Flex Floor
                except: pass

                st.session_state.update({
                    'final_tf': f_tf, 'final_tl': f_tl, 
                    'anti_left': anti_left, 'push_miss': push_miss,
                    'min_w': min_w, 'max_w': max_w, 'interview_complete': True
                })
                st.rerun()

    else:
        # --- 4. MASTER FITTER REPORT ---
        st.title(f"🎯 Fitting Report: {st.session_state.answers.get('Q01', 'Player')}")
        
        with st.expander("📋 View Full Input Verification Summary", expanded=True):
            cols = st.columns(3)
            categories = list(dict.fromkeys(q_master['Category'].tolist()))
            for i, cat in enumerate(categories):
                with cols[i % 3]:
                    st.markdown(f"**{cat}**")
                    cat_qs = q_master[q_master['Category'] == cat]
                    for _, q_row in cat_qs.iterrows():
                        ans = st.session_state.answers.get(str(q_row['QuestionID']).strip(), "—")
                        st.caption(f"{q_row['QuestionText']}: **{ans}**")

        tf = st.session_state.get('final_tf', 6.0)
        tl = st.session_state.get('final_tl', 5.0)
        push_miss = st.session_state.get('push_miss', False)
        min_w = st.session_state.get('min_w', 0)
        
        df_s = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'StabilityIndex', 'Weight (g)', 'Torque']:
            df_s[col] = pd.to_numeric(df_s[col], errors='coerce')

        # STEP A: HARD SPEED GATING (Weight & Flex)
        df_s = df_s[df_s['Weight (g)'] >= min_w]
        
        # STEP B: MATHEMATICAL SCORING
        df_s['Flex_Penalty'] = abs(df_s['FlexScore'] - tf) * 400.0 # Heavy weight on flex
        df_s['Launch_Penalty'] = abs(df_s['LaunchScore'] - tl) * 50.0
        
        # PUSH MISS CORRECTION: High torque is the enemy of the push.
        if push_miss and min_w >= 115:
            df_s['Torque_Penalty'] = df_s['Torque'] * 200.0 
        else:
            df_s['Torque_Penalty'] = 0

        df_s['Total_Score'] = df_s['Flex_Penalty'] + df_s['Launch_Penalty'] + df_s['Torque_Penalty']
        recs = df_s.sort_values('Total_Score').head(5).copy()

        # --- RESULTS ---
        st.subheader("🚀 Top Recommended Prescription")
        st.table(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Launch', 'Torque']].reset_index(drop=True))

        st.subheader("🔬 Expert Engineering Analysis")
        traits = {
            "Project X Rifle": "Low-torque, tip-stiff design to prevent the face from hanging open at high speeds.",
            "Dynamic Gold": "High-mass profile to provide maximum feedback and lower a 'High' flight tendency.",
            "C-Taper": "Piercing trajectory with an ultra-stiff tip to minimize face deflection.",
            "Modus3 Tour 120": "Unique 'X' profile with a stiff tip but smoother mid-section for high-speed feel.",
            "L-Series": "Modern carbon-fiber steel replacement with superior torque recovery for push-miss correction.",
            "CT-125": "Heavyweight stability profile specifically tuned for carry distances exceeding 180 yards."
        }

        for i, (idx, row) in enumerate(recs.iterrows(), 1):
            brand_model = f"{row['Brand']} {row['Model']}"
            blurb = "Selected for dynamic stability and optimal weight-to-speed ratio."
            for key in traits:
                if key in brand_model: blurb = traits[key]
            st.markdown(f"**{i}. {brand_model} ({row['Flex']})**")
            st.caption(f"{blurb}")

        st.divider()
        if st.button("🆕 New Fitting"):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.rerun()
