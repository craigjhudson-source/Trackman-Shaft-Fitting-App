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

def save_to_fittings(answers):
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        gc = gspread.authorize(creds)
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit'
        sh = gc.open_by_url(SHEET_URL)
        worksheet = sh.worksheet('Fittings')
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp]
        for i in range(1, 24):
            qid = f"Q{i:02d}"
            row.append(answers.get(qid, ""))
        worksheet.append_row(row)
    except Exception as e:
        st.error(f"Error saving to Sheets: {e}")

# --- 2. STATE MANAGEMENT ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state.answers = {}

all_data = get_data_from_gsheet()

def sync_all():
    for key in st.session_state:
        if key.startswith("widget_"):
            qid = key.replace("widget_", "")
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
                if "Heads" in qopts:
                    brand_val = st.session_state.get("widget_Q08", "")
                    if "Brand" in qtext:
                        opts += sorted(all_data['Heads']['Manufacturer'].unique().tolist())
                    else:
                        if brand_val: opts += sorted(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand_val]['Model'].unique().tolist())
                        else: opts = ["Select Brand First"]
                elif "Shafts" in qopts:
                    s_brand = st.session_state.get("widget_Q10", "")
                    s_flex = st.session_state.get("widget_Q11", "")
                    if "Brand" in qtext:
                        opts += sorted(all_data['Shafts']['Brand'].unique().tolist())
                    elif "Flex" in qtext:
                        if s_brand: opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == s_brand]['Flex'].unique().tolist())
                        else: opts = ["Select Brand First"]
                    elif "Model" in qtext:
                        if s_brand and s_flex:
                            filtered = all_data['Shafts'][(all_data['Shafts']['Brand'] == s_brand) & (all_data['Shafts']['Flex'] == s_flex)]
                            opts += sorted(filtered['Model'].unique().tolist())
                        elif s_brand: opts = ["Select Flex First"]
                        else: opts = ["Select Brand First"]
                elif "Config:" in qopts:
                    col = qopts.split(":")[1].strip()
                    if col in all_data['Config'].columns: opts += all_data['Config'][col].dropna().tolist()
                else:
                    opts += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].tolist()

                opts = list(dict.fromkeys([str(x) for x in opts if x]))
                if "" not in opts: opts = [""] + opts
                st.selectbox(qtext, opts, index=opts.index(str(ans_val)) if str(ans_val) in opts else 0, key=f"widget_{qid}", on_change=sync_all)

            elif qtype == "Numeric":
                st.number_input(qtext, value=float(ans_val) if ans_val else 0.0, key=f"widget_{qid}", on_change=sync_all)
            else:
                st.text_input(qtext, value=str(ans_val), key=f"widget_{qid}", on_change=sync_all)

        st.divider()
        c1, c2, _ = st.columns([1,1,4])
        if c1.button("⬅️ Back") and st.session_state.form_step > 0:
            sync_all(); st.session_state.form_step -= 1; st.rerun()
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"): sync_all(); st.session_state.form_step += 1; st.rerun()
        else:
            if c2.button("🔥 Generate Prescription"):
                sync_all(); save_to_fittings(st.session_state.answers); st.session_state.interview_complete = True; st.rerun()

    else:
        # --- 4. MASTER FITTER REPORT (MATRIX VIEW) ---
        st.title(f"🎯 Master Fitting Matrix: {st.session_state.answers.get('Q01', 'Player')}")
        
        with st.expander("👤 View Player Profile Summary"):
            ver_cols = st.columns(4)
            for i, cat in enumerate(categories):
                with ver_cols[i % 4]:
                    st.markdown(f"**{cat}**")
                    cat_qs = q_master[q_master['Category'] == cat]
                    for _, q_row in cat_qs.iterrows():
                        ans = st.session_state.answers.get(str(q_row['QuestionID']).strip(), "—")
                        st.caption(f"{q_row['QuestionText']}: **{ans}**")

        st.divider()

        # LOGIC PREP
        try: carry_6i = float(st.session_state.answers.get('Q15', 150))
        except: carry_6i = 150.0
        primary_miss = st.session_state.answers.get('Q18', '')
        target_flight = st.session_state.answers.get('Q17', 'Mid')
        target_feel = st.session_state.answers.get('Q20', 'Unsure')
        feel_priority = st.session_state.answers.get('Q21', '1 - Do. Not. Care!')
        current_shaft_model = st.session_state.answers.get('Q12', 'Unknown')
        
        if carry_6i >= 195: f_tf, ideal_w = 8.5, 130
        elif carry_6i >= 180: f_tf, ideal_w = 7.0, 125
        elif carry_6i >= 165: f_tf, ideal_w = 6.0, 110
        elif carry_6i >= 150: f_tf, ideal_w = 5.0, 95
        else: f_tf, ideal_w = 4.0, 80

        df_all = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'Weight (g)', 'Torque', 'StabilityIndex', 'EI_Mid']:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)

        def get_top_3(df_in, mode):
            df_temp = df_in.copy()
            df_temp['Penalty'] = abs(df_temp['FlexScore'] - f_tf) * 200
            if carry_6i >= 180: df_temp.loc[df_temp['FlexScore'] < 6.5, 'Penalty'] += 4000
            df_temp['Penalty'] += abs(df_temp['Weight (g)'] - ideal_w) * 15
            
            if mode == "Maximum Stability":
                df_temp['Penalty'] -= (df_temp['StabilityIndex'] * 600)
            elif mode == "Launch & Height":
                df_temp['Penalty'] -= (df_temp['LaunchScore'] * 500)
            elif mode == "Feel & Smoothness":
                df_temp['Penalty'] += (df_temp['EI_Mid'] * 400)
            
            res = df_temp.sort_values('Penalty').head(3)[['Brand', 'Model', 'Flex', 'Weight (g)', 'Launch']]
            # Current vs New Logic
            res['Status'] = res['Model'].apply(lambda x: "✅ CURRENT" if x == current_shaft_model else "🆕 NEW")
            return res

        # MATRIX DISPLAY
        modes = ["Balanced", "Maximum Stability", "Launch & Height", "Feel & Smoothness"]
        row1_cols = st.columns(2)
        row2_cols = st.columns(2)
        all_cols = row1_cols + row2_cols
        
        winners = {} # Store winners for the verdict
        for i, mode in enumerate(modes):
            with all_cols[i]:
                st.subheader(f"🚀 {mode}")
                top_df = get_top_3(df_all, mode)
                winners[mode] = top_df.iloc[0]
                st.table(top_df)

        st.divider()
        
        # --- EXPANDED TECHNICAL VERDICT ---
        st.subheader("🔬 Fitter's Technical Verdict")
        desc_lookup = dict(zip(all_data['Descriptions']['Model'], all_data['Descriptions']['Blurb'])) if not all_data['Descriptions'].empty else {}
        
        # Columned Verdicts for clarity
        v_col1, v_col2 = st.columns(2)
        
        with v_col1:
            # BALANCED VERDICT
            b_win = winners["Balanced"]
            st.markdown(f"**Primary Fit (Balanced): {b_win['Brand']} {b_win['Model']}**")
            st.write(f"Chosen because it aligns most closely with your {carry_6i}yd carry requirements. {desc_lookup.get(b_win['Model'], 'Optimized for total control.')}")
            
            # STABILITY VERDICT
            s_win = winners["Maximum Stability"]
            st.markdown(f"**Stability Optimization: {s_win['Brand']} {s_win['Model']}**")
            st.write(f"We prioritized the **Stability Index** here. Given your miss is a **{primary_miss}**, this shaft's reinforced section helps stabilize the face through impact to tighten dispersion.")

        with v_col2:
            # LAUNCH VERDICT
            l_win = winners["Launch & Height"]
            st.markdown(f"**Flight Optimization: {l_win['Brand']} {l_win['Model']}**")
            st.write(f"Specifically selected to achieve your **{target_flight}** flight target. This profile utilizes a specific tip-stiffness to manipulate the dynamic loft.")
            
            # FEEL VERDICT
            f_win = winners["Feel & Smoothness"]
            st.markdown(f"**Feel Optimization: {f_win['Brand']} {f_win['Model']}**")
            st.write(f"A recommendation for when **{target_feel}** feel is the priority. This shaft features a higher mid-section energy transfer (EI Mid) for a smoother transition.")

        

        if st.button("🆕 New Fitting"):
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.session_state.answers = {}
            st.rerun()
