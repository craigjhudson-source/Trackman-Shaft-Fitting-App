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
        creds = Credentials.from_service_account_info(
            creds_info, 
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        )
        gc = gspread.authorize(creds)
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit'
        sh = gc.open_by_url(SHEET_URL)
        
        def get_clean_df(worksheet_name):
            try:
                rows = sh.worksheet(worksheet_name).get_all_values()
                if not rows: return pd.DataFrame()
                headers = [h.strip() if h.strip() else f"Col_{i}" for i, h in enumerate(rows[0])]
                df = pd.DataFrame(rows[1:], columns=headers)
                return df
            except:
                return pd.DataFrame()

        return {
            'Heads': get_clean_df('Heads'),
            'Shafts': get_clean_df('Shafts'),
            'Questions': get_clean_df('Questions'),
            'Responses': get_clean_df('Responses'),
            'Config': get_clean_df('Config'),
            'Descriptions': get_clean_df('Descriptions')
        }
    except Exception as e:
        st.error(f"📡 Connection Error: {e}"); return None

# 🟢 NEW: FUNCTION TO SAVE DATA TO GOOGLE SHEETS
def save_to_fittings(answers):
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(
            creds_info, 
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        )
        gc = gspread.authorize(creds)
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit'
        sh = gc.open_by_url(SHEET_URL)
        worksheet = sh.worksheet('Fittings')
        
        # Prepare row: Timestamp + Q01 through Q23
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp]
        for i in range(1, 24):
            qid = f"Q{i:02d}"
            row.append(answers.get(qid, ""))
            
        worksheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"❌ Could not write to 'Fittings' tab: {e}")
        return False

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
                
                opts = list(dict.fromkeys([x for x in opts if x])) # Remove duplicates/blanks
                opts = [""] + opts
                st.selectbox(qtext, opts, index=opts.index(str(ans_val)) if str(ans_val) in opts else 0, key=f"widget_{qid}")
            
            elif qtype == "Numeric":
                st.number_input(qtext, value=float(ans_val) if ans_val else 0.0, key=f"widget_{qid}")
            else:
                st.text_input(qtext, value=str(ans_val), key=f"widget_{qid}")

        st.divider()
        c1, c2, _ = st.columns([1,1,4])
        
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
                # 🟢 SAVE TO GOOGLE SHEET ON FINISH
                save_to_fittings(st.session_state.answers)
                st.session_state.interview_complete = True
                st.rerun()

    else:
        # --- 4. MASTER FITTER REPORT ---
        st.title(f"🎯 Fitting Report: {st.session_state.answers.get('Q01', 'Player')}")
        
        # 🟢 RESTORED: QUESTIONNAIRE SUMMARY
        with st.expander("📋 View Full Questionnaire Summary", expanded=False):
            ver_cols = st.columns(3)
            for i, cat in enumerate(categories):
                with ver_cols[i % 3]:
                    st.markdown(f"**{cat}**")
                    cat_qs = q_master[q_master['Category'] == cat]
                    for _, q_row in cat_qs.iterrows():
                        ans = st.session_state.answers.get(str(q_row['QuestionID']).strip(), "—")
                        st.caption(f"{q_row['QuestionText']}: **{ans}**")

        # LOGIC CALCS
        try:
            val = st.session_state.answers.get('Q15', 150)
            carry_6i = float(val) if val else 150.0
        except: carry_6i = 150.0

        primary_miss = st.session_state.answers.get('Q18', '')
        
        # Flex/Weight targets
        if carry_6i >= 195: f_tf, ideal_w = 8.5, 130
        elif carry_6i >= 180: f_tf, ideal_w = 7.0, 120
        elif carry_6i >= 165: f_tf, ideal_w = 6.0, 110
        elif carry_6i >= 150: f_tf, ideal_w = 5.0, 95
        else: f_tf, ideal_w = 4.0, 85

        df_all = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'Weight (g)', 'Torque', 'StabilityIndex']:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)
        
        def score_shafts(df_in):
            df_in['Flex_Penalty'] = abs(df_in['FlexScore'] - f_tf) * 100
            df_in['Weight_Penalty'] = abs(df_in['Weight (g)'] - ideal_w) * 10
            if any(x in primary_miss for x in ["Hook", "Pull"]):
                df_in['Miss_Correction'] = (df_in['Torque'] * 50) + ((10 - df_in['StabilityIndex']) * 50)
            elif any(x in primary_miss for x in ["Slice", "Push"]):
                df_in['Miss_Correction'] = (abs(df_in['Torque'] - 3.5) * 30)
            else: df_in['Miss_Correction'] = 0
            return df_in['Flex_Penalty'] + df_in['Weight_Penalty'] + df_in['Miss_Correction']

        df_all['Total_Score'] = score_shafts(df_all)
        candidates = df_all.sort_values('Total_Score')

        # Archetype Selection
        final_recs = []
        final_recs.append(candidates[candidates['Material'].str.contains('Graphite', case=False, na=False)].head(1).assign(Archetype='🚀 Modern Power'))
        final_recs.append(candidates[candidates['Material'] == 'Steel'].head(1).assign(Archetype='⚓ Tour Standard'))
        final_recs.append(candidates[candidates['Model'].str.contains('LZ|Modus|KBS Tour', case=False, na=False)].head(1).assign(Archetype='🎨 Feel Option'))
        final_recs.append(candidates.sort_values(['StabilityIndex', 'Total_Score'], ascending=[False, True]).head(1).assign(Archetype='🎯 Dispersion Killer'))
        # 🟢 RESTORED: 5TH ARCHETYPE
        final_recs.append(candidates[candidates['Model'].str.contains('Fiber|MMT|Recoil|Axiom', case=False, na=False)].head(1).assign(Archetype='🧪 Alt Tech'))
        
        # 🟢 RESTORED: .head(5)
        final_df = pd.concat(final_recs).drop_duplicates(subset=['Model']).head(5)

        st.subheader("🚀 Top Recommended Prescription")
        st.table(final_df[['Archetype', 'Brand', 'Model', 'Flex', 'Weight (g)', 'Launch']])

        st.subheader("🔬 Expert Engineering Analysis")
        
        desc_lookup = {}
        if not all_data['Descriptions'].empty:
            desc_lookup = dict(zip(all_data['Descriptions']['Model'], all_data['Descriptions']['Blurb']))
        
        for _, row in final_df.iterrows():
            brand_model = f"{row['Brand']} {row['Model']}"
            blurb = desc_lookup.get(row['Model'], "Selected for optimized stability and transition timing based on carry distance.")
            st.markdown(f"**{row['Archetype']}: {brand_model}**")
            st.caption(f"{blurb}")

        st.divider()
        # 🟢 RESTORED: EDIT SURVEY BUTTON
        b1, b2, _ = st.columns([1,1,4])
        if b1.button("✏️ Edit Survey"):
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.rerun()
            
        if b2.button("🆕 New Fitting"):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.rerun()
