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
            # Fetch all values instead of records to manually handle headers
            list_of_lists = sh.worksheet(worksheet_name).get_all_values()
            if not list_of_lists:
                return pd.DataFrame()
            
            headers = list_of_lists[0]
            # Rename empty or duplicate headers to prevent pandas/gspread crashes
            clean_headers = []
            for i, h in enumerate(headers):
                h = str(h).strip()
                if h == "" or h in clean_headers:
                    clean_headers.append(f"Unnamed_{i}")
                else:
                    clean_headers.append(h)
            
            return pd.DataFrame(list_of_lists[1:], columns=clean_headers)

        data = {
            'Heads': get_clean_df('Heads'),
            'Shafts': get_clean_df('Shafts'),
            'Questions': get_clean_df('Questions'),
            'Responses': get_clean_df('Responses'),
            'Config': get_clean_df('Config')
        }
        return data
    except Exception as e:
        st.error(f"📡 Connection Error: {e}")
        return None

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
            sync_answers(q_df['QuestionID'].tolist()); st.session_state.form_step -= 1; st.rerun()
        
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"):
                sync_answers(q_df['QuestionID'].tolist()); st.session_state.form_step += 1; st.rerun()
        else:
            if c2.button("🔥 Generate Prescription"):
                sync_answers(q_master['QuestionID'].tolist())
                st.session_state.interview_complete = True; st.rerun()

    else:
        # --- 4. MASTER FITTER REPORT ---
        st.title(f"🎯 Fitting Report: {st.session_state.answers.get('Q01', 'Player')}")
        
        with st.expander("📋 View Full Input Verification Summary", expanded=True):
            ver_cols = st.columns(3)
            for i, cat in enumerate(categories):
                with ver_cols[i % 3]:
                    st.markdown(f"**{cat}**")
                    cat_qs = q_master[q_master['Category'] == cat]
                    for _, q_row in cat_qs.iterrows():
                        ans = st.session_state.answers.get(str(q_row['QuestionID']).strip(), "—")
                        st.caption(f"{q_row['QuestionText']}: **{ans}**")

        # ENGINE LOGIC
        primary_miss = st.session_state.answers.get('Q17', '')
        try:
            carry_6i = float(st.session_state.answers.get('Q15', 0))
        except:
            carry_6i = 0.0

        # Determine Specs based on Speed/Carry
        if carry_6i >= 200: f_tf, ideal_w = 9.0, 125
        elif carry_6i >= 180: f_tf, ideal_w = 7.5, 115
        elif carry_6i >= 160: f_tf, ideal_w = 6.0, 105
        else: f_tf, ideal_w = 4.0, 85

        df_all = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'Weight (g)', 'Torque', 'StabilityIndex']:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)
        
        def score_shafts(df):
            flex_pen = abs(df['FlexScore'] - f_tf) * 100
            weight_pen = abs(df['Weight (g)'] - ideal_w) * 10
            return flex_pen + weight_pen

        df_all['Total_Score'] = score_shafts(df_all)
        candidates = df_all.sort_values('Total_Score')

        # Archetype Picks
        final_recs = []
        final_recs.append(candidates[candidates['Material'].str.contains('Graphite|Carbon', case=False, na=False)].head(1))
        final_recs.append(candidates[candidates['Material'].str.contains('Steel', case=False, na=False)].head(1))
        final_recs.append(candidates[candidates['Model'].str.contains('LZ|Modus|KBS Tour', case=False, na=False)].head(1))
        final_recs.append(candidates.sort_values('StabilityIndex', ascending=False).head(1))
        final_recs.append(candidates[candidates['Model'].str.contains('Fiber|MMT|Recoil|Axiom', case=False, na=False)].head(1))

        final_df = pd.concat(final_recs).drop_duplicates(subset=['Model']).head(5)
        archetypes = ['🚀 Modern Power', '⚓ Tour Standard', '🎨 Feel Option', '🎯 Dispersion Killer', '🧪 Alt Tech']
        final_df['Archetype'] = archetypes[:len(final_df)]

        st.subheader("🚀 Top Recommended Prescription")
        st.table(final_df[['Archetype', 'Brand', 'Model', 'Flex', 'Weight (g)', 'Launch']])

        # EXPERT ANALYSIS
        st.subheader("🔬 Expert Engineering Analysis")
                for _, row in final_df.iterrows():
            blurb = row.get('Description', "Precision-matched profile selected to optimize energy transfer and impact stability.")
            st.markdown(f"**{row['Archetype']}: {row['Brand']} {row['Model']}**")
            st.caption(f"{blurb}")

        st.divider()
        b1, b2, _ = st.columns([1,1,4])
        if b1.button("✏️ Edit Survey"): st.session_state.interview_complete = False; st.rerun()
        if b2.button("🆕 New Fitting"):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.rerun()
            
