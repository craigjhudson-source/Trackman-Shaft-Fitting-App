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

# FUNCTION TO SAVE DATA TO "FITTINGS" TAB
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
                    brand = st.session_state.get("widget_Q08", st.session_state.answers.get("Q08", ""))
                    if "Brand" in qtext: opts += sorted(all_data['Heads']['Manufacturer'].unique().tolist())
                    else: opts += sorted(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].unique().tolist()) if brand else []
                elif "Shafts" in qopts:
                    brand = st.session_state.get("widget_Q10", st.session_state.answers.get("Q10", ""))
                    if "Brand" in qtext: opts += sorted(all_data['Shafts']['Brand'].unique().tolist())
                    elif "Flex" in qtext: opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Flex'].unique().tolist()) if brand else []
                    else: opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == brand]['Model'].unique().tolist()) if brand else []
                else:
                    opts += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].astype(str).tolist()
                
                opts = list(dict.fromkeys([x for x in opts if x]))
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
                save_to_fittings(st.session_state.answers)
                st.session_state.interview_complete = True
                st.rerun()

    else:
        # --- 4. MASTER FITTER REPORT ---
        st.title(f"🎯 Fitting Report: {st.session_state.answers.get('Q01', 'Player')}")
        
        # 4a. PROFILE SUMMARY
        st.subheader("📋 Player Profile Summary")
        ver_cols = st.columns(4)
        for i, cat in enumerate(categories):
            with ver_cols[i % 4]:
                st.markdown(f"**{cat}**")
                cat_qs = q_master[q_master['Category'] == cat]
                for _, q_row in cat_qs.iterrows():
                    ans = st.session_state.answers.get(str(q_row['QuestionID']).strip(), "—")
                    st.caption(f"{q_row['QuestionText']}: **{ans}**")
        
        st.divider()

        # 4b. REFINEMENT TOGGLE
        st.subheader("🛠 Refine Recommendations")
        refine_choice = st.radio(
            "Select the primary optimization goal to re-rank the prescription:",
            ["Balanced (Engine Choice)", "Maximum Stability (Kill the Miss)", "Launch & Height", "Feel & Smoothness"],
            horizontal=True
        )

        # LOGIC CALCS
        try:
            carry_6i = float(st.session_state.answers.get('Q15', 150))
        except: carry_6i = 150.0

        primary_miss = st.session_state.answers.get('Q18', '')
        target_flight = st.session_state.answers.get('Q17', 'Mid')
        target_feel = st.session_state.answers.get('Q20', 'Unsure')
        feel_priority = st.session_state.answers.get('Q21', '1 - Do. Not. Care!')
        
        if carry_6i >= 195: f_tf, ideal_w = 8.5, 130
        elif carry_6i >= 180: f_tf, ideal_w = 7.0, 125
        elif carry_6i >= 165: f_tf, ideal_w = 6.0, 110
        elif carry_6i >= 150: f_tf, ideal_w = 5.0, 95
        else: f_tf, ideal_w = 4.0, 80

        df_all = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'Weight (g)', 'Torque', 'StabilityIndex', 'EI_Mid']:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)
        
        def score_shafts(df_in):
            # BASE SCORING LOGIC
            df_in['Flex_Penalty'] = abs(df_in['FlexScore'] - f_tf) * 200
            if carry_6i >= 180:
                df_in.loc[df_in['FlexScore'] < 6.5, 'Flex_Penalty'] += 4000
            if carry_6i >= 195:
                df_in.loc[df_in['FlexScore'] < 7.5, 'Flex_Penalty'] += 4000

            df_in['Weight_Penalty'] = abs(df_in['Weight (g)'] - ideal_w) * 15
            
            if any(x in primary_miss for x in ["Hook", "Pull"]):
                df_in['Miss_Correction'] = (df_in['Torque'] * 100) + ((10 - df_in['StabilityIndex']) * 150)
            elif any(x in primary_miss for x in ["Slice", "Push"]):
                df_in['Miss_Correction'] = (abs(df_in['Torque'] - 3.5) * 75)
            else: df_in['Miss_Correction'] = 0
            
            launch_map = {"Low": 2.0, "Mid-Low": 3.5, "Mid": 5.0, "Mid-High": 6.5, "High": 8.0}
            target_l = launch_map.get(target_flight, 5.0)
            df_in['Launch_Penalty'] = abs(df_in['LaunchScore'] - target_l) * 150
            
            if target_flight == "High":
                df_in.loc[df_in['LaunchScore'] < 4.0, 'Launch_Penalty'] += 2000
            elif target_flight == "Low":
                df_in.loc[df_in['LaunchScore'] > 6.0, 'Launch_Penalty'] += 2000

            df_in['Feel_Adjustment'] = 0
            if target_feel in ["Smooth", "Whippy", "Responsive"] and any(x in feel_priority for x in ["4", "5"]):
                df_in['Feel_Adjustment'] = (df_in['EI_Mid'] - 16.0) * 100
            elif target_feel in ["Firm", "Boardy", "Stable"] and any(x in feel_priority for x in ["4", "5"]):
                df_in['Feel_Adjustment'] = (22.0 - df_in['EI_Mid']) * 100
            
            return df_in['Flex_Penalty'] + df_in['Weight_Penalty'] + df_in['Miss_Correction'] + df_in['Launch_Penalty'] + df_in['Feel_Adjustment']

        # Calculate initial score
        df_all['Total_Score'] = score_shafts(df_all)

        # 4c. APPLY AGGRESSIVE REFINEMENT WEIGHTS (Boosted to ensure Rank changes)
        if refine_choice == "Maximum Stability (Kill the Miss)":
            df_all['Total_Score'] -= (df_all['StabilityIndex'] * 600)
        elif refine_choice == "Launch & Height":
            df_all['Total_Score'] -= (df_all['LaunchScore'] * 500)
        elif refine_choice == "Feel & Smoothness":
            # For 'Smoothness', we favor a lower EI_Mid (more bend) for the weight class
            df_all['Total_Score'] += (df_all['EI_Mid'] * 400)

        # 4d. ARCHETYPE PICKING (Ensuring fresh sort)
        final_list = []
        # MUST re-sort here based on the new weighted score
        temp_candidates = df_all.sort_values('Total_Score', ascending=True).copy()

        def pick_and_pop(query, label):
            match = temp_candidates.query(query).head(1)
            if not match.empty:
                idx = match.index[0]
                res = match.assign(Archetype=label)
                temp_candidates.drop(idx, inplace=True)
                return res
            return pd.DataFrame()

        final_list.append(pick_and_pop("Material.str.contains('Graphite', case=False)", "🚀 Modern Power"))
        final_list.append(pick_and_pop("Material == 'Steel'", "⚓ Tour Standard"))
        final_list.append(pick_and_pop("Model.str.contains('LZ|Modus|KBS Tour|Elevate', case=False)", "🎨 Feel Option"))
        
        # Dispersion killer takes the absolute #1 remaining based on the new weighted score
        top_stab = temp_candidates.head(1).assign(Archetype="🎯 Dispersion Killer")
        if not top_stab.empty:
            final_list.append(top_stab)
            temp_candidates.drop(top_stab.index[0], inplace=True)
        
        final_list.append(pick_and_pop("Model.str.contains('Fiber|MMT|Recoil|Axiom', case=False)", "🧪 Alt-Tech Hybrid"))

        # Re-sort the final 5 by the Total_Score to show the "Winning" Rank
        final_df = pd.concat(final_list).sort_values('Total_Score').reset_index(drop=True)
        final_df.index = final_df.index + 1
        final_df.index.name = "Rank"

        # 4e. RESULTS DISPLAY
        st.subheader(f"🚀 Top Recommended Prescription (Sorted by: {refine_choice})")
        st.table(final_df[['Archetype', 'Brand', 'Model', 'Flex', 'Weight (g)', 'Launch']])
        
        tip_logic = "an active tip-section to increase peak height" if target_flight == "High" else "increased tip-stiffness to lower launch"
        st.info(f"💡 **Fitter's Verdict:** Based on a {int(carry_6i)}-yard carry, we are optimizing for land angle and spin. These selections utilize {tip_logic} to eliminate the '{primary_miss}' miss.")

        st.subheader("🔬 Expert Engineering Analysis")
        desc_lookup = dict(zip(all_data['Descriptions']['Model'], all_data['Descriptions']['Blurb'])) if not all_data['Descriptions'].empty else {}
        
        for idx, row in final_df.iterrows():
            with st.container():
                st.markdown(f"**Rank {idx} - {row['Archetype']}: {row['Brand']} {row['Model']}**")
                st.caption(desc_lookup.get(row['Model'], "Selected for optimized stability and transition timing."))

        st.divider()
        b1, b2, _ = st.columns([1,1,4])
        if b1.button("✏️ Edit Survey"):
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.rerun()
        if b2.button("🆕 New Fitting"):
            st.session_state.interview_complete = False
            st.session_state.form_step = 0
            st.session_state.answers = {}
            st.rerun()
