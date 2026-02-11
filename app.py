import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime

# --- 1. DATA CONNECTION & ROBUST CLEANING ---
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
            # Get raw values to handle empty/duplicate headers manually
            rows = sh.worksheet(worksheet_name).get_all_values()
            if not rows: return pd.DataFrame()
            
            headers = rows[0]
            seen = {}
            new_headers = []
            for i, h in enumerate(headers):
                h = h.strip()
                if not h: h = f"EmptyCol_{i}"
                if h in seen:
                    seen[h] += 1
                    new_headers.append(f"{h}_{seen[h]}")
                else:
                    seen[h] = 0
                    new_headers.append(h)
            # Create DF and drop columns that are purely 'EmptyCol' artifacts
            df = pd.DataFrame(rows[1:], columns=new_headers)
            return df.loc[:, ~df.columns.str.startswith('EmptyCol')]

        return {
            'Heads': get_clean_df('Heads'),
            'Shafts': get_clean_df('Shafts'),
            'Questions': get_clean_df('Questions'),
            'Responses': get_clean_df('Responses'),
            'Config': get_clean_df('Config'),
            'Descriptions': get_clean_df('Descriptions')  # New sheet for blurbs
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
        
        with st.expander("📋 View Full Input Verification Summary", expanded=False):
            ver_cols = st.columns(3)
            for i, cat in enumerate(categories):
                with ver_cols[i % 3]:
                    st.markdown(f"**{cat}**")
                    cat_qs = q_master[q_master['Category'] == cat]
                    for _, q_row in cat_qs.iterrows():
                        ans = st.session_state.answers.get(str(q_row['QuestionID']).strip(), "—")
                        st.caption(f"{q_row['QuestionText']}: **{ans}**")

        # ENGINE LOGIC
        carry_6i = float(st.session_state.answers.get('Q15', 150))
        primary_miss = st.session_state.answers.get('Q17', '')
        
        # Flex/Weight targets
        if carry_6i >= 200: min_w, f_tf, ideal_w = 120, 9.0, 130
        elif carry_6i >= 180: min_w, f_tf, ideal_w = 115, 7.5, 125
        elif carry_6i >= 160: min_w, f_tf, ideal_w = 105, 6.0, 115
        else: min_w, f_tf, ideal_w = 0, 4.0, 95

        df_all = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'Weight (g)', 'Torque', 'StabilityIndex']:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)
        
        def score_shafts(df_in):
            df_in['Flex_Penalty'] = abs(df_in['FlexScore'] - f_tf) * 100
            df_in['Weight_Penalty'] = abs(df_in['Weight (g)'] - ideal_w) * 10
            # Miss correction
            if any(x in primary_miss for x in ["Hook", "Pull"]):
                df_in['Miss_Correction'] = (df_in['Torque'] * 50) + ((10 - df_in['StabilityIndex']) * 50)
            elif any(x in primary_miss for x in ["Slice", "Push"]):
                df_in['Miss_Correction'] = (abs(df_in['Torque'] - 3.5) * 30)
            else:
                df_in['Miss_Correction'] = 0
            return df_in['Flex_Penalty'] + df_in['Weight_Penalty'] + df_in['Miss_Correction']

        df_all['Total_Score'] = score_shafts(df_all)
        candidates = df_all.sort_values('Total_Score')

        # Archetype Selection
        final_recs = []
        final_recs.append(candidates[candidates['Material'].str.contains('Graphite', case=False)].head(1).assign(Archetype='🚀 Modern Power'))
        final_recs.append(candidates[candidates['Material'] == 'Steel'].head(1).assign(Archetype='⚓ Tour Standard'))
        final_recs.append(candidates[candidates['Model'].str.contains('LZ|Modus|KBS Tour', case=False)].head(1).assign(Archetype='🎨 Feel Option'))
        final_recs.append(candidates.sort_values(['StabilityIndex', 'Total_Score'], ascending=[False, True]).head(1).assign(Archetype='🎯 Dispersion Killer'))
        final_recs.append(candidates[candidates['Model'].str.contains('Fiber|MMT|Recoil|Axiom', case=False)].head(1).assign(Archetype='🧪 Alt Tech'))

        final_df = pd.concat(final_recs).drop_duplicates(subset=['Model']).head(5)

        st.subheader("🚀 Top Recommended Prescription")
        st.table(final_df[['Archetype', 'Brand', 'Model', 'Material', 'Flex', 'Weight (g)', 'Launch']])

        st.subheader("🔬 Expert Engineering Analysis")
        
        desc_lookup = dict(zip(all_data['Descriptions'].iloc[:,0], all_data['Descriptions'].iloc[:,1]))
        
        for _, row in final_df.iterrows():
            brand_model = f"{row['Brand']} {row['Model']}"
            blurb = desc_lookup.get(row['Model'], "High-stability profile selected for speed and trajectory control.")
            st.markdown(f"**{row['Archetype']}: {brand_model}**")
            st.caption(f"{blurb}")

        # --- GRIP PRESCRIPTION ---
        st.divider()
        st.subheader("🧤 Final Touch: Grip Prescription")
        g_size = st.session_state.answers.get('Q05', 'Large')
        rec_size = "Midsize" if g_size in ['Large', 'Extra Large'] else "Standard"
        grip_model = "Golf Pride MCC Plus4" if carry_6i > 170 else "Golf Pride CP2 Wrap"
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Recommended Size", rec_size)
        c2.metric("Suggested Model", grip_model)
        c3.metric("Tape Spec", "+1 Wrap" if rec_size == "Midsize" else "Standard")

        st.divider()
        if st.button("🆕 New Fitting"):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.rerun()
