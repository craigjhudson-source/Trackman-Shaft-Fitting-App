import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime
from fpdf import FPDF
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Tour Proven Shaft Fitting", layout="wide", page_icon="⛳")

st.markdown("""
    <style>
    [data-testid="stTable"] { font-size: 13px !important; }
    [data-testid="stTable"] td { padding: 4px !important; }
    .main { background-color: #f8f9fa; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA CONNECTION ---
@st.cache_data(ttl=600)
def get_data_from_gsheet():
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        
        def get_clean_df(worksheet_name):
            try:
                rows = sh.worksheet(worksheet_name).get_all_values()
                if not rows: return pd.DataFrame()
                headers = [h.strip() if h.strip() else f"Col_{i}" for i, h in enumerate(rows[0])]
                df = pd.DataFrame(rows[1:], columns=headers)
                return df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
            except: return pd.DataFrame()

        return {k: get_clean_df(k) for k in ['Heads', 'Shafts', 'Questions', 'Responses', 'Config', 'Descriptions']}
    except Exception as e:
        st.error(f"📡 Database Error: {e}"); return None

def save_to_fittings(answers):
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        worksheet = sh.worksheet('Fittings')
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp] + [answers.get(f"Q{i:02d}", "") for i in range(1, 24)]
        worksheet.append_row(row)
    except Exception as e: st.error(f"Error saving fitting: {e}")

# --- 3. PRO PDF ENGINE ---
class ProFittingPDF(FPDF):
    def header(self):
        self.set_fill_color(20, 40, 80)
        self.rect(0, 0, 210, 30, 'F')
        self.set_font('Arial', 'B', 16)
        self.set_text_color(255, 255, 255)
        self.cell(0, 15, 'TOUR PROVEN PERFORMANCE REPORT', 0, 1, 'C')
        self.set_font('Arial', '', 9); self.cell(0, -5, f"Date: {datetime.date.today().strftime('%B %d, %Y')}", 0, 1, 'C')
        self.ln(15)

    def section_title(self, label):
        self.set_font('Arial', 'B', 11); self.set_fill_color(230, 230, 230); self.set_text_color(20, 40, 80)
        self.cell(0, 8, f"  {label.upper()}", 0, 1, 'L', True); self.ln(2)

    def draw_summary_table(self, title, data_list):
        self.set_font('Arial', 'B', 10); self.set_text_color(0, 0, 0); self.cell(0, 8, title, 0, 1, 'L')
        self.set_font('Arial', '', 9)
        for item in data_list:
            self.cell(45, 6, f"{item['Detail']}:", 0, 0)
            self.cell(0, 6, str(item['Value']), 0, 1)
        self.ln(4)

    def draw_recommendation_grid(self, title, df_top3):
        self.set_font('Arial', 'B', 10); self.set_text_color(180, 0, 0); self.cell(0, 8, title, 0, 1, 'L')
        self.set_font('Arial', 'B', 8); self.set_fill_color(245, 245, 245); self.set_text_color(0, 0, 0)
        cols, w = ["Brand", "Model", "Flex", "Weight"], [40, 80, 35, 30]
        for i, col in enumerate(cols): self.cell(w[i], 7, col, 1, 0, 'C', True)
        self.ln()
        self.set_font('Arial', '', 8)
        for _, row in df_top3.iterrows():
            self.cell(w[0], 7, str(row['Brand']), 1, 0, 'C')
            self.cell(w[1], 7, str(row['Model']), 1, 0, 'C')
            self.cell(w[2], 7, str(row['Flex']), 1, 0, 'C')
            self.cell(w[3], 7, f"{row['Weight (g)']}g", 1, 0, 'C')
            self.ln()
        self.ln(6)

def create_pdf_bytes(player_name, all_winners, answers, categories, q_master, verdicts):
    pdf = ProFittingPDF()
    pdf.add_page()
    pdf.section_title("Player Profile Summary")
    for cat in categories:
        qs = q_master[q_master['Category'] == cat]
        data = [{"Detail": r['QuestionText'].replace("Current ",""), "Value": answers.get(r['QuestionID'], "")} for _, r in qs.iterrows()]
        pdf.draw_summary_table(cat, data)
    pdf.add_page()
    pdf.section_title("Recommendation Matrix (Top 3)")
    for mode, df in all_winners.items(): pdf.draw_recommendation_grid(mode, df)
    pdf.section_title("Fitter's Technical Verdict")
    pdf.set_font('Arial', '', 9)
    for title, text in verdicts.items():
        pdf.set_font('Arial', 'B', 9); pdf.cell(0, 6, title, 0, 1)
        pdf.set_font('Arial', '', 9); pdf.multi_cell(0, 5, text); pdf.ln(3)
    return pdf.output(dest='S').encode('latin-1')

def send_email_with_pdf(recipient_email, player_name, pdf_bytes):
    try:
        sender_email = st.secrets["email"]["user"]
        sender_password = str(st.secrets["email"]["password"]).replace(" ", "").strip()
        msg = MIMEMultipart()
        msg['From'] = f"Tour Proven Shaft Fitting <{sender_email}>"
        msg['To'] = recipient_email
        msg['Subject'] = f"Tour Proven Fitting Report: {player_name}"
        msg.attach(MIMEText(f"Hello {player_name},\n\nAttached is your full fitting report.", 'plain'))
        part = MIMEApplication(pdf_bytes, Name=f"Tour_Proven_{player_name}.pdf")
        part['Content-Disposition'] = f'attachment; filename="Tour_Proven_{player_name}.pdf"'
        msg.attach(part)
        server = smtplib.SMTP('smtp.gmail.com', 587); server.starttls()
        server.login(sender_email, sender_password); server.send_message(msg); server.quit()
        return True
    except Exception as e: return str(e)

# --- 4. APP FLOW ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state.answers = {}
if 'email_sent' not in st.session_state: st.session_state.email_sent = False

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
        # --- APP DASHBOARD ---
        player_name = st.session_state.answers.get('Q01', 'Player')
        player_email = st.session_state.answers.get('Q02', '')
        st.title(f"⛳ Fitting Matrix: {player_name}")
        
        c_nav1, c_nav2, _ = st.columns([1,1,4])
        if c_nav1.button("✏️ Edit"): st.session_state.interview_complete = False; st.session_state.email_sent = False; st.rerun()
        if c_nav2.button("🆕 New"): st.session_state.clear(); st.rerun()

        st.markdown("### 📊 Player Profile Summary")
        sum_cols = st.columns(len(categories))
        for i, cat in enumerate(categories):
            with sum_cols[i]:
                cat_qs = q_master[q_master['Category'] == cat]
                cat_data = [{"Detail": r['QuestionText'].replace("Current ",""), "Value": st.session_state.answers.get(r['QuestionID'], "")} for _, r in cat_qs.iterrows()]
                st.markdown(f"**{cat}**"); st.table(pd.DataFrame(cat_data))

        # --- CALCULATIONS ---
        try: carry_6i = float(st.session_state.answers.get('Q15', 150))
        except: carry_6i = 150.0
        miss = st.session_state.answers.get('Q18', 'None')
        f_tf, ideal_w = (8.5, 130) if carry_6i >= 195 else (7.0, 125) if carry_6i >= 180 else (6.0, 110) if carry_6i >= 165 else (5.0, 95) if carry_6i >= 150 else (4.0, 80)
        
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

        all_winners = {m: get_top_3(m) for m in ["Balanced", "Maximum Stability", "Launch & Height", "Feel & Smoothness"]}

        # Display Grids
        r1_c1, r1_c2 = st.columns(2); r2_c1, r2_c2 = st.columns(2); grids = [r1_c1, r1_c2, r2_c1, r2_c2]
        for i, (mode, df) in enumerate(all_winners.items()):
            with grids[i]: st.subheader(mode); st.table(df)

        # Verdicts
        desc_map = dict(zip(all_data['Descriptions']['Model'], all_data['Descriptions']['Blurb']))
        verdicts = {f"Primary: {all_winners['Balanced'].iloc[0]['Model']}": desc_map.get(all_winners['Balanced'].iloc[0]['Model'], "Optimized profile."),
                    f"Anti-{miss}: {all_winners['Maximum Stability'].iloc[0]['Model']}": desc_map.get(all_winners['Maximum Stability'].iloc[0]['Model'], "High stability.")}
        
        st.divider(); st.subheader("🔬 Fitter's Technical Verdict")
        v_c1, v_c2 = st.columns(2); v_cols = [v_c1, v_c2]
        for i, (t, txt) in enumerate(verdicts.items()):
            with v_cols[i]: st.info(f"**{t}**\n\n{txt}")

        # Email
        if not st.session_state.email_sent and player_email:
            with st.spinner("Dispatching Pro Report..."):
                pdf_bytes = create_pdf_bytes(player_name, all_winners, st.session_state.answers, categories, q_master, verdicts)
                if send_email_with_pdf(player_email, player_name, pdf_bytes) is True:
                    st.success(f"📬 Report sent to {player_email}"); st.session_state.email_sent = True
