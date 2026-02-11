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

def save_lead_to_gsheet(answers, t_flex, t_launch):
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        ws = sh.worksheet('Fittings')
        # Map Q01-Q21 into a single row
        row = [str(datetime.datetime.now())] + [answers.get(f"Q{i:02d}", "") for i in range(1, 22)] + [t_flex, t_launch]
        ws.append_row(row)
        return True
    except: return False

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
        
        # 1. Verification Bar
        carry = float(st.session_state['answers'].get('Q15', 0))
        miss = st.session_state['answers'].get('Q18', "")
        
        with st.container(border=True):
            v1, v2, v3, v4 = st.columns(4)
            v1.metric("6i Carry", f"{carry} yds")
            v2.metric("Primary Miss", miss)
            v3.metric("Target Flight", st.session_state['answers'].get('Q17', "Mid"))
            v4.metric("Current Flex", st.session_state['answers'].get('Q11', "N/A"))

        # 2. Logic Processing
        tf, tl = 6.0, 5.0 # Fallbacks
        for qid, ans in st.session_state['answers'].items():
            logic = all_data['Responses'][(all_data['Responses']['QuestionID'] == qid) & (all_data['Responses']['ResponseOption'] == str(ans))]
            if not logic.empty:
                act = str(logic.iloc[0]['LogicAction'])
                if "FlexScore:" in act: tf = float(act.split(":")[1])
                if "LaunchScore:" in act: tl = float(act.split(":")[1])

        # 3. Penalty Engine
        df_s = all_data['Shafts'].copy()
        df_s['FlexScore'] = pd.to_numeric(df_s['FlexScore'], errors='coerce')
        df_s['LaunchScore'] = pd.to_numeric(df_s['LaunchScore'], errors='coerce')
        df_s['StabilityIndex'] = pd.to_numeric(df_s['StabilityIndex'], errors='coerce')
        df_s['Weight'] = pd.to_numeric(df_s['Weight (g)'], errors='coerce')

        df_s['Penalty'] = (abs(df_s['FlexScore'] - tf) * 40) + (abs(df_s['LaunchScore'] - tl) * 20)
        
        # Apply Stability Overrides
        if carry > 185:
            df_s.loc[df_s['Weight'] < 115, 'Penalty'] += 300 
            df_s.loc[df_s['FlexScore'] < 7.0, 'Penalty'] += 150
        
        if "Hook" in miss or "Pull" in miss:
            df_s.loc[df_s['StabilityIndex'] < 7.0, 'Penalty'] += 200

        recs = df_s.sort_values(['Penalty', 'Weight'], ascending=[True, False]).head(5)

        # 4. Visualization: Shaft DNA Chart
        st.subheader("📊 Recommendation Profile")
        
        fig = px.scatter(recs, x="LaunchScore", y="StabilityIndex", 
                         text="Model", size="Weight", color="Brand",
                         labels={"LaunchScore": "Launch Profile (Low to High)", "StabilityIndex": "Stability (Tip Stiffness)"},
                         title="Recommended Shaft DNA")
        fig.add_hline(y=7.0, line_dash="dash", annotation_text="High Stability Zone")
        st.plotly_chart(fig, use_container_width=True)

        # 5. Result Table
        st.subheader("🚀 Top 5 Optimized Blueprints")
        st.dataframe(recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'Launch', 'Spin', 'StabilityIndex']], use_container_width=True)
        
        # 6. Action Footer
        st.divider()
        f1, f2, _ = st.columns([2,2,3])
        if f1.button("💾 Save Results to Cloud"):
            with st.status("Uploading to Google Sheets..."):
                if save_lead_to_gsheet(st.session_state['answers'], tf, tl):
                    st.success("Results Synchronized!")
                else: st.error("Sync Failed.")

        if f2.button("🆕 Start New Fitting"):
            for key in st.session_state.keys(): del st.session_state[key]
            st.rerun()
