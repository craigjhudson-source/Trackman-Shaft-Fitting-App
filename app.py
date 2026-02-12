import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime
from fpdf import FPDF
import smtplib
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# --- 1. CONFIGURATION & STYLES ---
st.set_page_config(page_title="Tour Proven Shaft Fitting", layout="wide", page_icon="⛳")

st.markdown("""
    <style>
    [data-testid="stTable"] { font-size: 12px !important; }
    .main { background-color: #f8f9fa; }
    .profile-bar { 
        background-color: #142850; 
        color: white; 
        padding: 20px; 
        border-radius: 10px; 
        margin-bottom: 25px;
        font-family: sans-serif;
    }
    .profile-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 15px;
    }
    .verdict-text {
        font-style: italic;
        color: #444;
        margin-bottom: 25px;
        font-size: 13px;
        border-left: 3px solid #b40000;
        padding-left: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. SECURITY & DATABASE ---
def get_google_creds(scopes):
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        if "private_key" in creds_dict:
            pk = creds_dict["private_key"].replace("\\n", "\n")
            if "-----BEGIN PRIVATE KEY-----" in pk:
                pk = pk[pk.find("-----BEGIN PRIVATE KEY-----"):]
            creds_dict["private_key"] = pk.strip()
        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    except Exception as e:
        st.error(f"🔐 Security Error: {e}")
        st.stop()

@st.cache_data(ttl=600)
def get_data_from_gsheet():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = get_google_creds(scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        
        def get_clean_df(worksheet_name):
            try:
                rows = sh.worksheet(worksheet_name).get_all_values()
                if not rows: return pd.DataFrame()
                df = pd.DataFrame(rows[1:], columns=[h.strip() if h.strip() else f"Col_{i}" for i, h in enumerate(rows[0])])
                return df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
            except: return pd.DataFrame()

        return {k: get_clean_df(k) for k in ['Heads', 'Shafts', 'Questions', 'Responses', 'Config', 'Descriptions']}
    except Exception as e:
        st.error(f"📡 Database Error: {e}")
        return None

def save_to_fittings(answers):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = get_google_creds(scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        worksheet = sh.worksheet('Fittings')
        row = [datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")] + [answers.get(f"Q{i:02d}", "") for i in range(1, 22)]
        worksheet.append_row(row)
    except Exception as e: st.error(f"Error saving fitting: {e}")

# --- 3. PRO PDF ENGINE ---
def clean_text(text):
    return re.sub(r'[^\x00-\x7F]+', '', str(text)) if text else ""

class ProFittingPDF(FPDF):
    def header(self):
        self.set_fill_color(20, 40, 80); self.rect(0, 0, 210, 25, 'F')
        self.set_font('helvetica', 'B', 14); self.set_text_color(255, 255, 255)
        self.cell(0, 10, 'TOUR PROVEN PERFORMANCE REPORT', 0, 1, 'C')
        self.set_font('helvetica', '', 8); self.cell(0, -2, f"Date: {datetime.date.today().strftime('%B %d, %Y')}", 0, 1, 'C')
        self.ln(12)

    def draw_player_header(self, answers):
        self.set_font('helvetica', 'B', 9); self.set_text_color(20, 40, 80)
        self.cell(0, 6, f"PLAYER: {clean_text(answers.get('Q01','')).upper()}", 0, 1, 'L')
        self.set_font('helvetica', '', 8); self.set_text_color(0, 0, 0)
        line1 = f"6i Carry: {answers.get('Q15','')}yd | Flight: {answers.get('Q16','')} | Target: {answers.get('Q17','')} | Miss: {answers.get('Q18','')}"
        line2 = f"Current Head: {answers.get('Q08','')} {answers.get('Q09','')} | Current Shaft: {answers.get('Q12','')} ({answers.get('Q11','')})"
        line3 = f"Length: {answers.get('Q13','')} | Swing Weight: {answers.get('Q14','')} | Grip: {answers.get('Q06','')} | Ball: {answers.get('Q07','')}"
        self.cell(0, 4, clean_text(line1), 0, 1, 'L')
        self.cell(0, 4, clean_text(line2), 0, 1, 'L')
        self.cell(0, 4, clean_text(line3), 0, 1, 'L')
        self.ln(2); self.line(10, self.get_y(), 200, self.get_y()); self.ln(4)

    def draw_recommendation_block(self, title, df, verdict_text):
        self.set_font('helvetica', 'B', 10); self.set_text_color(180, 0, 0); self.cell(0, 6, clean_text(title.upper()), 0, 1, 'L')
        self.set_font('helvetica', 'B', 8); self.set_fill_color(240, 240, 240); self.set_text_color(0, 0, 0)
        cols, w = ["Brand", "Model", "Flex", "Weight"], [40, 85, 30, 30]
        for i, col in enumerate(cols): self.cell(w[i], 6, col, 1, 0, 'C', True)
        self.ln(); self.set_font('helvetica', '', 8)
        for _, row in df.iterrows():
            for i, c in enumerate(['Brand', 'Model', 'Flex', 'Weight (g)']): self.cell(w[i], 5, clean_text(row[c]), 1, 0, 'C')
            self.ln()
        self.set_font('helvetica', 'B', 8); self.cell(0, 4, "Fitter's Technical Verdict:", 0, 1)
        self.set_font('helvetica', 'I', 8); self.multi_cell(0, 4, clean_text(verdict_text)); self.ln(4)

def create_pdf_bytes(player_name, all_winners, answers, verdicts):
    pdf = ProFittingPDF(); pdf.add_page(); pdf.draw_player_header(answers)
    mapping = {"Balanced Choice": "Balanced", "Maximum Stability (Anti-Hook)": "Maximum Stability", "Launch & Height Optimizer": "Launch & Height", "Feel & Smoothness": "Feel & Smoothness"}
    v_keys = list(verdicts.keys())
    for i, (label, calc_key) in enumerate(mapping.items()):
        pdf.draw_recommendation_block(label, all_winners[calc_key], verdicts[v_keys[i]])
    return bytes(pdf.output())

def send_email_with_pdf(recipient_email, player_name, pdf_bytes):
    try:
        user, pwd = st.secrets["email"]["user"], st.secrets["email"]["password"].replace(" ", "").strip()
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = f"Tour Proven <{user}>", recipient_email, f"Fitting Report: {player_name}"
        msg.attach(MIMEText(f"Hello {player_name},\n\nAttached is your one-page Performance Report.", 'plain'))
        part = MIMEApplication(pdf_bytes, Name=f"Report_{player_name}.pdf")
        part['Content-Disposition'] = f'attachment; filename="Report_{player_name}.pdf"'; msg.attach(part)
        server = smtplib.SMTP('smtp.gmail.com', 587); server.starttls(); server.login(user, pwd); server.send_message(msg); server.quit()
        return True
    except Exception as e: return str(e)

# --- 4. TRACKMAN LAB ENGINE ---
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

# --- 5. APP FLOW & SESSION ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state.answers = {}
if 'email_sent' not in st.session_state: st.session_state.email_sent = False
if 'tm_lab_data' not in st.session_state: st.session_state.tm_lab_data = []

def sync_all():
    for key in st.session_state:
        if key.startswith("widget_"): st.session_state.answers[key.replace("widget_", "")] = st.session_state[key]

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
        # --- RESULTS DASHBOARD ---
        ans = st.session_state.answers
        player_name, player_email = ans.get('Q01', 'Player'), ans.get('Q02', '')
        st.title(f"⛳ Performance Matrix: {player_name}")

        # --- RESTORED NAVIGATION BUTTONS ---
        c_nav1, c_nav2, _ = st.columns([1,1,4])
        if c_nav1.button("✏️ Edit Fitting"): 
            st.session_state.interview_complete = False
            st.session_state.email_sent = False
            st.rerun()
        if c_nav2.button("🆕 New Fitting"): 
            st.session_state.clear()
            st.rerun()
        st.divider()

        tab_report, tab_lab = st.tabs(["📄 Recommendations", "🧪 Trackman Lab"])

        # --- PREDICTION LOGIC ---
        try: carry_6i = float(ans.get('Q15', 150))
        except: carry_6i = 150.0
        miss = ans.get('Q18', 'None')
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
            # PROFILE BAR
            st.markdown(f"""
            <div class="profile-bar">
                <div class="profile-grid">
                    <div>
                        <b>CARRY:</b> {ans.get('Q15','')}yd &nbsp;|&nbsp; 
                        <b>FLIGHT:</b> {ans.get('Q16','')} &nbsp;|&nbsp; 
                        <b>TARGET:</b> {ans.get('Q17','')}
                    </div>
                    <div>
                        <b>CURRENT HEAD:</b> {ans.get('Q08','')} {ans.get('Q09','')}
                    </div>
                    <div>
                        <b>CURRENT SHAFT:</b> {ans.get('Q12','')} ({ans.get('Q11','')}) &nbsp;|&nbsp; 
                        <b>MISS:</b> {ans.get('Q18','')}
                    </div>
                    <div>
                        <b>SPECS:</b> {ans.get('Q13','')} L / {ans.get('Q14','')} SW &nbsp;|&nbsp; 
                        <b>GRIP:</b> {ans.get('Q06','')} &nbsp;|&nbsp; 
                        <b>BALL:</b> {ans.get('Q07','')}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            v_items = list(verdicts.items())
            col1, col2 = st.columns(2)
            for i, (cat, c_name) in enumerate([("Balanced", "⚖️ Balanced Choice"), ("Maximum Stability", "🛡️ Maximum Stability"), ("Launch & Height", "🚀 Launch & Height"), ("Feel & Smoothness", "☁️ Feel & Smoothness")]):
                with col1 if i < 2 else col2:
                    st.subheader(c_name)
                    st.table(all_winners[cat])
                    st.markdown(f"<div class='verdict-text'><b>Fitter's Verdict:</b> {v_items[i][1]}</div>", unsafe_allow_html=True)
            
            if not st.session_state.email_sent and player_email:
                with st.spinner("Emailing Performance Report..."):
                    pdf_bytes = create_pdf_bytes(player_name, all_winners, ans, verdicts)
                    if send_email_with_pdf(player_email, player_name, pdf_bytes) is True: 
                        st.success(f"📬 Report emailed to {player_email}!")
                        st.session_state.email_sent = True

        with tab_lab:
            st.header("🧪 Trackman Correlation Lab")
            st.write("Upload Trackman data to compare live session numbers against predictions.")
            c_up, c_res = st.columns([1,2])
            with c_up:
                test_list = [all_winners[k].iloc[0]['Model'] for k in all_winners]
                selected_s = st.selectbox("Assign Data to Shaft:", test_list)
                tm_file = st.file_uploader("Upload Trackman CSV/Excel", type=['csv','xlsx'])
                if st.button("➕ Add to Session") and tm_file:
                    stat = process_trackman_file(tm_file, selected_s)
                    if stat: st.session_state.tm_lab_data.append(stat); st.rerun()
            
            with c_res:
                if st.session_state.tm_lab_data:
                    lab_df = pd.DataFrame(st.session_state.tm_lab_data)
                    st.table(lab_df)
                    if len(lab_df) > 1:
                        top_shaft = lab_df.loc[lab_df['Smash Factor'].idxmax()]['Shaft ID']
                        st.success(f"🏆 **Winner (Efficiency):** {top_shaft}")
                        avg_spin = lab_df['Spin Rate'].mean()
                        if avg_spin > 3200: st.warning("💡 **Tip:** Spin is high. Consider lower loft or different ball.")
                else: st.info("Upload files to start live comparison.")
