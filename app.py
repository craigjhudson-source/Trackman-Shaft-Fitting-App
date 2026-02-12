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

# --- PDF & EMAIL LOGIC ---
def create_pdf_bytes(player_name, winners, answers):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(200, 15, "PATRIOT GOLF PERFORMANCE REPORT", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 10, f"Date: {datetime.datetime.now().strftime('%Y-%m-%d')}", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"Player: {player_name}", ln=True)
    pdf.set_font("Arial", size=11)
    pdf.cell(0, 10, f"6i Carry: {answers.get('Q15', '—')}yd | Miss: {answers.get('Q18', '—')}", ln=True)
    pdf.ln(5)

    for mode, row in winners.items():
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, f"Selection: {mode}", ln=True)
        pdf.set_font("Arial", size=11)
        pdf.cell(0, 8, f"{row['Brand']} {row['Model']} (Flex: {row['Flex']})", ln=True)
        pdf.ln(2)
    
    return pdf.output(dest='S').encode('latin-1')

def send_email_with_pdf(recipient_email, player_name, pdf_bytes):
    try:
        sender_email = st.secrets["email"]["user"]
        sender_password = st.secrets["email"]["password"] 
        msg = MIMEMultipart()
        msg['From'] = f"Patriot Golf Fitting <{sender_email}>"
        msg['To'] = recipient_email
        msg['Subject'] = f"Your Custom Shaft Prescription - {player_name}"
        
        body = f"Hello {player_name},\n\nPlease find your personalized shaft recommendation attached. Let us know if you have any questions!\n\nBest,\nPatriot Golf Team"
        msg.attach(MIMEText(body, 'plain'))
        
        part = MIMEApplication(pdf_bytes, Name=f"Patriot_Fitting_{player_name}.pdf")
        part['Content-Disposition'] = f'attachment; filename="Patriot_Fitting_{player_name}.pdf"'
        msg.attach(part)
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Email Error: {e}"); return False

# --- 2. STATE MANAGEMENT ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state.answers = {}

all_data = get_data_from_gsheet()

# --- 3. UI LOGIC ---
if all_data:
    q_master = all_data['Questions']
    categories = list(dict.fromkeys(q_master['Category'].tolist()))
    
    if not st.session_state.interview_complete:
        st.title("Patriot Golf Performance Fitting")
        current_cat = categories[st.session_state.form_step]
        q_df = q_master[q_master['Category'] == current_cat]
        st.subheader(f"Section: {current_cat}")
        
        for _, row in q_df.iterrows():
            qid = str(row['QuestionID']).strip()
            qtext, qtype = row['QuestionText'], row['InputType']
            ans_val = st.session_state.answers.get(qid, "")
            
            # Simple input handling
            if qtype == "Dropdown":
                opts = [""] + all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].tolist()
                st.selectbox(qtext, opts, key=f"widget_{qid}")
            elif qtype == "Numeric":
                st.number_input(qtext, key=f"widget_{qid}")
            else:
                st.text_input(qtext, key=f"widget_{qid}")

        if st.button("🔥 Generate Prescription"):
            # Sync answers to state
            for key in st.session_state:
                if key.startswith("widget_"):
                    st.session_state.answers[key.replace("widget_", "")] = st.session_state[key]
            st.session_state.interview_complete = True
            st.rerun()

    else:
        # --- 4. RESULTS PAGE ---
        player_name = st.session_state.answers.get('Q01', 'Player')
        player_email = st.session_state.answers.get('Q02', '')
        
        hdr1, hdr2 = st.columns([5, 1])
        with hdr1: st.title(f"🎯 Master Fitting Matrix: {player_name}")
        with hdr2: 
            if st.button("✏️ Edit Answers"):
                st.session_state.interview_complete = False
                st.rerun()

        # [Logic Prep for Shaft Ranking - same as previous]
        carry_6i = float(st.session_state.answers.get('Q15', 150))
        current_shaft = st.session_state.answers.get('Q12', '')
        
        if carry_6i >= 195: f_tf, ideal_w = 8.5, 130
        elif carry_6i >= 180: f_tf, ideal_w = 7.0, 125
        else: f_tf, ideal_w = 6.0, 110

        df_all = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'Weight (g)', 'StabilityIndex', 'EI_Mid']:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)

        def get_top_3(df_in, mode):
            df_temp = df_in.copy()
            df_temp['Penalty'] = abs(df_temp['FlexScore'] - f_tf) * 200 + abs(df_temp['Weight (g)'] - ideal_w) * 15
            if mode == "Maximum Stability": df_temp['Penalty'] -= (df_temp['StabilityIndex'] * 600)
            res = df_temp.sort_values('Penalty').head(3)[['Brand', 'Model', 'Flex', 'Weight (g)', 'Launch']]
            res['Status'] = res['Model'].apply(lambda x: "✅ CURRENT" if x == current_shaft else "🆕 NEW")
            return res

        modes = ["Balanced", "Maximum Stability", "Launch & Height", "Feel & Smoothness"]
        winners = {}
        cols = st.columns(2); cols2 = st.columns(2); all_cols = cols + cols2
        for i, m in enumerate(modes):
            with all_cols[i]:
                top_df = get_top_3(df_all, m)
                winners[m] = top_df.iloc[0]
                st.subheader(f"🚀 {m}")
                st.table(top_df)

        # --- AUTO EMAIL TRIGGER ---
        if 'email_sent' not in st.session_state and player_email:
            with st.spinner("Generating PDF and emailing player..."):
                pdf_bytes = create_pdf_bytes(player_name, winners, st.session_state.answers)
                if send_email_with_pdf(player_email, player_name, pdf_bytes):
                    st.success(f"📬 Report emailed to {player_email}")
                    st.session_state.email_sent = True

        st.divider()
        st.subheader("🏁 Summary Recommendation")
        st.info(f"Test the **{winners['Balanced']['Model']}** first. It provides the best weight-to-flex ratio for your {carry_6i}yd carry.")
