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
        # Using your specific URL
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
        # --- CRITICAL AUTOFILL FIX ---
        # Instead of trusting the 'answers' dictionary, we force-grab 
        # the literal value currently inside the UI widgets.
        final_row_data = {}
        for i in range(1, 22):
            qid = f"Q{i:02d}"
            widget_key = f"widget_{qid}"
            # Grab from live widget state, fallback to dict if widget isn't on screen
            live_val = st.session_state.get(widget_key, answers.get(qid, ""))
            final_row_data[qid] = str(live_val)
        # -----------------------------

        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        ws = sh.worksheet('Fittings')
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp]
        
        # Build the final row using our forced-sync data
        for i in range(1, 22):
            qid = f"Q{i:02d}"
            row.append(final_row_data.get(qid, ""))
            
        row.append(t_flex)
        row.append(t_launch)
        
        ws.append_row(row)
        return True
    except Exception as e:
        st.error(f"📡 Connection Error: {str(e)}")
        return False
        
# --- 2. INITIALIZATION ---
st.set_page_config(page_title="Patriot Fitting Engine", layout="wide", page_icon="⛳")
all_data = get_data_from_gsheet()

if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'needs_save' not in st.session_state: st.session_state.needs_save = False
if 'answers' not in st.session_state: st.session_state['answers'] = {f"Q{i:02d}": "" for i in range(1, 22)}

def sync_answers(q_list):
    """Force syncs current widget values into the session answers dictionary."""
    for qid in q_list:
        widget_key = f"widget_{qid}"
        if widget_key in st.session_state: 
            st.session_state['answers'][qid] = st.session_state[widget_key]

# --- 3. QUESTIONNAIRE ---
if all_data:
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine")
        
        categories = all_data['Questions']['Category'].unique().tolist()
        progress = (st.session_state.form_step) / (len(categories))
        st.progress(progress, text=f"Step {st.session_state.form_step + 1} of {len(categories)}")

        current_cat = categories[st.session_state.form_step]
        q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
        current_qids = q_df['QuestionID'].tolist()

        st.subheader(f"Section: {current_cat}")
        
        for _, row in q_df.iterrows():
            qid, qtext, qtype, qopts = row['QuestionID'], row['QuestionText'], row['InputType'], str(row['Options'])
            prev_val = st.session_state['answers'].get(qid, "")

            if qtype == "Dropdown":
                options = [""]
                if "Config:" in qopts: 
                    options += all_data['Config'][qopts.split(":")[1]].dropna().unique().tolist()
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
                elif "," in qopts and qopts != "nan": options += [x.strip() for x in qopts.split(",")]
                else: 
                    options += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].unique().tolist()
                
                idx = options.index(prev_val) if prev_val in options else 0
                st.selectbox(qtext, options, index=idx, key=f"widget_{qid}")
            
            elif qtype == "Numeric":
                st.number_input(qtext, value=float(prev_val) if prev_val else 0.0, key=f"widget_{qid}")
            else:
                # Text Input (Name, Email, Phone)
                st.text_input(qtext, value=str(prev_val), key=f"widget_{qid}")

        st.markdown("---")
        c1, c2, _ = st.columns([1,1,4])
        
        if st.session_state.form_step > 0 and c1.button("⬅️ Back"):
            sync_answers(current_qids)
            st.session_state.form_step -= 1
            st.rerun()
            
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"):
                sync_answers(current_qids)
                st.session_state.form_step += 1
                st.rerun()
        elif c2.button("🔥 Generate Prescription"):
            # FINAL SYNC FOR ALL QUESTIONS
            all_qids = [f"Q{i:02d}" for i in range(1, 22)]
            sync_answers(all_qids)
            
            # Final Score Calculation
            f_tf, f_tl = 6.0, 5.0
            for qid, ans in st.session_state['answers'].items():
                if not ans: continue
                logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == str(ans))]
                if not logic.empty:
                    act = str(logic.iloc[0]['LogicAction'])
                    if "FlexScore:" in act: f_tf = float(act.split(":")[1])
                    if "LaunchScore:" in act: f_tl = float(act.split(":")[1])
            
            st.session_state.final_tf = f_tf
            st.session_state.final_tl = f_tl
            st.session_state.interview_complete = True
            st.session_state.needs_save = True
            st.rerun()

    else:
        # --- 4. RESULTS VIEW ---
        tf = st.session_state.get('final_tf', 6.0)
        tl = st.session_state.get('final_tl', 5.0)

        # AUTO-SAVE HANDLER
        if st.session_state.get('needs_save', False):
            if save_lead_to_gsheet(st.session_state['answers'], tf, tl):
                st.toast("✅ Lead automatically saved to Google Sheets", icon="💾")
            st.session_state.needs_save = False 

        st.title(f"🎯 Fitting Report: {st.session_state['answers'].get('Q01', 'Player')}")
        
        # 1. Summary Dashboard
        st.subheader("📋 Input Verification Summary")
        sum_col1, sum_col2 = st.columns(2)
        with sum_col1:
            st.markdown("##### **Player & Current Setup**")
            st.write(f"**Handedness:** {st.session_state['answers'].get('Q04', 'N/A')}")
            st.write(f"**Current Head:** {st.session_state['answers'].get('Q08', '')} {st.session_state['answers'].get('Q09', '')}")
            st.write(f"**Current Shaft:** {st.session_state['answers'].get('Q10', '')} {st.session_state['answers'].get('Q12', '')} ({st.session_state['answers'].get('Q11', '')})")
            st.write(f"**Club Specs:** {st.session_state['answers'].get('Q13', 'Std')} Length | {st.session_state['answers'].get('Q14', 'D2')} SW")
        with sum_col2:
            st.markdown("##### **Performance & Goals**")
            carry = float(st.session_state['answers'].get('Q15', 0))
            miss = st.session_state['answers'].get('Q18', "Straight")
            st.write(f"**6i Carry:** :red[{carry} yards]")
            st.write(f"**Primary Miss:** :orange[{miss}]")
            st.write(f"**Flight Path:** {st.session_state['answers'].get('Q16', 'Mid')} → **Target:** {st.session_state['answers'].get('Q17', 'Mid')}")
            st.write(f"**Feel Priority:** {st.session_state['answers'].get('Q21', 'N/A')}")

        st.divider()

        # 2. Calculation Engine
        df_s = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'StabilityIndex', 'Weight (g)', 'EI_Tip', 'Torque']:
            df_s[col] = pd.to_numeric(df_s[col], errors='coerce')

        df_s['Penalty'] = (abs(df_s['FlexScore'] - tf) * 150) + (abs(df_s['LaunchScore'] - tl) * 20)
        
        if carry >= 190:
            df_s.loc[df_s['Weight (g)'] < 120, 'Penalty'] += 500
            df_s.loc[df_s['FlexScore'] < 8.5, 'Penalty'] += 1000
            df_s.loc[df_s['EI_Tip'] < 11.5, 'Penalty'] += 300
        
        if miss in ["Hook", "Pull"]:
            df_s['Penalty'] += (df_s['Torque'] * 200)
            df_s.loc[df_s['LaunchScore'] > 4, 'Penalty'] += 300

        if miss in ["Push", "Slice"]:
            df_s.loc[df_s['Torque'] < 1.6, 'Penalty'] += 150
            df_s.loc[df_s['EI_Tip'] > 13.0, 'Penalty'] += 200
            df_s.loc[df_s['LaunchScore'] < 4, 'Penalty'] += 150

        recs = df_s.sort_values(['Penalty', 'FlexScore'], ascending=[True, False]).head(5)

        # 3. Recommendations
        st.subheader("🚀 Top 5 Shaft Recommendations")
        def generate_note(row):
            notes = []
            if row['StabilityIndex'] > 8: notes.append("Max Stability")
            if row['Torque'] < 1.5: notes.append("Low Twist")
            if row['Weight (g)'] > 125: notes.append("Heavy Tempo")
            return " | ".join(notes) if notes else "Balanced"

        recs['Analysis'] = recs.apply(generate_note, axis=1)
        st.table(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Launch', 'Torque', 'Analysis']])

        # 4. Action Buttons
        st.divider()
        b_col1, b_col2, b_col3, _ = st.columns([2, 2, 2, 2])
        
        if b_col1.button("💾 Manual Save"):
            if save_lead_to_gsheet(st.session_state['answers'], tf, tl):
                st.success("Entry Saved!")

        if b_col2.button("✏️ Edit Survey"):
            st.session_state.interview_complete = False
            st.rerun()

        if b_col3.button("🆕 New Fitting"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
