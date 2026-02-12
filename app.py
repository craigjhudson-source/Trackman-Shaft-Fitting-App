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

# --- 0. SECRETS & PEM FORMATTING FIX ---
def get_google_creds(scopes):
    """Ensures secrets are in a proper dictionary format and fixes PEM key errors."""
    try:
        # Convert Streamlit Secrets object to a standard Python dictionary
        creds_dict = dict(st.secrets["gcp_service_account"])
        
        # FIX: The "InvalidByte" error happens if the PEM key isn't perfectly formatted.
        # This block forces the key into the correct RSA block format.
        if "private_key" in creds_dict:
            pk = creds_dict["private_key"]
            # Remove any literal '\n' text and replace with actual newlines
            pk = pk.replace("\\n", "\n")
            # Ensure the header and footer are on their own lines
            if "-----BEGIN PRIVATE KEY-----" in pk and not pk.startswith("-----BEGIN"):
                pk = pk.strip()
            creds_dict["private_key"] = pk

        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    except Exception as e:
        st.error(f"🔐 Security Credential Error: {e}")
        st.info("Check that your [gcp_service_account] section in Secrets uses triple quotes \"\"\" for the private_key.")
        st.stop()

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Tour Proven Shaft Fitting", layout="wide", page_icon="⛳")

# Folder ID where PDFs will be stored
DRIVE_FOLDER_ID = "1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY" 

st.markdown("""
    <style>
    [data-testid="stTable"] { font-size: 12px !important; }
    [data-testid="stTable"] td { padding: 2px !important; }
    .main { background-color: #f8f9fa; }
    .verdict-text {
        font-style: italic; color: #444; margin-bottom: 25px;
        font-size: 13px; border-left: 3px solid #b40000; padding-left: 10px;
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
        file_metadata = {'name': filename, 'parents': [DRIVE_FOLDER_ID] if DRIVE_FOLDER_ID else []}
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf')
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        service.permissions().create(fileId=file.get('id'), body={'type': 'anyone', 'role': 'reader'}).execute()
        return file.get('webViewLink')
    except Exception as e:
        return f"Upload Failed: {e}"

def save_to_fittings(answers, pdf_link=""):
    try:
        creds = get_google_creds(["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        worksheet = sh.worksheet('Fittings')
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp] + [answers.get(f"Q{i:02d}", "") for i in range(1, 23)] + [pdf_link]
        worksheet.append_row(row)
    except: pass

# --- 3. PRO PDF ENGINE ---
def clean_text(text):
    return re.sub(r'[^\x00-\x7F]+', '', str(text)) if text else ""

class ProFittingPDF(FPDF):
    def header(self):
        self.set_fill_color(20, 40, 80)
        self.rect(0, 0, 210, 25, 'F')
        self.set_font('Arial', 'B', 14); self.set_text_color(255, 255, 255)
        self.cell(0, 10, 'TOUR PROVEN PERFORMANCE REPORT', 0, 1, 'C')
        self.ln(12)

    def draw_recommendation_block(self, title, df, verdict_text):
        self.set_font('Arial', 'B', 10); self.set_text_color(180, 0, 0)
        self.cell(0, 6, clean_text(title.upper()), 0, 1, 'L')
        self.set_font('Arial', 'B', 8); self.set_fill_color(240, 240, 240); self.set_text_color(0, 0, 0)
        cols, w = ["Brand", "Model", "Flex", "Weight"], [40, 85, 30, 30]
        for i, col in enumerate(cols): self.cell(w[i], 6, col, 1, 0, 'C', True)
        self.ln()
        self.set_font('Arial', '', 8)
        for _, row in df.iterrows():
            self.cell(w[0], 5, clean_text(row.get('Brand','')), 1, 0, 'C')
            self.cell(w[1], 5, clean_text(row.get('Model','')), 1, 0, 'C')
            self.cell(w[2], 5, clean_text(row.get('Flex','')), 1, 0, 'C')
            self.cell(w[3], 5, f"{clean_text(row.get('Weight (g)',''))}g", 1, 0, 'C')
            self.ln()
        self.set_font('Arial', 'I', 8); self.multi_cell(0, 4, clean_text(verdict_text)); self.ln(4)

def create_pdf_bytes(player_name, all_winners, answers, verdicts):
    pdf = ProFittingPDF()
    pdf.add_page()
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, f"Fitting Report: {player_name}", 0, 1)
    mapping = {"Balanced": "Balanced", "Maximum Stability": "Maximum Stability", "Launch & Height": "Launch & Height", "Feel & Smoothness": "Feel & Smoothness"}
    for label, key in mapping.items():
        if key in all_winners:
            pdf.draw_recommendation_block(label, all_winners[key], verdicts.get(key, ""))
    return pdf.output(dest='S').encode('latin-1')

# --- 4. APP FLOW ---
data = get_data_from_gsheet()

if data:
    if 'step' not in st.session_state: st.session_state.step = 1
    if 'answers' not in st.session_state: st.session_state.answers = {}

    qs = data['Questions']
    if st.session_state.step <= len(qs):
        q_row = qs.iloc[st.session_state.step - 1]
        q_id = q_row['QuestionID']
        st.subheader(f"{q_row['QuestionText']}")
        
        if q_row['InputType'] == 'Dropdown':
            opts = data['Config'][q_row['Options'].split(':')[-1]].dropna().tolist() if ':' in str(q_row['Options']) else ["Yes", "No"]
            ans = st.selectbox("Choose one:", opts, key=q_id)
        else:
            ans = st.text_input("Answer:", key=q_id)

        if st.button("Next Step"):
            st.session_state.answers[q_id] = ans
            st.session_state.step += 1
            st.rerun()
    else:
        # --- CALCULATION ENGINE ---
        ans = st.session_state.answers
        shafts = data['Shafts'].copy()
        shafts['Penalty'] = 0
        
        # Calculation logic
        all_winners = {
            "Balanced": shafts.sort_values('Penalty').head(3),
            "Maximum Stability": shafts.sort_values(['Penalty', 'StabilityIndex'], ascending=[True, False]).head(3),
            "Launch & Height": shafts[shafts['Launch'] == 'High'].sort_values('Penalty').head(3),
            "Feel & Smoothness": shafts[shafts['MidProfile'] == 'Responsive'].sort_values('Penalty').head(3)
        }
        verdicts = {k: "Recommended based on your impact dynamics." for k in all_winners.keys()}

        st.success("Fitting Complete!")
        st.table(all_winners["Balanced"])

        if st.button("Generate & Email PDF"):
            with st.spinner("Processing Report..."):
                pdf_bytes = create_pdf_bytes(ans.get('Q01','Player'), all_winners, ans, verdicts)
                link = upload_to_drive(pdf_bytes, f"Fitting_{ans.get('Q01','Player')}.pdf")
                save_to_fittings(ans, link)
                st.success(f"Report Ready! [View PDF]({link})")
