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

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Tour Proven Shaft Fitting", layout="wide", page_icon="⛳")

# Folder ID where PDFs will be stored (You can find this in the URL of your Google Drive folder)
DRIVE_FOLDER_ID = "YOUR_GOOGLE_DRIVE_FOLDER_ID_HERE" 

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
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=[
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
        st.error(f"📡 Database Error: {e}"); return None

def upload_to_drive(pdf_bytes, filename):
    """Uploads PDF to Google Drive and returns the public webViewLink."""
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/drive"])
        service = build('drive', 'v3', credentials=creds)

        file_metadata = {
            'name': filename,
            'parents': [DRIVE_FOLDER_ID] if DRIVE_FOLDER_ID != "YOUR_GOOGLE_DRIVE_FOLDER_ID_HERE" else []
        }
        
        # Convert bytes to file-like object for upload
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf')
        
        # Upload file
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        file_id = file.get('id')

        # Set permissions to "anyone with the link can view"
        service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        st.error(f"Drive Upload Error: {e}")
        return "Upload Failed"

def save_to_fittings(answers, pdf_link=""):
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        worksheet = sh.worksheet('Fittings')
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Row data + the new PDF link at the end (Column 25)
        row = [timestamp] + [answers.get(f"Q{i:02d}", "") for i in range(1, 22)] + ["", "", pdf_link]
        worksheet.append_row(row)
    except Exception as e: st.error(f"Error saving fitting: {e}")

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
        line3 = f"Shaft: {answers.get('Q12','')} ({answers.get('Q11','')}) | Grip: {answers.get('Q06','')} | Ball: {answers.get('Q07','')}"
        
        self.cell(0, 4, clean_text(line1), 0, 1, 'L')
        self.cell(0, 4, clean_text(line2), 0, 1, 'L')
        self.cell(0, 4, clean_text(line3), 0, 1, 'L')
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
        self.ln(1); self.set_font('Arial', 'B', 8); self.cell(0, 4, "Fitter's Technical Verdict:", 0, 1)
        self.set_font('Arial', 'I', 8); self.multi_cell(0, 4, clean_text(verdict_text)); self.ln(4)

def create_pdf_bytes(player_name, all_winners, answers, verdicts):
    pdf = ProFittingPDF()
    pdf.add_page()
    pdf.draw_player_header(answers)
    mapping = {
        "Balanced Choice": "Balanced",
        "Maximum Stability (Anti-Hook)": "Maximum Stability",
        "Launch & Height Optimizer": "Launch & Height",
        "Feel & Smoothness": "Feel & Smoothness"
    }
    v_keys = list(verdicts.keys())
    for i, (label, calc_key) in enumerate(mapping.items()):
        pdf.draw_recommendation_block(label, all_winners[calc_key], verdicts[v_keys[i]])
    # Use output(dest='S') for byte string
    return pdf.output(dest='S').encode('latin-1')

def send_email_with_pdf(recipient_email, player_name, pdf_bytes):
    try:
        sender_email = st.secrets["email"]["user"]
        sender_password = str(st.secrets["email"]["password"]).replace(" ", "").strip()
        msg = MIMEMultipart()
        msg['From'] = f"Tour Proven Shaft Fitting <{sender_email}>"
        msg['To'] = recipient_email
        msg['Subject'] = f"Tour Proven Fitting Report: {player_name}"
        msg.attach(MIMEText(f"Hello {player_name},\n\nAttached is your one-page Performance Report.", 'plain'))
        part = MIMEApplication(pdf_bytes, Name=f"Tour_Proven_{player_name}.pdf")
        part['Content-Disposition'] = f'attachment; filename="Tour_Proven_{player_name}.pdf"'
        msg.attach(part)
        server = smtplib.SMTP('smtp.gmail.com', 587); server.starttls()
        server.login(sender_email, sender_password); server.send_message(msg); server.quit()
        return True
    except Exception as e: return str(e)

# --- 4. APP FLOW ---
# (Interview logic remains same as provided in prompt)
# ... [Omitted for brevity, assuming standard selection logic] ...

# --- MODIFIED CALCULATION TRIGGER ---
if st.session_state.get('interview_complete'):
    ans = st.session_state.answers
    player_name = ans.get('Q01', 'Player')
    
    # Run the calc and PDF generation
    # ... [Assuming all_winners and verdicts are calculated as in your script] ...

    if not st.session_state.get('data_saved'):
        with st.spinner("Generating Report and Archiving to Cloud..."):
            # 1. Generate PDF Bytes
            pdf_bytes = create_pdf_bytes(player_name, all_winners, ans, verdicts)
            
            # 2. Upload to Drive and get Link
            pdf_filename = f"Fitting_{player_name}_{datetime.datetime.now().strftime('%Y%m%d')}.pdf"
            pdf_link = upload_to_drive(pdf_bytes, pdf_filename)
            
            # 3. Save everything (including link) to Sheets
            save_to_fittings(ans, pdf_link)
            
            # 4. Email the player
            if player_email:
                send_email_with_pdf(player_email, player_name, pdf_bytes)
            
            st.session_state['data_saved'] = True
            st.success(f"✅ Fitting archived and sent to {player_email}")
