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

# --- 1. SETTINGS & DATA ---
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
        
        def get_clean_df(ws_name):
            try:
                rows = sh.worksheet(ws_name).get_all_values()
                if not rows: return pd.DataFrame()
                df = pd.DataFrame(rows[1:], columns=[h.strip() for h in rows[0]])
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
        st.error(f"📡 Connection Error: {e}"); return None

# --- 2. EMAIL & PDF LOGIC ---
def create_pdf_bytes(player_name, winners, answers):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20); pdf.set_text_color(20, 40, 100)
    pdf.cell(200, 15, "PATRIOT GOLF PERFORMANCE REPORT", ln=True, align='C')
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12); pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 10, f"Player: {player_name}", ln=True)
    pdf.set_font("Arial", size=11)
    pdf.cell(0, 7, f"6i Carry: {answers.get('Q15', '—')}yd | Miss: {answers.get('Q18', '—')}", ln=True)
    pdf.ln(10)
    for mode, row in winners.items():
        pdf.set_font("Arial", 'B', 12); pdf.set_text_color(180, 0, 0)
        pdf.cell(0, 10, f"MODE: {mode.upper()}", ln=True)
        pdf.set_font("Arial", size=11); pdf.set_text_color(0, 0, 0)
        pdf.cell(10, 8, ""); pdf.cell(0, 8, f"{row['Brand']} {row['Model']} (Flex: {row['Flex']} | {row['Weight (g)']}g)", ln=True)
        pdf.ln(2)
    return pdf.output(dest='S').encode('latin-1')

def send_email_with_pdf(recipient_email, player_name, pdf_bytes):
    try:
        sender_email = st.secrets["email"]["user"]
        sender_password = st.secrets["email"]["password"] 
        msg = MIMEMultipart()
        msg['From'] = f"Patriot Golf <{sender_email}>"; msg['To'] = recipient_email
        msg['Subject'] = f"Your Custom Shaft Prescription - {player_name}"
        msg.attach(MIMEText(f"Hello {player_name},\n\nPlease find your shaft report attached.\n\nBest,\nPatriot Golf", 'plain'))
        part = MIMEApplication(pdf_bytes, Name=f"Patriot_Fitting_{player_name}.pdf")
        part['Content-Disposition'] = f'attachment; filename="Patriot_Fitting_{player_name}.pdf"'
        msg.attach(part)
        server = smtplib.SMTP('smtp.gmail.com', 587); server.starttls()
        server.login(sender_email, sender_password); server.send_message(msg); server.quit()
        return True
    except: return False

# --- 3. CORE LOGIC ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state.answers = {}

def sync_all():
    for key in st.session_state:
        if key.startswith("widget_"):
            st.session_state.answers[key.replace("widget_", "")] = st.session_state[key]

all_data = get_data_from_gsheet()

if all_data:
    q_master = all_data['Questions']
    categories = list(dict.fromkeys(q_master['Category'].tolist()))
    
    if not st.session_state.interview_complete:
        st.title("Patriot Golf Fitting Engine")
        current_cat = categories[st.session_state.form_step]
        q_df = q_master[q_master['Category'] == current_cat]
        st.subheader(f"Section: {current_cat}")

        for _, row in q_df.iterrows():
            qid, qtext, qtype, qopts = row['QuestionID'], row['QuestionText'], row['InputType'], row['Options']
            
            if qtype == "Dropdown":
                opts = [""]
                # 1. Check Config Tab
                if qopts.startswith("Config:"):
                    col_name = qopts.split(":")[1]
                    if col_name in all_data['Config'].columns:
                        opts += sorted([o for o in all_data['Config'][col_name].unique() if o])
                # 2. Check Heads Tab
                elif "Heads Tab" in qopts:
                    if qid == "Q08": opts += sorted(all_data['Heads']['Manufacturer'].unique().tolist())
                    if qid == "Q09": 
                        brand = st.session_state.answers.get("Q08", "")
                        opts += sorted(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand]['Model'].unique().tolist())
                # 3. Check Shafts Tab
                elif "Shafts Tab" in qopts:
                    if qid == "Q10": opts += sorted(all_data['Shafts']['Brand'].unique().tolist())
                    if qid == "Q11": opts += sorted(all_data['Shafts']['Flex'].unique().tolist())
                    if qid == "Q12": 
                        brand = st.session_state.answers.get("Q10", "")
                        flex = st.session_state.answers.get("Q11", "")
                        mask = (all_data['Shafts']['Brand'] == brand) & (all_data['Shafts']['Flex'] == flex)
                        opts += sorted(all_data['Shafts'][mask]['Model'].unique().tolist())
                # 4. Fallback to Responses Tab
                else:
                    res_opts = all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].tolist()
                    opts += sorted(res_opts)

                ans = st.session_state.answers.get(qid, "")
                idx = opts.index(ans) if ans in opts else 0
                st.selectbox(qtext, opts, index=idx, key=f"widget_{qid}", on_change=sync_all)

            else:
                st.text_input(qtext, value=st.session_state.answers.get(qid, ""), key=f"widget_{qid}", on_change=sync_all)

        st.divider()
        c1, c2, _ = st.columns([1,1,4])
        if c1.button("⬅️ Back") and st.session_state.form_step > 0:
            st.session_state.form_step -= 1; st.rerun()
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"):
                st.session_state.form_step += 1; st.rerun()
        else:
            if c2.button("🔥 Generate Prescription"):
                sync_all(); st.session_state.interview_complete = True; st.rerun()

    else:
        # --- 4. RESULTS ---
        player_name = st.session_state.answers.get('Q01', 'Player')
        player_email = st.session_state.answers.get('Q02', '')
        st.title(f"🎯 Fitting Matrix: {player_name}")

        # Basic Ranking Math
        carry = float(st.session_state.answers.get('Q15', 150))
        f_target = 8.5 if carry >= 195 else (7.0 if carry >= 180 else 6.0)
        w_target = 130 if carry >= 195 else (115 if carry >= 170 else 105)

        df_s = all_data['Shafts'].copy()
        for c in ['FlexScore', 'Weight (g)', 'StabilityIndex']:
            df_s[c] = pd.to_numeric(df_s[c], errors='coerce').fillna(0)

        def get_top(mode):
            df = df_s.copy()
            df['Penalty'] = abs(df['FlexScore'] - f_target)*200 + abs(df['Weight (g)'] - w_target)*10
            if mode == "Maximum Stability": df['Penalty'] -= (df['StabilityIndex'] * 500)
            return df.sort_values('Penalty').head(3)

        modes = ["Balanced", "Maximum Stability", "Launch & Height", "Feel & Smoothness"]
        winners = {}
        cols = st.columns(2); cols2 = st.columns(2); all_cols = cols + cols2
        for i, m in enumerate(modes):
            with all_cols[i]:
                top = get_top(m)
                winners[m] = top.iloc[0]
                st.subheader(f"🚀 {m}"); st.table(top[['Brand', 'Model', 'Flex', 'Weight (g)']])

        if 'sent' not in st.session_state and player_email:
            pdf = create_pdf_bytes(player_name, winners, st.session_state.answers)
            if send_email_with_pdf(player_email, player_name, pdf):
                st.success(f"📬 Report sent to {player_email}")
                st.session_state.sent = True

        if st.button("🆕 Reset"):
            st.session_state.clear(); st.rerun()
