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
    
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine")
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
                f_tf, f_tl = 6.0, 5.0
                for qid, ans in st.session_state.answers.items():
                    logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == str(ans))]
                    if not logic.empty:
                        act = str(logic.iloc[0]['LogicAction'])
                        if "FlexScore:" in act: f_tf = float(act.split(":")[1])
                        if "LaunchScore:" in act: f_tl = float(act.split(":")[1])
                
                save_lead_to_gsheet(st.session_state.answers, f_tf, f_tl, q_master['QuestionID'].tolist())
                st.session_state.update({'final_tf': f_tf, 'final_tl': f_tl, 'interview_complete': True})
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

        # Recommendation Engine with Weight Guardrails
        tf, tl = st.session_state.final_tf, st.session_state.final_tl
        miss = st.session_state.answers.get('Q18', "Straight")
        carry = float(st.session_state.answers.get('Q15', 0))
        
        df_s = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'StabilityIndex', 'Weight (g)', 'EI_Tip', 'Torque']:
            df_s[col] = pd.to_numeric(df_s[col], errors='coerce')

        # Primary Penalty (Flex & Launch)
        df_s['Penalty'] = (abs(df_s['FlexScore'] - tf) * 150) + (abs(df_s['LaunchScore'] - tl) * 30)
        
        # --- ADDED: SPEED-TO-WEIGHT GUARDRAILS ---
        if carry > 175:
            df_s.loc[df_s['Weight (g)'] < 115, 'Penalty'] += 500 # Heavy penalty for light shafts at high speed
        elif 150 <= carry <= 170:
            df_s.loc[df_s['Weight (g)'] > 125, 'Penalty'] += 200
            df_s.loc[df_s['Weight (g)'] < 100, 'Penalty'] += 200
        elif carry < 140:
            df_s.loc[df_s['Weight (g)'] > 110, 'Penalty'] += 500 # Heavy penalty for heavy shafts at low speed

        # Miss Correction logic
        if miss in ["Push", "Slice"]:
            df_s.loc[df_s['EI_Tip'] > 12.5, 'Penalty'] += 200
            df_s.loc[df_s['Torque'] < 1.6, 'Penalty'] += 100
        elif miss in ["Hook", "Pull"]:
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

        # --- ADDED: NARRATIVE WEIGHT WARNING ---
        rec_w = recs.iloc[0]['Weight (g)']
        weight_note = ""
        if carry > 175 and rec_w < 110:
            weight_note = f" ⚠️ Note: This shaft is lighter than traditional sets; ensure you maintain a smooth tempo."
        elif carry < 140 and rec_w > 110:
            weight_note = f" ⚠️ Note: This is a heavier build; focus on a full shoulder turn to maintain speed."

        st.info(f"**Expert Analysis:** For your **{miss}**, we prioritized the **{recs.iloc[0]['Brand']} {recs.iloc[0]['Model']}**. Its profile is designed to {'help you turn the club over' if miss in ['Push', 'Slice'] else 'keep the face from closing'} while matching your **{carry}yd** speed.{weight_note}")

        st.divider()
        bt1, bt2, _ = st.columns([1, 1, 4])
        if bt1.button("✏️ Edit Survey", use_container_width=True):
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.rerun()
        if bt2.button("🆕 New Fitting", use_container_width=True):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.rerun()
