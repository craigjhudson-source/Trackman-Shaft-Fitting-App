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

# --- 2. DATA CONNECTION ---
@st.cache_data(ttl=600)
def get_data_from_gsheet():
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit')
        
        def get_df(name):
            rows = sh.worksheet(name).get_all_values()
            return pd.DataFrame(rows[1:], columns=[h.strip() for h in rows[0]])

        return {k: get_df(k) for k in ['Heads', 'Shafts', 'Questions', 'Responses', 'Config', 'Descriptions']}
    except Exception as e:
        st.error(f"Database Error: {e}"); return None

# --- 3. THE "PRO REPORT" PDF ENGINE ---
class ProFittingPDF(FPDF):
    def header(self):
        self.set_fill_color(20, 40, 80)
        self.rect(0, 0, 210, 30, 'F')
        self.set_font('Arial', 'B', 16)
        self.set_text_color(255, 255, 255)
        self.cell(0, 15, 'TOUR PROVEN PERFORMANCE REPORT', 0, 1, 'C')
        self.set_font('Arial', '', 9)
        self.cell(0, -5, f"Date: {datetime.date.today().strftime('%B %d, %Y')}", 0, 1, 'C')
        self.ln(15)

    def section_title(self, label):
        self.set_font('Arial', 'B', 11)
        self.set_fill_color(230, 230, 230)
        self.set_text_color(20, 40, 80)
        self.cell(0, 8, f"  {label.upper()}", 0, 1, 'L', True)
        self.ln(2)

    def draw_summary_table(self, title, data_list):
        self.set_font('Arial', 'B', 10)
        self.set_text_color(0, 0, 0)
        self.cell(0, 8, title, 0, 1, 'L')
        self.set_font('Arial', '', 9)
        for item in data_list:
            self.cell(40, 6, f"{item['Detail']}:", 0, 0)
            self.cell(0, 6, str(item['Value']), 0, 1)
        self.ln(4)

    def draw_recommendation_grid(self, title, df_top3):
        self.set_font('Arial', 'B', 10)
        self.set_text_color(180, 0, 0)
        self.cell(0, 8, title, 0, 1, 'L')
        
        self.set_font('Arial', 'B', 8)
        self.set_fill_color(245, 245, 245)
        self.set_text_color(0, 0, 0)
        cols = ["Brand", "Model", "Flex", "Weight"]
        w = [40, 80, 35, 30]
        for i, col in enumerate(cols):
            self.cell(w[i], 7, col, 1, 0, 'C', True)
        self.ln()
        
        self.set_font('Arial', '', 8)
        for _, row in df_top3.iterrows():
            self.cell(w[0], 7, str(row['Brand']), 1, 0, 'C')
            self.cell(w[1], 7, str(row['Model']), 1, 0, 'C')
            self.cell(w[2], 7, str(row['Flex']), 1, 0, 'C')
            self.cell(w[3], 7, f"{row['Weight (g)']}g", 1, 0, 'C')
            self.ln()
        self.ln(6)

def create_pdf_bytes(player_name, all_winners_dfs, answers, categories, q_master, verdicts):
    pdf = ProFittingPDF()
    pdf.add_page()
    
    # 1. Questionnaire Summary
    pdf.section_title("Player Profile & Interview Summary")
    col_width = 90
    for cat in categories:
        cat_qs = q_master[q_master['Category'] == cat]
        cat_data = [{"Detail": r['QuestionText'].replace("Current ", ""), "Value": answers.get(r['QuestionID'], "")} for _, r in cat_qs.iterrows()]
        pdf.draw_summary_table(cat, cat_data)

    # 2. Recommendations (All Top 3s)
    pdf.add_page() # Move recommendations to a clean page
    pdf.section_title("Shaft Recommendation Matrix (Top 3 per Category)")
    for mode, df in all_winners_dfs.items():
        pdf.draw_recommendation_grid(mode, df)

    # 3. Fitter's Technical Verdict
    pdf.ln(5)
    pdf.section_title("Fitter's Technical Verdict")
    pdf.set_font('Arial', '', 9)
    for title, text in verdicts.items():
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(0, 6, title, 0, 1)
        pdf.set_font('Arial', '', 9)
        pdf.multi_cell(0, 5, text)
        pdf.ln(3)

    return pdf.output(dest='S').encode('latin-1')

# --- 4. APP LOGIC ---
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
            qid, qtext, qtype = str(row['QuestionID']).strip(), row['QuestionText'], row['InputType']
            # ... (Standard Questionnaire UI here) ...
            if qtype == "Dropdown": st.selectbox(qtext, ["Option A", "Option B"], key=f"widget_{qid}", on_change=sync_all) # Simplified for brevity
            else: st.text_input(qtext, key=f"widget_{qid}", on_change=sync_all)

        if st.button("🔥 Calculate"): st.session_state.interview_complete = True; st.rerun()

    else:
        # --- RESULTS & PDF GENERATION ---
        player_name = st.session_state.answers.get('Q01', 'Player')
        
        # 1. Run Calculations and store ALL Top 3 Dataframes
        df_all = all_data['Shafts'].copy()
        for col in ['FlexScore', 'Weight (g)', 'StabilityIndex', 'LaunchScore', 'EI_Mid']:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)
            
        def get_top_3(mode):
            # (Your specific math logic here)
            return df_all.head(3) # Placeholder

        all_winners_dfs = {
            "Balanced": get_top_3("Balanced"),
            "Maximum Stability": get_top_3("Maximum Stability"),
            "Launch & Height": get_top_3("Launch & Height"),
            "Feel & Smoothness": get_top_3("Feel & Smoothness")
        }

        # 2. Gather Technical Verdicts
        desc_lookup = dict(zip(all_data['Descriptions']['Model'], all_data['Descriptions']['Blurb']))
        verdicts = {
            f"Primary: {all_winners_dfs['Balanced'].iloc[0]['Model']}": desc_lookup.get(all_winners_dfs['Balanced'].iloc[0]['Model'], ""),
            f"Stability: {all_winners_dfs['Maximum Stability'].iloc[0]['Model']}": desc_lookup.get(all_winners_dfs['Maximum Stability'].iloc[0]['Model'], "")
        }

        # 3. Display in App
        st.title(f"⛳ Fitting Matrix: {player_name}")
        # (App UI Tables here)

        # 4. Email/PDF Trigger
        if not st.session_state.email_sent:
            pdf_bytes = create_pdf_bytes(player_name, all_winners_dfs, st.session_state.answers, categories, q_master, verdicts)
            # send_email_with_pdf(...)
            st.session_state.email_sent = True
