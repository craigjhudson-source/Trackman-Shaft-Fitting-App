import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime
import plotly.express as px # For the Visual DNA chart

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

def save_lead_to_gsheet(answers, target_flex, target_launch):
    try:
        # 1. Connect to your Sheet (Ensure the name matches exactly)
        gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        sh = gc.open("Your_Google_Sheet_Name") # Replace with your actual sheet name
        worksheet = sh.worksheet("fittings") # The specific tab name
        
        # 2. Build the row data using the updated Miss and Carry info
        # We use .get() to ensure if a field is missing, the code doesn't crash
        row = [
            pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), # Timestamp
            answers.get("Q01", "N/A"), # Name
            answers.get("Q02", "N/A"), # Email
            answers.get("Q15", 0),     # Carry
            answers.get("Q18", "N/A"), # Miss (The adjusted value)
            target_flex,               # Calculated Target Flex
            target_launch,             # Calculated Target Launch
            answers.get("Q10", ""),    # Current Shaft
            # Add any other columns you need in your Sheet here
        ]
        
        # 3. Append the row
        worksheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"Filing Error: {e}")
        return False

# --- 2. INITIALIZATION ---
st.set_page_config(page_title="Patriot Fitting Engine", layout="wide", page_icon="⛳")
all_data = get_data_from_gsheet()

if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state['answers'] = {f"Q{i:02d}": "" for i in range(1, 22)}

def sync_answers(q_list):
    for qid in q_list:
        if f"widget_{qid}" in st.session_state: 
            st.session_state['answers'][qid] = st.session_state[f"widget_{qid}"]

# --- 3. QUESTIONNAIRE ---
if all_data:
    if not st.session_state.interview_complete:
        st.title("Americas Best Shaft Fitting Engine")
        
        # Progress Bar
        categories = all_data['Questions']['Category'].unique().tolist()
        progress = (st.session_state.form_step) / (len(categories))
        st.progress(progress, text=f"Step {st.session_state.form_step + 1} of {len(categories)}")

        current_cat = categories[st.session_state.form_step]
        q_df = all_data['Questions'][all_data['Questions']['Category'] == current_cat]
        current_qids = q_df['QuestionID'].tolist()

        st.subheader(f"Section: {current_cat}")
        
        # Display Questions
        for _, row in q_df.iterrows():
            qid, qtext, qtype, qopts = row['QuestionID'], row['QuestionText'], row['InputType'], str(row['Options'])
            prev_val = st.session_state['answers'].get(qid, "")

            if qtype == "Dropdown":
                options = [""] # Default empty
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
                st.selectbox(qtext, options, index=idx, key=f"widget_{qid}", on_change=sync_answers, args=(current_qids,))
            
            elif qtype == "Numeric":
                st.number_input(qtext, value=float(prev_val) if prev_val else 0.0, key=f"widget_{qid}", on_change=sync_answers, args=(current_qids,))
            else:
                st.text_input(qtext, value=str(prev_val), key=f"widget_{qid}", on_change=sync_answers, args=(current_qids,))

        # Navigation
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
            sync_answers(current_qids)
            st.session_state.interview_complete = True
            st.rerun()

    else:
        # --- 4. RESULTS VIEW ---
        st.title(f"🎯 Fitting Report: {st.session_state['answers'].get('Q01', 'Player')}")
        
        # 1. DATA VERIFICATION SUMMARY (Replacing the Plotly Chart)
        st.subheader("📋 Input Verification Summary")
        
        # Grouping answers for readability
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

        # 2. CALCULATION ENGINE
        tf, tl = 6.0, 5.0 # Fallbacks
        for qid, ans in st.session_state['answers'].items():
            logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == str(ans))]
            if not logic.empty:
                act = str(logic.iloc[0]['LogicAction'])
                if "FlexScore:" in act: tf = float(act.split(":")[1])
                if "LaunchScore:" in act: tl = float(act.split(":")[1])

        df_s = all_data['Shafts'].copy()
        # Convert numeric columns safely
        for col in ['FlexScore', 'LaunchScore', 'StabilityIndex', 'Weight (g)', 'EI_Tip', 'Torque']:
            df_s[col] = pd.to_numeric(df_s[col], errors='coerce')

       # 1. Baseline Penalty (Multiplier increased to 150 for Flex to make it the priority)
        df_s['Penalty'] = (abs(df_s['FlexScore'] - tf) * 150) + (abs(df_s['LaunchScore'] - tl) * 20)
        
        # 2. Strict Tour Speed Floor (For 190+ yards)
        if carry >= 190:
            # Penalize anything under 120g heavily
            df_s.loc[df_s['Weight (g)'] < 120, 'Penalty'] += 500
            # Penalize anything under an X-Flex (FlexScore 8.5) heavily
            df_s.loc[df_s['FlexScore'] < 8.5, 'Penalty'] += 1000
            # Stability check
            df_s.loc[df_s['EI_Tip'] < 11.5, 'Penalty'] += 300
        
        # 3. Anti-Left / Hook Logic
        if miss in ["Hook", "Pull"]:
            df_s['Penalty'] += (df_s['Torque'] * 200)
            # High launch + Hook = Disaster. Heavy penalty.
            df_s.loc[df_s['LaunchScore'] > 4, 'Penalty'] += 300

        # Final Sorting
        recs = df_s.sort_values(['Penalty', 'FlexScore'], ascending=[True, False]).head(5)

        # 3. RECOMMENDATIONS TABLE
        st.subheader("🚀 Top 5 Shaft Recommendations")
        
        # Adding a custom "Fitters Note" column based on the profile
        def generate_note(row):
            notes = []
            if row['StabilityIndex'] > 8: notes.append("Max Stability")
            if row['Torque'] < 1.5: notes.append("Low Twist")
            if row['Weight (g)'] > 125: notes.append("Heavy Tempo")
            return " | ".join(notes) if notes else "Balanced"

        recs['Analysis'] = recs.apply(generate_note, axis=1)

        st.table(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Launch', 'Torque', 'Analysis']])

       # 4. ACTION BUTTONS
        st.divider()
        # Create 3 columns instead of 2
        btn_col1, btn_col2, btn_col3, _ = st.columns([2, 2, 2, 2])
        
        if btn_col1.button("💾 Save to Google Sheets"):
            if save_lead_to_gsheet(st.session_state['answers'], tf, tl):
                st.success("Entry Saved!")
            else: st.error("Save Error.")

        # THIS IS THE NEW BUTTON
        if btn_col2.button("✏️ Edit Survey"):
            st.session_state.interview_complete = False
            st.rerun()

        if btn_col3.button("🆕 New Fitting"):
            # This clears everything to start fresh
            for key in st.session_state.keys(): del st.session_state[key]
            st.rerun()
