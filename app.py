import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime

# --- 1. DATA ENGINE ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

@st.cache_data(ttl=600)
def get_data_from_gsheet():
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        return {
            'Heads': pd.DataFrame(sh.worksheet('Heads').get_all_records()),
            'Shafts': pd.DataFrame(sh.worksheet('Shafts').get_all_records()),
            'Questions': pd.DataFrame(sh.worksheet('Questions').get_all_records()),
            'Responses': pd.DataFrame(sh.worksheet('Responses').get_all_records()),
            'Config': pd.DataFrame(sh.worksheet('Config').get_all_records())
        }
    except Exception as e:
        st.error(f"📡 Data Load Error: {e}"); return None

def save_lead_to_gsheet(answers, t_flex, t_launch):
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        ws = sh.worksheet('Fittings')
        row = [str(datetime.datetime.now())] + [answers.get(f"Q{i:02d}", "") for i in range(1, 22)] + [t_flex, t_launch]
        ws.append_row(row)
        return True
    except: return False

# --- 2. INITIALIZATION ---
st.set_page_config(page_title="Patriot Fitting Engine", layout="wide")
all_data = get_data_from_gsheet()

if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state['answers'] = {f"Q{i:02d}": "" for i in range(1, 22)}

def sync_answers(q_list):
    for qid in q_list:
        if f"widget_{qid}" in st.session_state: st.session_state['answers'][qid] = st.session_state[f"widget_{qid}"]

# --- 3. QUESTIONNAIRE ---
if all_data:
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine")
        categories = all_data['Questions']['Category'].unique().tolist()
        current_cat = categories[st.session_state.form_step]
        q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
        current_qids = q_df['QuestionID'].tolist()

        st.subheader(f"Section: {current_cat}")
        for _, row in q_df.iterrows():
            qid, qtext, qtype, qopts = row['QuestionID'], row['QuestionText'], row['InputType'], str(row['Options'])
            prev_val = st.session_state['answers'].get(qid, "")

            if qtype == "Dropdown":
                options = [""]
                if "Config:" in qopts: options += all_data['Config'][qopts.split(":")[1]].dropna().unique().tolist()
                elif "Heads" in qopts:
                    if "Brand" in qtext: options += sorted(all_data['Heads']['Manufacturer'].unique().tolist())
                    else:
                        brand = st.session_state.get("widget_Q08", st.session_state['answers'].get('Q08', ""))
                        if brand: options += sorted(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].unique().tolist())
                elif "Shafts" in qopts:
                    brand = st.session_state.get("widget_Q10", st.session_state['answers'].get('Q10', ""))
                    if "Brand" in qtext: options += sorted(all_data['Shafts']['Brand'].unique().tolist())
                    elif brand:
                        if "Flex" in qtext: options += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Flex'].unique().tolist())
                        else: options += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Model'].unique().tolist())
                elif "," in qopts: options += [x.strip() for x in qopts.split(",")]
                else: options += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].unique().tolist()
                
                idx = options.index(prev_val) if prev_val in options else 0
                st.selectbox(qtext, options, index=idx, key=f"widget_{qid}", on_change=sync_answers, args=(current_qids,))
            elif qtype == "Numeric":
                st.number_input(qtext, value=float(prev_val) if prev_val else 0.0, key=f"widget_{qid}", on_change=sync_answers, args=(current_qids,))
            else:
                st.text_input(qtext, value=str(prev_val), key=f"widget_{qid}", on_change=sync_answers, args=(current_qids,))

        c1, c2, _ = st.columns([1,1,4])
        if st.session_state.form_step > 0 and c1.button("⬅️ Back"):
            sync_answers(current_qids); st.session_state.form_step -= 1; st.rerun()
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"):
                sync_answers(current_qids); st.session_state.form_step += 1; st.rerun()
        elif c2.button("🔥 Generate Prescription"):
            sync_answers(current_qids); st.session_state.interview_complete = True; st.rerun()

    else:
        # --- 4. RESULTS VIEW ---
        st.title(f"🎯 Fitting Report: {st.session_state['answers'].get('Q01', 'Player')}")
        
        # 1. Verification Section
        st.subheader("📋 Input Verification")
        v1, v2, v3, v4 = st.columns(4)
        try: carry = float(st.session_state['answers'].get('Q15', 0))
        except: carry = 0
        miss = st.session_state['answers'].get('Q18', "")
        v1.metric("6i Carry", f"{carry} yds")
        v2.metric("Miss", miss)
        v3.metric("Current Shaft", st.session_state['answers'].get('Q12', ""))
        v4.metric("Current Flex", st.session_state['answers'].get('Q11', ""))

        with st.expander("Show Full Survey Answers"):
            cols = st.columns(3)
            for i, (qid, val) in enumerate(st.session_state['answers'].items()):
                q_txt = all_data['Questions'][all_data['Questions']['QuestionID'] == qid]['QuestionText'].values[0]
                cols[i%3].write(f"**{q_txt}:** {val}")

        # 2. Advanced Penalty Engine
        tf, tl = 6.0, 5.0 # Fallbacks
        for qid, ans in st.session_state['answers'].items():
            logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == str(ans))]
            if not logic.empty:
                act = str(logic.iloc[0]['LogicAction'])
                if "FlexScore:" in act: tf = float(act.split(":")[1])
                if "LaunchScore:" in act: tl = float(act.split(":")[1])

        # ELITE SPEED CORRECTION
        if carry >= 190: tf = 7.5 # Target X-Stiff+
        elif carry >= 175: tf = 6.5 # Target Stiff+

        df_s = all_data['Shafts'].copy()
        df_s['FlexScore'] = pd.to_numeric(df_s['FlexScore'], errors='coerce')
        df_s['LaunchScore'] = pd.to_numeric(df_s['LaunchScore'], errors='coerce')
        df_s['Weight'] = pd.to_numeric(df_s['Weight (g)'], errors='coerce')

       # --- NEW ADVANCED STABILITY ENGINE WITH FITTER'S NOTES ---
        df_s['EI_Tip'] = pd.to_numeric(df_s['EI_Tip'], errors='coerce')
        df_s['StabilityIndex'] = pd.to_numeric(df_s['StabilityIndex'], errors='coerce')
        df_s['Torque'] = pd.to_numeric(df_s['Torque'], errors='coerce')

        # 1. Baseline Penalty (Flex & Launch)
        df_s['Penalty'] = (abs(df_s['FlexScore'] - tf) * 30) + (abs(df_s['LaunchScore'] - tl) * 20)
        
        # 2. Speed & Hook Logic
        if carry >= 190:
            df_s.loc[df_s['Weight'] < 115, 'Penalty'] += 500 
            df_s.loc[df_s['EI_Tip'] < 12.0, 'Penalty'] += 250
            df_s.loc[df_s['StabilityIndex'] < 7.5, 'Penalty'] += 200
        
        if "Hook" in miss:
            df_s['Penalty'] += (df_s['Torque'] * 100) 
            df_s.loc[df_s['EI_Tip'] >= 13, 'Penalty'] -= 50

        # 3. GENERATE DYNAMIC FITTER'S NOTES
        def generate_notes(row):
            notes = []
            if row['EI_Tip'] >= 12.5: notes.append("Reinforced Tip (Anti-Hook)")
            if row['StabilityIndex'] >= 8.0: notes.append("Tour-Grade Stability")
            if row['Torque'] <= 1.4: notes.append("Low-Twist Face Control")
            if row['Weight'] >= 125: notes.append("Heavy Tempo Control")
            return " | ".join(notes) if notes else "Balanced Profile"

        df_s['Fitters Note'] = df_s.apply(generate_notes, axis=1)

        # 4. FINAL SORT (Prioritizing Flex Score to push 6.5 above 6.0 for high speed)
        # We sort by Penalty (Low to High), then FlexScore (High to Low), then Stability (High to Low)
        recs = df_s.sort_values(['Penalty', 'FlexScore', 'StabilityIndex'], 
                               ascending=[True, False, False]).head(5)

        st.divider()
        st.subheader("🚀 Recommended Shaft Blueprints")
        st.info(f"Targeting: Stiff-Plus to X-Stiff profiles with High Tip Stability.")
        
        # Display the table with the new Fitters Note column
        st.table(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Launch', 'Spin', 'Fitters Note']])
        
        # SPEED & HOOK SHIELD
        if carry > 185:
            df_s.loc[df_s['Weight'] < 115, 'Penalty'] += 300 # Kill light shafts for high speed
        
        if "Hook" in miss or "Pull" in miss:
            df_s.loc[df_s['LaunchScore'] > 4, 'Penalty'] += 150 # Penalize active tips
            df_s.loc[df_s['Weight'] < 110, 'Penalty'] += 100 # Weight stabilizes path

        st.divider()
        st.subheader("🚀 Recommended Shaft Blueprints")
        st.success(f"Algorithm Target -> Flex: {tf} (X-Stiff Class) | Launch: {tl}")
        
        recs = df_s.sort_values(['Penalty', 'Weight'], ascending=[True, False]).head(5)
        st.table(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Launch', 'Spin']])
        
        if st.button("💾 Save Results to Google Sheets"):
            if save_lead_to_gsheet(st.session_state['answers'], tf, tl):
                st.success("Results Uploaded Successfully!")
            else: st.error("Upload Failed.")

        if st.button("🆕 New Fitting"):
            st.session_state['answers'] = {f"Q{i:02d}": "" for i in range(1, 22)}
            st.session_state.interview_complete = False; st.session_state.form_step = 0; st.rerun()
