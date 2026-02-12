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
                headers = [h.strip() for h in rows[0]]
                df = pd.DataFrame(rows[1:], columns=headers)
                return df
            except Exception as e:
                st.warning(f"Could not load {worksheet_name}: {e}")
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

# --- [PDF & Email Functions remain the same as previous response] ---
def create_pdf_bytes(player_name, winners, answers):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20); pdf.cell(200, 15, "PATRIOT GOLF PERFORMANCE REPORT", ln=True, align='C')
    pdf.set_font("Arial", size=11); pdf.cell(0, 10, f"Player: {player_name}", ln=True)
    for mode, row in winners.items():
        pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, f"MODE: {mode}", ln=True)
        pdf.set_font("Arial", size=11); pdf.cell(0, 8, f"{row['Brand']} {row['Model']} ({row['Flex']})", ln=True)
    return pdf.output(dest='S').encode('latin-1')

def send_email_with_pdf(recipient_email, player_name, pdf_bytes):
    try:
        sender_email = st.secrets["email"]["user"]
        sender_password = st.secrets["email"]["password"] 
        msg = MIMEMultipart()
        msg['From'] = f"Patriot Golf <{sender_email}>"; msg['To'] = recipient_email; msg['Subject'] = f"Fitting Report - {player_name}"
        msg.attach(MIMEText(f"Hi {player_name}, attached is your report.", 'plain'))
        part = MIMEApplication(pdf_bytes, Name=f"Patriot_Fitting_{player_name}.pdf")
        part['Content-Disposition'] = f'attachment; filename="Patriot_Fitting_{player_name}.pdf"'
        msg.attach(part)
        server = smtplib.SMTP('smtp.gmail.com', 587); server.starttls(); server.login(sender_email, sender_password)
        server.send_message(msg); server.quit()
        return True
    except: return False

# --- 3. STATE MANAGEMENT ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state.answers = {}

def sync_all():
    for key in st.session_state:
        if key.startswith("widget_"):
            qid = key.replace("widget_", "")
            st.session_state.answers[qid] = st.session_state[key]

all_data = get_data_from_gsheet()

# --- 4. UI LOGIC ---
if all_data:
    q_master = all_data['Questions']
    # Clean whitespace from categories to prevent matching errors
    q_master['Category'] = q_master['Category'].str.strip()
    categories = list(dict.fromkeys(q_master['Category'].tolist()))
    
    if not st.session_state.interview_complete:
        st.title("Patriot Golf Performance Fitting")
        
        current_cat = categories[st.session_state.form_step]
        q_df = q_master[q_master['Category'] == current_cat]
        st.subheader(f"Section: {current_cat}")
        
        for _, row in q_df.iterrows():
            qid = str(row['QuestionID']).strip()
            qtext, qtype = row['QuestionText'], row['InputType']
            
            # PULLING OPTIONS
            if qtype == "Dropdown":
                # Filter the Responses dataframe for the current QuestionID
                raw_opts = all_data['Responses']
                filtered_opts = raw_opts[raw_opts['QuestionID'].str.strip() == qid]['ResponseOption'].tolist()
                
                # Fallback if no options found
                if not filtered_opts:
                    opts = ["", "No options found in Sheet"]
                else:
                    opts = [""] + sorted([str(o).strip() for o in filtered_opts if o])

                current_ans = st.session_state.answers.get(qid, "")
                idx = opts.index(str(current_ans)) if str(current_ans) in opts else 0
                st.selectbox(qtext, opts, index=idx, key=f"widget_{qid}", on_change=sync_all)
            
            elif qtype == "Numeric":
                st.number_input(qtext, key=f"widget_{qid}", on_change=sync_all)
            else:
                st.text_input(qtext, key=f"widget_{qid}", on_change=sync_all)

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
        # --- RESULTS PAGE ---
        # (Same logic as before to calculate winners and send email)
        st.write("Generating results...")
        # Add a reset button just in case
        if st.button("Start Over"):
            st.session_state.clear(); st.rerun()
