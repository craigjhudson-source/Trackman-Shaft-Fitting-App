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

# REPLACE THIS WITH YOUR ACTUAL FOLDER ID FROM GOOGLE DRIVE URL
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
        if "gcp_service_account" not in st.secrets:
            st.error("Missing Secrets: gcp_service_account")
            return None
            
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
        st.error(f"📡 Database Error: {e}")
        return None

# --- 3. UTILITIES & CLOUD STORAGE ---

def upload_to_drive(pdf_bytes, filename):
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/drive"])
        service = build('drive', 'v3', credentials=creds)

        file_metadata = {
            'name': filename,
            'parents': [DRIVE_FOLDER_ID] if DRIVE_FOLDER_ID != "YOUR_GOOGLE_DRIVE_FOLDER_ID_HERE" else []
        }
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf')
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        service.permissions().create(fileId=file.get('id'), body={'type': 'anyone', 'role': 'reader'}).execute()
        return file.get('webViewLink')
    except Exception as e:
        return f"Upload Failed: {e}"

def save_to_fittings(answers, pdf_link=""):
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        worksheet = sh.worksheet('Fittings')
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp] + [answers.get(f"Q{i:02d}", "") for i in range(1, 23)] + [pdf_link]
        worksheet.append_row(row)
    except: pass

class ProFittingPDF(FPDF):
    def header(self):
        self.set_fill_color(20, 40, 80)
        self.rect(0, 0, 210, 25, 'F')
        self.set_font('Arial', 'B', 14); self.set_text_color(255, 255, 255)
        self.cell(0, 10, 'TOUR PROVEN PERFORMANCE REPORT', 0, 1, 'C')
        self.ln(10)

def clean_text(text):
    return str(text).encode('latin-1', 'ignore').decode('latin-1')

# --- 4. ENGINE & UI ---
data = get_data_from_gsheet()
if data:
    if 'step' not in st.session_state: st.session_state.step = 1
    if 'answers' not in st.session_state: st.session_state.answers = {}

    st.title("⛳ Tour Proven Shaft Fitting")

    # SIMPLE INTERVIEW
    qs = data['Questions']
    total_steps = len(qs)
    
    if st.session_state.step <= total_steps:
        q_row = qs.iloc[st.session_state.step - 1]
        q_id = q_row['QuestionID']
        st.subheader(f"Step {st.session_state.step}: {q_row['QuestionText']}")
        
        # Choice logic
        ans = st.text_input("Answer here", key=f"input_{q_id}")
        
        if st.button("Next"):
            st.session_state.answers[q_id] = ans
            st.session_state.step += 1
            st.rerun()

    else:
        # --- CALCULATION LOGIC ---
        ans = st.session_state.answers
        carry = float(ans.get('Q15', 0))
        miss = ans.get('Q18', 'None')
        
        shafts = data['Shafts'].copy()
        shafts['Penalty'] = 0
        
        # Simple Logic Example
        if carry > 180:
            shafts.loc[shafts['Flex'].str.contains('R|A|L', na=False), 'Penalty'] += 5000
        if "Hook" in miss:
            shafts.loc[shafts['TipProfile'] == 'Active', 'Penalty'] += 2000

        # Define Categories
        categories = {
            "Balanced": shafts.sort_values('Penalty').head(3),
            "Maximum Stability": shafts[shafts['StabilityIndex'].astype(float) > 8].sort_values('Penalty').head(3),
            "Launch & Height": shafts[shafts['Launch'] == 'High'].sort_values('Penalty').head(3),
            "Feel & Smoothness": shafts[shafts['MidProfile'] == 'Responsive'].sort_values('Penalty').head(3)
        }

        # DISPLAY RESULTS
        col1, col2 = st.columns(2)
        for i, (cat_name, df) in enumerate(categories.items()):
            with (col1 if i % 2 == 0 else col2):
                st.subheader(cat_name)
                st.table(df[['Brand', 'Model', 'Flex', 'Weight (g)']])

        # SAVE & CLOUD
        if st.button("Finalize & Email Report"):
            with st.spinner("Processing..."):
                # Create PDF
                pdf = ProFittingPDF()
                pdf.add_page()
                pdf.set_font("Arial", size=10)
                pdf.cell(200, 10, txt=f"Fitting for {ans.get('Q01', 'Player')}", ln=1, align='C')
                pdf_bytes = pdf.output(dest='S').encode('latin-1')
                
                # Cloud Actions
                link = upload_to_drive(pdf_bytes, f"Fitting_{ans.get('Q01')}.pdf")
                save_to_fittings(ans, link)
                
                st.success(f"Archived to Google Drive! View: {link}")
