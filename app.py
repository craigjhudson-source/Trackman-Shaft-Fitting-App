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

def save_lead_to_gsheet(answers, t_flex, t_launch, q_ids):
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        ws = sh.worksheet('Fittings')
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp]
        for qid in q_ids:
            row.append(answers.get(qid, ""))
        row.extend([t_flex, t_launch])
        ws.append_row(row)
        return True
    except Exception as e:
        st.error(f"⚠️ Error saving to Google Sheets: {e}"); return False

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
        
        # Render Inputs
        for _, row in q_df.iterrows():
            qid = str(row['QuestionID']).strip()
            qtext = row['QuestionText']
            qtype = row['InputType']
            qopts = str(row['Options']).strip()
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
        
        # Navigation Logic
        if c1.button("⬅️ Back") and st.session_state.form_step > 0:
            sync_answers(q_df['QuestionID'].tolist())
            st.session_state.form_step -= 1
            st.rerun()
        
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"):
                sync_answers(q_df['QuestionID'].tolist())
                st.session_state.form_step += 1
                st.rerun()
        else:
            if c2.button("🔥 Generate Prescription"):
                sync_answers(q_master['QuestionID'].tolist())
                
                # --- CALCULATION LOGIC ---
                f_tf, f_tl = 5.0, 5.0
                push_miss, slice_miss = False, False
                min_w, hs_mandate = 0, False

                try:
                    carry_6i = float(st.session_state.answers.get('Q15', 0))
                    if carry_6i >= 180: 
                        min_w, f_tf, hs_mandate = 118, 7.0, True
                    elif carry_6i >= 160: 
                        min_w, f_tf = 105, 6.0
                    elif carry_6i < 140:
                        f_tf = 4.0 
                except: pass

                # Logic Processing
                for qid, ans in st.session_state.answers.items():
                    logic_rows = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & 
                                                       (all_data['Responses']['ResponseOption'] == str(ans))]
                    for _, l_row in logic_rows.iterrows():
                        act = str(l_row['LogicAction'])
                        if "Target FlexScore:" in act: 
                            try: f_tf = max(f_tf, float(act.split("FlexScore:")[1].split(";")[0]))
                            except: pass
                        if "Target LaunchScore:" in act: 
                            try: f_tl = float(act.split("LaunchScore:")[1].split(";")[0])
                            except: pass
                        if "Push" in str(ans): push_miss = True
                        if "Slice" in str(ans): slice_miss = True

                st.session_state.update({
                    'final_tf': f_tf, 'final_tl': f_tl, 'push_miss': push_miss, 'slice_miss': slice_miss,
                    'min_w': min_w, 'hs_mandate': hs_mandate, 'interview_complete': True
                })
                save_lead_to_gsheet(st.session_state.answers, f_tf, f_tl, q_master['QuestionID'].tolist())
                st.rerun()

    else:
        # --- 4. MASTER FITTER REPORT ---
        st.title(f"🎯 Fitting Report: {st.session_state.answers.get('Q01', 'Player')}")
        
        # Summary Expander
        with st.expander("📋 View Full Input Verification Summary", expanded=False):
            cols = st.columns(3)
            for i, cat in enumerate(categories):
                with cols[i % 3]:
                    st.markdown(f"**{cat}**")
                    cat_qs = q_master[q_master['Category'] == cat]
                    for _, q_row in cat_qs.iterrows():
                        ans = st.session_state.answers.get(str(q_row['QuestionID']).strip(), "—")
                        st.caption(f"{q_row['QuestionText']}: **{ans}**")

        # Recommendation Logic
        tf, tl = st.session_state.get('final_tf', 5.0), st.session_state.get('final_tl', 5.0)
        push_miss, slice_miss = st.session_state.get('push_miss', False), st.session_state.get('slice_miss', False)
        min_w, hs_mandate = st.session_state.get('min_w', 0), st.session_state.get('hs_mandate', False)
        
        curr_brand = str(st.session_state.answers.get('Q10', '')).strip().lower()
        curr_model = str(st.session_state.answers.get('Q12', '')).strip().lower()

        df_s = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'Weight (g)', 'Torque', 'StabilityIndex']:
            df_s[col] = pd.to_numeric(df_s[col], errors='coerce')

        # Filters
        if curr_brand and curr_model:
            df_s = df_s[~((df_s['Brand'].str.lower() == curr_brand) & (df_s['Model'].str.lower() == curr_model))]
        df_s = df_s[~df_s['Model'].str.contains('Wedge', case=False)]
        df_s = df_s[df_s['Weight (g)'] >= min_w]
        
        # Scoring
        df_s['Flex_Penalty'] = abs(df_s['FlexScore'] - tf) * 800.0
        if hs_mandate:
            df_s.loc[df_s['FlexScore'] < 6.8, 'Flex_Penalty'] += 2500.0
        
        df_s['Launch_Penalty'] = abs(df_s['LaunchScore'] - tl) * 75.0
        
        if push_miss:
            df_s['Miss_Correction'] = (df_s['Torque'] * 500.0) + ((10 - df_s['StabilityIndex']) * 200.0)
        elif slice_miss or st.session_state.answers.get('Q17') == "Scattered":
            df_s['Miss_Correction'] = (abs(df_s['Torque'] - 3.5) * 200.0) 
        else:
            df_s['Miss_Correction'] = 0

        df_s['Total_Score'] = df_s['Flex_Penalty'] + df_s['Launch_Penalty'] + df_s['Miss_Correction']
        recs = df_s.sort_values('Total_Score').head(5).copy()

        st.subheader("🚀 Top Recommended Prescription")
        st.table(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Launch', 'Torque']].reset_index(drop=True))

        st.subheader("🔬 Expert Engineering Analysis")
        traits = {
            "Project X Rifle": "Non-loading zone profile with maximum tip-stiffness to neutralize push misses.",
            "Project X LS": "Ultra-low spin profile designed specifically for high-tempo players to hold the line.",
            "Zelos": "Ultra-lightweight Japanese steel designed to maximize clubhead speed for smoother tempos.",
            "NEO": "Active tip section specifically engineered to increase launch and spin for modern distance irons.",
            "C-Taper": "Stiffest tip profile in the KBS line; ideal for high-speed face squaring.",
            "Modus3 Tour 125": "Traditional 'System3' profile offering X-flex stability with a smooth Japanese steel feel.",
            "L-Series": "Carbon-engineered for ultra-fast torque recovery to square the face at impact."
        }

        for i, (idx, row) in enumerate(recs.iterrows(), 1):
            brand_model = f"{row['Brand']} {row['Model']}"
            blurb = "Selected for optimal weight-to-speed ratio and dynamic stability."
            for key in traits:
                if key in brand_model: blurb = traits[key]
            st.markdown(f"**{i}. {brand_model} ({row['Flex']})**")
            st.caption(f"{blurb}")

        st.divider()
        # --- RESTORED FOOTER BUTTONS ---
        b1, b2, _ = st.columns([1,1,4])
        if b1.button("✏️ Edit Survey"):
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.rerun()
        if b2.button("🆕 New Fitting"):
            for key in list(st.session_state.keys()): 
                del st.session_state[key]
            st.rerun()
