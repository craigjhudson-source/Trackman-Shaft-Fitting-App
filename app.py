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
        final_row_data = {f"Q{i:02d}": st.session_state.get(f"widget_Q{i:02d}", answers.get(f"Q{i:02d}", "")) for i in range(1, 22)}
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        ws = sh.worksheet('Fittings')
        row = [datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")] + [final_row_data.get(f"Q{i:02d}", "") for i in range(1, 22)] + [t_flex, t_launch]
        ws.append_row(row)
        return True
    except: return False
        
# --- 2. INITIALIZATION ---
st.set_page_config(page_title="Patriot Fitting Engine", layout="wide", page_icon="⛳")
all_data = get_data_from_gsheet()
if 'form_step' not in st.session_state: st.session_state.update({'form_step': 0, 'interview_complete': False, 'needs_save': False, 'answers': {f"Q{i:02d}": "" for i in range(1, 22)}})

def sync_answers(q_list):
    for qid in q_list:
        if f"widget_{qid}" in st.session_state: st.session_state['answers'][qid] = st.session_state[f"widget_{qid}"]

# --- 3. UI RENDERER ---
if all_data:
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine")
        categories = all_data['Questions']['Category'].unique().tolist()
        st.progress(st.session_state.form_step / len(categories))
        current_cat = categories[st.session_state.form_step]
        q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
        
        for _, row in q_df.iterrows():
            qid, qtext, qtype, qopts = row['QuestionID'], row['QuestionText'], row['InputType'], str(row['Options'])
            val = st.session_state['answers'].get(qid, "")
            if qtype == "Dropdown":
                opts = [""]
                if "Config:" in qopts: opts += all_data['Config'][qopts.split(":")[1]].dropna().unique().tolist()
                elif "Heads" in qopts: 
                    brand = st.session_state.get("widget_Q08", "")
                    opts += sorted(all_data['Heads']['Manufacturer'].unique().tolist()) if "Brand" in qtext else sorted(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].unique().tolist())
                elif "Shafts" in qopts:
                    brand = st.session_state.get("widget_Q10", "")
                    if "Brand" in qtext: opts += sorted(all_data['Shafts']['Brand'].unique().tolist())
                    elif "Flex" in qtext: opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Flex'].unique().tolist())
                    else: opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Model'].unique().tolist())
                else: opts += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].unique().tolist()
                st.selectbox(qtext, opts, index=opts.index(val) if val in opts else 0, key=f"widget_{qid}")
            elif qtype == "Numeric": st.number_input(qtext, value=float(val) if val else 0.0, key=f"widget_{qid}")
            else: st.text_input(qtext, value=str(val), key=f"widget_{qid}")

        c1, c2, _ = st.columns([1,1,4])
        if c1.button("⬅️ Back") and st.session_state.form_step > 0: sync_answers(q_df['QuestionID'].tolist()); st.session_state.form_step -= 1; st.rerun()
        if st.session_state.form_step < len(categories)-1:
            if c2.button("Next ➡️"): sync_answers(q_df['QuestionID'].tolist()); st.session_state.form_step += 1; st.rerun()
        elif c2.button("🔥 Generate Prescription"):
            sync_answers([f"Q{i:02d}" for i in range(1, 22)])
            f_tf, f_tl = 6.0, 5.0
            for qid, ans in st.session_state['answers'].items():
                logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == str(ans))]
                if not logic.empty:
                    act = str(logic.iloc[0]['LogicAction'])
                    if "FlexScore:" in act: f_tf = float(act.split(":")[1])
                    if "LaunchScore:" in act: f_tl = float(act.split(":")[1])
            st.session_state.update({'final_tf': f_tf, 'final_tl': f_tl, 'interview_complete': True, 'needs_save': True}); st.rerun()

    else:
        # --- 4. EXPERT RESULTS VIEW ---
        tf, tl = st.session_state.get('final_tf', 6.0), st.session_state.get('final_tl', 5.0)
        if st.session_state.needs_save:
            if save_lead_to_gsheet(st.session_state['answers'], tf, tl): st.toast("✅ Lead Saved")
            st.session_state.needs_save = False

        st.title(f"🎯 Fitting Report: {st.session_state['answers'].get('Q01', 'Player')}")
        miss = st.session_state['answers'].get('Q18', "Straight")
        carry = float(st.session_state['answers'].get('Q15', 0))

        # --- THE VERDICT ENGINE ---
        df_s = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'StabilityIndex', 'Weight (g)', 'EI_Tip', 'Torque']:
            df_s[col] = pd.to_numeric(df_s[col], errors='coerce')

        df_s['Penalty'] = (abs(df_s['FlexScore'] - tf) * 150) + (abs(df_s['LaunchScore'] - tl) * 20)
        if miss in ["Hook", "Pull"]: df_s['Penalty'] += (df_s['Torque'] * 200)
        if miss in ["Push", "Slice"]: df_s['Penalty'] += (abs(df_s['EI_Tip'] - 10) * 50) # Favors softer tips

        # Brand Variety Boost
        df_s['BrandRank'] = df_s.groupby('Brand')['Penalty'].rank(method='first')
        df_s.loc[df_s['BrandRank'] == 1, 'Penalty'] -= 15

        recs = df_s.sort_values('Penalty').head(5).copy()

        def get_verdict(row):
            if miss in ["Push", "Slice"] and row['EI_Tip'] < 11: return "✅ Release Assistant (Fixes Push)"
            if miss in ["Hook", "Pull"] and row['StabilityIndex'] > 9: return "🛡️ Stability King (Anti-Hook)"
            if row['Weight (g)'] < 100 and carry > 170: return "⚡ Speed Play (Lightweight)"
            if row['Brand'] == "KBS" or row['Brand'] == "Nippon": return "💎 Premium Feel"
            return "🎯 Balanced Fit"

        recs['Verdict'] = recs.apply(get_verdict, axis=1)

        st.subheader("🚀 Recommended Prescription")
        st.table(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Verdict']])

        # Narrative Summary
        st.info(f"**Expert Analysis:** Based on your **{miss}** miss and **{carry}yd** carry, we prioritized shafts with a **FlexScore of {tf}**. "
                f"We selected profiles that provide enough 'kick' to help square the face at impact while maintaining stability.")
        
        if st.button("🆕 New Fitting"):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.rerun()
