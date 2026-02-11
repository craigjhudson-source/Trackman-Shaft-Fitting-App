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
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        return {
            'Heads': pd.DataFrame(sh.worksheet('Heads').get_all_records()),
            'Shafts': pd.DataFrame(sh.worksheet('Shafts').get_all_records()),
            'Questions': pd.DataFrame(sh.worksheet('Questions').get_all_records()),
            'Responses': pd.DataFrame(sh.worksheet('Responses').get_all_records()),
            'Config': pd.DataFrame(sh.worksheet('Config').get_all_records())
        }
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
        if key in st.session_state: st.session_state.answers[qid] = st.session_state[key]

# --- 3. DYNAMIC QUESTIONNAIRE ---
if all_data:
    # Clean up Questions data
    q_master = all_data['Questions'].copy()
    q_master['QuestionID'] = q_master['QuestionID'].astype(str).str.strip()
    
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine")
        
        # Get Ordered Categories
        categories = list(dict.fromkeys(q_master['Category'].tolist()))
        st.progress(st.session_state.form_step / len(categories))
        
        current_cat = categories[st.session_state.form_step]
        q_df = q_master[q_master['Category'] == current_cat]
        
        st.subheader(f"Section: {current_cat}")
        
        for _, row in q_df.iterrows():
            qid = row['QuestionID']
            qtext = row['QuestionText']
            qtype = row['InputType']
            qopts = str(row['Options']).strip()
            ans_val = st.session_state.answers.get(qid, "")
            
            if qtype == "Dropdown":
                opts = [""]
                # 1. Pull from Config Tab (ORDERED AS IN SHEET)
                if "Config:" in qopts:
                    col_name = qopts.split(":")[1].strip()
                    if col_name in all_data['Config'].columns:
                        opts += all_data['Config'][col_name].dropna().tolist()
                
                # 2. Dynamic Heads (ALPHABETICAL)
                elif "Heads" in qopts:
                    if "Brand" in qtext:
                        opts += sorted(all_data['Heads']['Manufacturer'].unique().tolist())
                    else:
                        brand = st.session_state.get("widget_Q08", st.session_state.answers.get("Q08", ""))
                        opts += sorted(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].unique().tolist()) if brand else []
                
                # 3. Dynamic Shafts (ALPHABETICAL)
                elif "Shafts" in qopts:
                    brand = st.session_state.get("widget_Q10", st.session_state.answers.get("Q10", ""))
                    if "Brand" in qtext: 
                        opts += sorted(all_data['Shafts']['Brand'].unique().tolist())
                    elif "Flex" in qtext: 
                        opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Flex'].unique().tolist()) if brand else []
                    else: 
                        opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Model'].unique().tolist()) if brand else []
                
                # 4. Pull from Responses Tab
                else:
                    opts += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].tolist()
                
                st.selectbox(qtext, opts, index=opts.index(ans_val) if ans_val in opts else 0, key=f"widget_{qid}")
            
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
                # Scoring Logic
                f_tf, f_tl = 6.0, 5.0
                for qid, ans in st.session_state.answers.items():
                    logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == str(ans))]
                    if not logic.empty:
                        act = str(logic.iloc[0]['LogicAction'])
                        if "FlexScore:" in act: f_tf = float(act.split(":")[1])
                        if "LaunchScore:" in act: f_tl = float(act.split(":")[1])
                st.session_state.update({'final_tf': f_tf, 'final_tl': f_tl, 'interview_complete': True}); st.rerun()

    else:
        # --- 4. RESULTS ---
        st.title(f"🎯 Fitting Report: {st.session_state.answers.get('Q01', 'Player')}")
        
        # Restoration of Verification Summary
        st.subheader("📋 Input Verification")
        c_v1, c_v2 = st.columns(2)
        with c_v1:
            st.write(f"**Handedness:** {st.session_state.answers.get('Q04', 'N/A')}")
            st.write(f"**Current Head:** {st.session_state.answers.get('Q08', '')} {st.session_state.answers.get('Q09', '')}")
        with c_v2:
            miss = st.session_state.answers.get('Q18', "Straight")
            carry = float(st.session_state.answers.get('Q15', 0))
            st.write(f"**6i Carry:** {carry} yards")
            st.write(f"**Primary Miss:** {miss}")

        # Fitter Logic
        tf, tl = st.session_state.final_tf, st.session_state.final_tl
        df_s = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'StabilityIndex', 'Weight (g)', 'EI_Tip', 'Torque']:
            df_s[col] = pd.to_numeric(df_s[col], errors='coerce')

        df_s['Penalty'] = (abs(df_s['FlexScore'] - tf) * 150) + (abs(df_s['LaunchScore'] - tl) * 30)
        
        # Push/Hook Correction
        if miss in ["Push", "Slice"]:
            df_s.loc[df_s['EI_Tip'] > 12.5, 'Penalty'] += 200
            df_s.loc[df_s['Torque'] < 1.6, 'Penalty'] += 100
        if miss in ["Hook", "Pull"]:
            df_s['Penalty'] += (df_s['Torque'] * 150)
            df_s.loc[df_s['StabilityIndex'] < 8.0, 'Penalty'] += 200

        recs = df_s.sort_values(['Penalty', 'FlexScore'], ascending=[True, False]).head(5).copy()

        def generate_verdict(row):
            if miss in ["Push", "Slice"] and row['EI_Tip'] < 11.5: return "✅ Release Assistant"
            if miss in ["Hook", "Pull"] and row['StabilityIndex'] > 8.5: return "🛡️ Stability King"
            if row['Weight (g)'] < 100 and carry > 175: return "⚡ Speed Play"
            return "🎯 Balanced Fit"

        recs['Verdict'] = recs.apply(generate_verdict, axis=1)
        st.subheader("🚀 Recommended Prescription")
        st.table(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Verdict', 'Launch', 'Torque']])

        # Narrative
        st.info(f"**Expert Analysis:** For your **{miss}**, we prioritized the **{recs.iloc[0]['Brand']} {recs.iloc[0]['Model']}**. Its profile is designed to {'help you turn the club over' if miss in ['Push', 'Slice'] else 'keep the face from closing'} while matching your **{carry}yd** speed.")

        st.divider()
        if st.button("✏️ Edit Survey"):
            st.session_state.interview_complete = False; st.session_state.form_step = 0; st.rerun()
