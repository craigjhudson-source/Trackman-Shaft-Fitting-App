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

# --- 1. CONFIGURATION & STYLING ---
st.set_page_config(page_title="Tour Proven Shaft Fitting", layout="wide", page_icon="⛳")

st.markdown("""
    <style>
    [data-testid="stTable"] { font-size: 13px !important; }
    [data-testid="stTable"] td { padding: 4px !important; }
    .stAlert p { font-size: 14px; }
    .main { background-color: #f8f9fa; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA CONNECTION ---
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
                return df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
            except: return pd.DataFrame()

        return {
            'Heads': get_clean_df('Heads'),
            'Shafts': get_clean_df('Shafts'),
            'Questions': get_clean_df('Questions'),
            'Responses': get_clean_df('Responses'),
            'Config': get_clean_df('Config'),
            'Descriptions': get_clean_df('Descriptions')
        }
    except Exception as e:
        st.error(f"📡 Database Connection Error: {e}"); return None

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
    except Exception as e:
        st.error(f"Error saving fitting record: {e}")

# --- 3. ADVANCED PDF ENGINE ---
class FittingPDF(FPDF):
    def header(self):
        self.set_fill_color(20, 40, 80)
        self.rect(0, 0, 210, 35, 'F')
        self.set_font('Arial', 'B', 18)
        self.set_text_color(255, 255, 255)
        self.cell(0, 20, 'TOUR PROVEN SHAFT PRESCRIPTION', 0, 1, 'C')
        self.set_font('Arial', '', 10)
        self.cell(0, -5, f"Generated: {datetime.date.today().strftime('%B %d, %Y')}", 0, 1, 'C')
        self.ln(15)

    def section_header(self, label, icon_color=(200, 0, 0)):
        self.set_font('Arial', 'B', 12)
        self.set_text_color(*icon_color)
        self.cell(0, 10, f"  {label.upper()}", 0, 1, 'L')
        self.set_draw_color(*icon_color)
        self.line(self.get_x(), self.get_y()-2, self.get_x()+190, self.get_y()-2)
        self.ln(2)

    def recommendation_table(self, df_row):
        self.set_font('Arial', 'B', 10)
        self.set_fill_color(240, 240, 240)
        self.set_text_color(0, 0, 0)
        # Table Headers
        cols = ["Brand", "Model", "Flex", "Weight"]
        widths = [45, 80, 35, 30]
        for i, col in enumerate(cols):
            self.cell(widths[i], 8, col, 1, 0, 'C', True)
        self.ln()
        # Table Data
        self.set_font('Arial', '', 10)
        self.cell(widths[0], 8, str(df_row['Brand']), 1, 0, 'C')
        self.cell(widths[1], 8, str(df_row['Model']), 1, 0, 'C')
        self.cell(widths[2], 8, str(df_row['Flex']), 1, 0, 'C')
        self.cell(widths[3], 8, f"{df_row['Weight (g)']}g", 1, 0, 'C')
        self.ln(12)

def create_pdf_bytes(player_name, winners, answers):
    pdf = FittingPDF()
    pdf.add_page()
    
    # Player Summary Box
    pdf.set_font('Arial', 'B', 11)
    pdf.set_fill_color(245, 245, 245)
    pdf.cell(0, 10, f" PLAYER: {player_name.upper()}", 1, 1, 'L', True)
    pdf.set_font('Arial', '', 10)
    stats = f"6i Carry: {answers.get('Q15','—')}yd  |  Flight: {answers.get('Q17','—')}  |  Miss: {answers.get('Q18','—')}"
    pdf.cell(0, 8, f" {stats}", 1, 1, 'L')
    pdf.ln(10)

    # Recommendations
    pdf.section_header("Balanced Choice", (40, 40, 40))
    pdf.recommendation_table(winners['Balanced'])

    pdf.section_header("Maximum Stability (Anti-Hook)", (0, 100, 200))
    pdf.recommendation_table(winners['Maximum Stability'])

    pdf.section_header("Launch & Height Optimizer", (200, 80, 0))
    pdf.recommendation_table(winners['Launch & Height'])

    pdf.section_header("Feel & Smoothness", (0, 150, 0))
    pdf.recommendation_table(winners['Feel & Smoothness'])

    return pdf.output(dest='S').encode('latin-1')

def send_email_with_pdf(recipient_email, player_name, pdf_bytes):
    try:
        sender_email = st.secrets["email"]["user"]
        sender_password = str(st.secrets["email"]["password"]).replace(" ", "").strip()
        msg = MIMEMultipart()
        msg['From'] = f"Tour Proven Shaft Fitting <{sender_email}>"
        msg['To'] = recipient_email
        msg['Subject'] = f"Tour Proven Fitting Report: {player_name}"
        body = f"Hello {player_name},\n\nAttached is your custom shaft fitting report from Tour Proven Shaft Fitting.\n\nBest,\nTour Proven Team"
        msg.attach(MIMEText(body, 'plain'))
        part = MIMEApplication(pdf_bytes, Name=f"Tour_Proven_Fitting_{player_name}.pdf")
        part['Content-Disposition'] = f'attachment; filename="Tour_Proven_Fitting_{player_name}.pdf"'
        msg.attach(part)
        server = smtplib.SMTP('smtp.gmail.com', 587); server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg); server.quit()
        return True
    except Exception as e: return str(e)

# --- 4. STATE MANAGEMENT ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state.answers = {}
if 'email_sent' not in st.session_state: st.session_state.email_sent = False

def sync_all():
    for key in st.session_state:
        if key.startswith("widget_"): st.session_state.answers[key.replace("widget_", "")] = st.session_state[key]

all_data = get_data_from_gsheet()

# --- 5. UI FLOW ---
if all_data:
    q_master = all_data['Questions']
    categories = list(dict.fromkeys(q_master['Category'].tolist()))
    
    if not st.session_state.interview_complete:
        st.title("⛳ Tour Proven Fitting Interview")
        st.progress((st.session_state.form_step + 1) / len(categories))
        current_cat = categories[st.session_state.form_step]
        q_df = q_master[q_master['Category'] == current_cat]
        st.subheader(f"Section: {current_cat}")
        
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
            
        st.divider()
        c1, c2, _ = st.columns([1,1,4])
        if c1.button("⬅️ Back") and st.session_state.form_step > 0: sync_all(); st.session_state.form_step -= 1; st.rerun()
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"): sync_all(); st.session_state.form_step += 1; st.rerun()
        else:
            if c2.button("🔥 Calculate Fitting"): sync_all(); save_to_fittings(st.session_state.answers); st.session_state.interview_complete = True; st.rerun()

    else:
        # --- RESULTS PAGE ---
        player_name = st.session_state.answers.get('Q01', 'Player')
        player_email = st.session_state.answers.get('Q02', '')
        st.title(f"⛳ Fitting Matrix: {player_name}")
        
        nb1, nb2, _ = st.columns([1.2, 1.5, 4])
        if nb1.button("✏️ Edit Profile"):
            st.session_state.interview_complete = False; st.session_state.email_sent = False; st.rerun()
        if nb2.button("🆕 Start New Fitting"):
            st.session_state.clear(); st.rerun()

        st.divider()

        # Summary Grid
        st.markdown("### 📊 Player Profile Summary")
        summary_cols = st.columns(len(categories))
        for i, cat in enumerate(categories):
            with summary_cols[i]:
                cat_qs = q_master[q_master['Category'] == cat]
                cat_data = [{"Detail": r['QuestionText'].replace("Current ", "").replace("Target ", ""), "Value": st.session_state.answers.get(r['QuestionID'], "")} for _, r in cat_qs.iterrows()]
                if cat_data:
                    st.markdown(f"**{cat}**")
                    st.table(pd.DataFrame(cat_data))

        # Calculation Logic
        try: carry_6i = float(st.session_state.answers.get('Q15', 150))
        except: carry_6i = 150.0
        primary_miss = st.session_state.answers.get('Q18', 'None')
        if carry_6i >= 195: f_tf, ideal_w = 8.5, 130
        elif carry_6i >= 180: f_tf, ideal_w = 7.0, 125
        elif carry_6i >= 165: f_tf, ideal_w = 6.0, 110
        elif carry_6i >= 150: f_tf, ideal_w = 5.0, 95
        else: f_tf, ideal_w = 4.0, 80

        df_all = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'Weight (g)', 'StabilityIndex', 'EI_Mid']:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)

        def get_top_3(df_in, mode):
            df_temp = df_in.copy()
            df_temp['Penalty'] = abs(df_temp['FlexScore'] - f_tf) * 200
            if carry_6i >= 180: df_temp.loc[df_temp['FlexScore'] < 6.5, 'Penalty'] += 4000
            df_temp['Penalty'] += abs(df_temp['Weight (g)'] - ideal_w) * 15
            if mode == "Maximum Stability": df_temp['Penalty'] -= (df_temp['StabilityIndex'] * 600)
            elif mode == "Launch & Height": df_temp['Penalty'] -= (df_temp['LaunchScore'] * 500)
            elif mode == "Feel & Smoothness": df_temp['Penalty'] += (df_temp['EI_Mid'] * 400)
            return df_temp.sort_values('Penalty').head(3)[['ID', 'Brand', 'Model', 'Flex', 'Weight (g)']]

        # Display Grid
        modes = [("Balanced", "⚖️"), ("Maximum Stability", "🛡️"), ("Launch & Height", "🚀"), ("Feel & Smoothness", "☁️")]
        winners = {}
        r1 = st.columns(2); r2 = st.columns(2); all_grid = r1 + r2
        for i, (mode, icon) in enumerate(modes):
            with all_grid[i]:
                st.subheader(f"{icon} {mode}")
                res = get_top_3(df_all, mode); winners[mode] = res.iloc[0]; st.table(res)

        # Email Trigger
        if not st.session_state.email_sent and player_email:
            with st.spinner("Dispatching Redesigned PDF..."):
                pdf_bytes = create_pdf_bytes(player_name, winners, st.session_state.answers)
                result = send_email_with_pdf(player_email, player_name, pdf_bytes)
                if result is True: st.success(f"📬 Professional Report sent to {player_email}"); st.session_state.email_sent = True
                else: st.error(f"⚠️ Email Delivery Failed: {result}")

        # Final Verdicts
        st.divider()
        st.subheader("🔬 Fitter's Technical Verdict")
        desc_lookup = dict(zip(all_data['Descriptions']['Model'], all_data['Descriptions']['Blurb'])) if not all_data['Descriptions'].empty else {}
        v1, v2 = st.columns(2)
        with v1:
            st.info(f"**Primary: {winners['Balanced']['Model']}**\n\n{desc_lookup.get(winners['Balanced']['Model'], 'Optimized trajectory and weight.')}")
            st.error(f"**Anti-{primary_miss} Logic: {winners['Maximum Stability']['Model']}**\n\n{desc_lookup.get(winners['Maximum Stability']['Model'], 'Reinforced for maximum face control.')}")
        with v2:
            st.success(f"**Flight/Height: {winners['Launch & Height']['Model']}**\n\n{desc_lookup.get(winners['Launch & Height']['Model'], 'Designed to optimize peak apex.')}")
            st.warning(f"**Feel/Smoothness: {winners['Feel & Smoothness']['Model']}**\n\n{desc_lookup.get(winners['Feel & Smoothness']['Model'], 'Enhanced vibration dampening and feedback.')}")
