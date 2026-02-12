import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime
# IMPORT FROM UTILS
from utils import create_pdf_bytes, send_email_with_pdf

st.set_page_config(page_title="Tour Proven Shaft Fitting", layout="wide", page_icon="⛳")

# --- STYLING ---
st.markdown("""
    <style>
    [data-testid="stTable"] { font-size: 12px !important; }
    .profile-bar { background-color: #142850; color: white; padding: 20px; border-radius: 10px; margin-bottom: 25px; }
    .profile-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
    .verdict-text { font-style: italic; color: #444; margin-bottom: 25px; font-size: 13px; border-left: 3px solid #b40000; padding-left: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- DATABASE LOGIC ---
def get_google_creds(scopes):
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        if "private_key" in creds_dict:
            pk = creds_dict["private_key"].replace("\\n", "\n")
            if "-----BEGIN PRIVATE KEY-----" in pk: pk = pk[pk.find("-----BEGIN PRIVATE KEY-----"):]
            creds_dict["private_key"] = pk.strip()
        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    except Exception as e:
        st.error(f"🔐 Security Error: {e}"); st.stop()

@st.cache_data(ttl=600)
def get_data_from_gsheet():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = get_google_creds(scopes); gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        def get_clean_df(ws_name):
            rows = sh.worksheet(ws_name).get_all_values()
            df = pd.DataFrame(rows[1:], columns=[h.strip() if h.strip() else f"Col_{i}" for i, h in enumerate(rows[0])])
            return df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
        return {k: get_clean_df(k) for k in ['Heads', 'Shafts', 'Questions', 'Responses', 'Config', 'Descriptions']}
    except Exception as e:
        st.error(f"📡 Database Error: {e}"); return None

def save_to_fittings(answers):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = get_google_creds(scopes); gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        worksheet = sh.worksheet('Fittings')
        row = [datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")] + [answers.get(f"Q{i:02d}", "") for i in range(1, 22)]
        worksheet.append_row(row)
    except Exception as e: st.error(f"Error saving: {e}")

# --- TRACKMAN LAB ---
def process_trackman_file(uploaded_file, shaft_id):
    try:
        df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        m_map = {'Club Speed': 'Club Speed', 'Spin Rate': 'Spin Rate', 'Carry': 'Carry', 'Smash Factor': 'Smash Factor'}
        results = {"Shaft ID": shaft_id}
        for label, tm_col in m_map.items():
            actual_col = next((c for c in df.columns if tm_col in c), None)
            if actual_col: results[label] = round(pd.to_numeric(df[actual_col], errors='coerce').mean(), 1)
        return results
    except: return None

# --- SESSION MGMT ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state.answers = {}
if 'email_sent' not in st.session_state: st.session_state.email_sent = False
if 'tm_lab_data' not in st.session_state: st.session_state.tm_lab_data = []

def sync_all():
    for key in st.session_state:
        if key.startswith("widget_"): st.session_state.answers[key.replace("widget_", "")] = st.session_state[key]

# --- MAIN APP FLOW ---
all_data = get_data_from_gsheet()
if all_data:
    q_master = all_data['Questions']
    categories = list(dict.fromkeys(q_master['Category'].tolist()))
    
    if not st.session_state.interview_complete:
        st.title("⛳ Tour Proven Fitting Interview")
        current_cat = categories[st.session_state.form_step]
        q_df = q_master[q_master['Category'] == current_cat]
        for _, row in q_df.iterrows():
            qid, qtext, qtype, qopts = str(row['QuestionID']).strip(), row['QuestionText'], row['InputType'], str(row['Options']).strip()
            ans_val = st.session_state.answers.get(qid, "")
            if qtype == "Dropdown":
                opts = [""]
                if "Heads" in qopts:
                    brand_val = st.session_state.answers.get("Q08", "")
                    if "Brand" in qtext: opts += sorted(all_data['Heads']['Manufacturer'].unique().tolist())
                    else: opts += sorted(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand_val]['Model'].unique().tolist()) if brand_val else ["Select Brand First"]
                elif "Shafts" in qopts:
                    s_brand, s_flex = st.session_state.answers.get("Q10", ""), st.session_state.answers.get("Q11", "")
                    if "Brand" in qtext: opts += sorted(all_data['Shafts']['Brand'].unique().tolist())
                    elif "Flex" in qtext: opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == s_brand]['Flex'].unique().tolist()) if s_brand else ["Select Brand First"]
                    elif "Model" in qtext:
                        if s_brand and s_flex: opts += sorted(all_data['Shafts'][(all_data['Shafts']['Brand'] == s_brand) & (all_data['Shafts']['Flex'] == s_flex)]['Model'].unique().tolist())
                        else: opts += ["Select Brand/Flex First"]
                elif "Config:" in qopts:
                    col = qopts.split(":")[1].strip()
                    if col in all_data['Config'].columns: opts += all_data['Config'][col].dropna().tolist()
                else: opts += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].tolist()
                opts = list(dict.fromkeys([str(x) for x in opts if x]))
                st.selectbox(qtext, opts, index=opts.index(str(ans_val)) if str(ans_val) in opts else 0, key=f"widget_{qid}", on_change=sync_all)
            elif qtype == "Numeric": st.number_input(qtext, value=float(ans_val) if ans_val else 0.0, key=f"widget_{qid}", on_change=sync_all)
            else: st.text_input(qtext, value=str(ans_val), key=f"widget_{qid}", on_change=sync_all)
        
        c1, c2, _ = st.columns([1,1,4])
        if c1.button("⬅️ Back") and st.session_state.form_step > 0: sync_all(); st.session_state.form_step -= 1; st.rerun()
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"): sync_all(); st.session_state.form_step += 1; st.rerun()
        else:
            if c2.button("🔥 Calculate"): sync_all(); save_to_fittings(st.session_state.answers); st.session_state.interview_complete = True; st.rerun()

    else:
        # --- DASHBOARD ---
        ans = st.session_state.answers
        p_name, p_email = ans.get('Q01', 'Player'), ans.get('Q02', '')
        st.title(f"⛳ Results: {p_name}")

        c_nav1, c_nav2, _ = st.columns([1,1,4])
        if c_nav1.button("✏️ Edit Fitting"): st.session_state.interview_complete = False; st.session_state.email_sent = False; st.rerun()
        if c_nav2.button("🆕 New Fitting"): st.session_state.clear(); st.rerun()
        st.divider()

        tab_report, tab_lab = st.tabs(["📄 Recommendations", "🧪 Trackman Lab"])

        # --- MATH ENGINE ---
        try: carry_6i = float(ans.get('Q15', 150))
        except: carry_6i = 150.0
        f_tf, ideal_w = (8.5, 130) if carry_6i >= 195 else (7.0, 125) if carry_6i >= 180 else (6.0, 110) if carry_6i >= 165 else (5.0, 95)
        df_all = all_data['Shafts'].copy()
        for col in ['FlexScore', 'Weight (g)', 'StabilityIndex', 'LaunchScore', 'EI_Mid']: df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)

        def get_top_3(mode):
            df_t = df_all.copy()
            df_t['Penalty'] = abs(df_t['FlexScore'] - f_tf) * 200 + abs(df_t['Weight (g)'] - ideal_w) * 15
            if carry_6i >= 180: df_t.loc[df_t['FlexScore'] < 6.5, 'Penalty'] += 4000
            if mode == "Maximum Stability": df_t['Penalty'] -= (df_t['StabilityIndex'] * 600)
            elif mode == "Launch & Height": df_t['Penalty'] -= (df_t['LaunchScore'] * 500)
            elif mode == "Feel & Smoothness": df_t['Penalty'] += (df_t['EI_Mid'] * 400)
            return df_t.sort_values('Penalty').head(3)[['Brand', 'Model', 'Flex', 'Weight (g)']]

        all_winners = {k: get_top_3(k) for k in ["Balanced", "Maximum Stability", "Launch & Height", "Feel & Smoothness"]}
        desc_map = dict(zip(all_data['Descriptions']['Model'], all_data['Descriptions']['Blurb']))
        verdicts = {f"{k}: {all_winners[k].iloc[0]['Model']}": desc_map.get(all_winners[k].iloc[0]['Model'], "Optimized.") for k in all_winners}
        
        with tab_report:
            st.markdown(f"""<div class="profile-bar"><div class="profile-grid">
                <div><b>CARRY:</b> {ans.get('Q15','')}yd | <b>FLIGHT:</b> {ans.get('Q16','')} | <b>TARGET:</b> {ans.get('Q17','')}</div>
                <div><b>HEAD:</b> {ans.get('Q08','')} {ans.get('Q09','')}</div>
                <div><b>CURRENT:</b> {ans.get('Q12','')} ({ans.get('Q11','')}) | <b>MISS:</b> {ans.get('Q18','')}</div>
                <div><b>SPECS:</b> {ans.get('Q13','')} L / {ans.get('Q14','')} SW | <b>GRIP/BALL:</b> {ans.get('Q06','')}/{ans.get('Q07','')}</div>
            </div></div>""", unsafe_allow_html=True)

            v_items = list(verdicts.items())
            col1, col2 = st.columns(2)
            for i, (cat, c_name) in enumerate([("Balanced", "⚖️ Balanced"), ("Maximum Stability", "🛡️ Stability"), ("Launch & Height", "🚀 Launch"), ("Feel & Smoothness", "☁️ Feel")]):
                with col1 if i < 2 else col2:
                    st.subheader(c_name); st.table(all_winners[cat])
                    st.markdown(f"<div class='verdict-text'><b>Verdict:</b> {v_items[i][1]}</div>", unsafe_allow_html=True)
            
            if not st.session_state.email_sent and p_email:
                with st.spinner("Dispatching PDF..."):
                    pdf_bytes = create_pdf_bytes(p_name, all_winners, ans, verdicts)
                    if send_email_with_pdf(p_email, p_name, pdf_bytes) is True: 
                        st.success(f"📬 Sent to {p_email}!"); st.session_state.email_sent = True

        with tab_lab:
            st.header("🧪 Trackman Correlation")
            c_up, c_res = st.columns([1,2])
            with c_up:
                test_list = [all_winners[k].iloc[0]['Model'] for k in all_winners]
                selected_s = st.selectbox("Assign Data to:", test_list)
                tm_file = st.file_uploader("Upload CSV/Excel", type=['csv','xlsx'])
                if st.button("➕ Add") and tm_file:
                    stat = process_trackman_file(tm_file, selected_s)
                    if stat: st.session_state.tm_lab_data.append(stat); st.rerun()
            with c_res:
                if st.session_state.tm_lab_data:
                    lab_df = pd.DataFrame(st.session_state.tm_lab_data); st.table(lab_df)
                    if len(lab_df) > 1:
                        top_shaft = lab_df.loc[lab_df['Smash Factor'].idxmax()]['Shaft ID']
                        st.success(f"🏆 **Efficiency Winner:** {top_shaft}")
                else: st.info("Upload files to correlate data.")
