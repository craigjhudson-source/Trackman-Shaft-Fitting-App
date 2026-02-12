import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime
from fpdf import FPDF
import smtplib
import re
import io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- 0. SECRETS FIXER ---
def get_google_creds(scopes):
    """Ensures secrets are in a proper dictionary format for Google Libraries."""
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        # Standardize the private key for Python 3.13
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    except Exception as e:
        st.error(f"Secret Parsing Error: {e}")
        st.stop()

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Tour Proven Shaft Fitting", layout="wide", page_icon="⛳")

# Folder ID where PDFs will be stored (Ensure this matches your Google Drive folder)
DRIVE_FOLDER_ID = "1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY" 

st.markdown("""
    <style>
    [data-testid="stTable"] { font-size: 12px !important; }
    [data-testid="stTable"] td { padding: 2px !important; }
    .main { background-color: #f8f9fa; }
    .profile-bar { 
        background-color: #142850; 
        color: white; 
        padding: 15px; 
        border-radius: 8px; 
        margin-bottom: 25px;
        line-height: 1.6;
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

# --- 2. DATA CONNECTION ---
@st.cache_data(ttl=600)
def get_data_from_gsheet():
    try:
        creds = get_google_creds([
            "https://www.googleapis.com/auth/spreadsheets", 
            "https://www.googleapis.com/auth/drive"
        ])
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
        st.error(f"📡 Database Connection Error: {e}")
        return None

def upload_to_drive(pdf_bytes, filename):
    try:
        creds = get_google_creds(["https://www.googleapis.com/auth/drive"])
        service = build('drive', 'v3', credentials=creds)

        file_metadata = {
            'name': filename,
            'parents': [DRIVE_FOLDER_ID] if DRIVE_FOLDER_ID else []
        }
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf')
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        service.permissions().create(fileId=file.get('id'), body={'type': 'anyone', 'role': 'reader'}).execute()
        return file.get('webViewLink')
    except Exception as e:
        st.error(f"Drive Upload Error: {e}")
        return "Upload Failed"

def save_to_fittings(answers, pdf_link=""):
    try:
        creds = get_google_creds(["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        worksheet = sh.worksheet('Fittings')
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp] + [answers.get(f"Q{i:02d}", "") for i in range(1, 23)] + [pdf_link]
        worksheet.append_row(row)
    except Exception as e:
        st.error(f"Error saving to Sheets: {e}")

# --- 3. PRO PDF ENGINE ---
def clean_text(text):
    if not text: return ""
    return re.sub(r'[^\x00-\x7F]+', '', str(text))

class ProFittingPDF(FPDF):
    def header(self):
        self.set_fill_color(20, 40, 80)
        self.rect(0, 0, 210, 25, 'F')
        self.set_font('Arial', 'B', 14); self.set_text_color(255, 255, 255)
        self.cell(0, 10, 'TOUR PROVEN PERFORMANCE REPORT', 0, 1, 'C')
        self.set_font('Arial', '', 8); self.cell(0, -2, f"Date: {datetime.date.today().strftime('%B %d, %Y')}", 0, 1, 'C')
        self.ln(12)

    def draw_player_header(self, answers):
        self.set_font('Arial', 'B', 9); self.set_text_color(20, 40, 80)
        self.cell(0, 6, f"PLAYER: {clean_text(answers.get('Q01','')).upper()}", 0, 1, 'L')
        self.set_font('Arial', '', 8); self.set_text_color(0, 0, 0)
        line1 = f"6i Carry: {answers.get('Q15','')}yd | Flight: {answers.get('Q16','')} | Target: {answers.get('Q17','')} | Miss: {answers.get('Q18','')}"
        line2 = f"Club: {answers.get('Q08','')} {answers.get('Q09','')} | Length: {answers.get('Q13','')} | SW: {answers.get('Q14','')}"
        self.cell(0, 4, clean_text(line1), 0, 1, 'L')
        self.cell(0, 4, clean_text(line2), 0, 1, 'L')
        self.ln(2); self.line(10, self.get_y(), 200, self.get_y()); self.ln(4)

    def draw_recommendation_block(self, title, df, verdict_text):
        self.set_font('Arial', 'B', 10); self.set_text_color(180, 0, 0)
        self.cell(0, 6, clean_text(title.upper()), 0, 1, 'L')
        self.set_font('Arial', 'B', 8); self.set_fill_color(240, 240, 240); self.set_text_color(0, 0, 0)
        cols, w = ["Brand", "Model", "Flex", "Weight"], [40, 85, 30, 30]
        for i, col in enumerate(cols): self.cell(w[i], 6, col, 1, 0, 'C', True)
        self.ln()
        self.set_font('Arial', '', 8)
        for _, row in df.iterrows():
            self.cell(w[0], 5, clean_text(row['Brand']), 1, 0, 'C')
            self.cell(w[1], 5, clean_text(row['Model']), 1, 0, 'C')
            self.cell(w[2], 5, clean_text(row['Flex']), 1, 0, 'C')
            self.cell(w[3], 5, f"{clean_text(row['Weight (g)'])}g", 1, 0, 'C')
            self.ln()
        self.set_font('Arial', 'I', 8); self.multi_cell(0, 4, clean_text(verdict_text)); self.ln(4)

def create_pdf_bytes(player_name, all_winners, answers, verdicts):
    pdf = ProFittingPDF()
    pdf.add_page()
    pdf.draw_player_header(answers)
    mapping = {"Balanced": "Balanced", "Maximum Stability": "Maximum Stability", "Launch & Height": "Launch & Height", "Feel & Smoothness": "Feel & Smoothness"}
    for label, calc_key in mapping.items():
        pdf.draw_recommendation_block(label, all_winners[calc_key], verdicts.get(calc_key, ""))
    return pdf.output(dest='S').encode('latin-1')

def send_email_with_pdf(recipient_email, player_name, pdf_bytes):
    try:
        sender_email = st.secrets["email"]["user"]
        sender_password = st.secrets["email"]["password"].strip()
        msg = MIMEMultipart()
        msg['From'] = f"Tour Proven Fitting <{sender_email}>"
        msg['To'] = recipient_email
        msg['Subject'] = f"Report: {player_name}"
        msg.attach(MIMEText("Your report is attached.", 'plain'))
        part = MIMEApplication(pdf_bytes, Name=f"Report_{player_name}.pdf")
        part['Content-Disposition'] = f'attachment; filename="Report_{player_name}.pdf"'
        msg.attach(part)
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls(); server.login(sender_email, sender_password)
        server.send_message(msg); server.quit()
        return True
    except Exception as e: return str(e)

# --- 4. APP FLOW ---
data = get_data_from_gsheet()

if data:
    if 'step' not in st.session_state: st.session_state.step = 1
    if 'answers' not in st.session_state: st.session_state.answers = {}

    qs = data['Questions']
    total_steps = len(qs)

    if st.session_state.step <= total_steps:
        q_row = qs.iloc[st.session_state.step - 1]
        q_id = q_row['QuestionID']
        st.subheader(f"{q_row['QuestionText']}")
        
        # Simple selection/input logic
        if q_row['InputType'] == 'Dropdown':
            opts = data['Config'][q_row['Options'].split(':')[-1]].dropna().tolist() if ':' in str(q_row['Options']) else []
            ans = st.selectbox("Select option", opts, key=q_id)
        else:
            ans = st.text_input("Type answer", key=q_id)

        if st.button("Next"):
            st.session_state.answers[q_id] = ans
            st.session_state.step += 1
            st.rerun()
    else:
        # --- CALCULATION ENGINE ---
        ans = st.session_state.answers
        shafts = data['Shafts'].copy()
        shafts['Penalty'] = 0
        
        # Example Logic: Carry Penalty
        carry = float(ans.get('Q15', 0)) if ans.get('Q15','').isdigit() else 150
        if carry > 180: shafts.loc[shafts['Flex'].isin(['R', 'A', 'L']), 'Penalty'] += 5000
        
        all_winners = {
            "Balanced": shafts.sort_values('Penalty').head(3),
            "Maximum Stability": shafts.sort_values(['Penalty', 'StabilityIndex'], ascending=[True, False]).head(3),
            "Launch & Height": shafts[shafts['Launch'] == 'High'].sort_values('Penalty').head(3),
            "Feel & Smoothness": shafts[shafts['MidProfile'] == 'Responsive'].sort_values('Penalty').head(3)
        }

        verdicts = {k: f"Based on your profile, the {v.iloc[0]['Model']} is optimized for this category." for k, v in all_winners.items()}

        # Display Results
        st.success("Fitting Complete!")
        col1, col2 = st.columns(2)
        with col1: st.table(all_winners["Balanced"])
        with col2: st.table(all_winners["Maximum Stability"])

        if st.button("Send Report"):
            with st.spinner("Uploading..."):
                pdf_bytes = create_pdf_bytes(ans.get('Q01'), all_winners, ans, verdicts)
                link = upload_to_drive(pdf_bytes, f"Report_{ans.get('Q01')}.pdf")
                save_to_fittings(ans, link)
                send_email_with_pdf(ans.get('Q02'), ans.get('Q01'), pdf_bytes)
                st.balloons()
                st.write(f"View on Drive: {link}")
