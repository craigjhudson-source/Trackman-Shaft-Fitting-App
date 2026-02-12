# utils.py
import re
import smtplib
import datetime
from fpdf import FPDF
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import streamlit as st

def clean_text(text):
    return re.sub(r'[^\x00-\x7F]+', '', str(text)) if text else ""

class ProFittingPDF(FPDF):
    def header(self):
        self.set_fill_color(20, 40, 80); self.rect(0, 0, 210, 25, 'F')
        self.set_font('helvetica', 'B', 14); self.set_text_color(255, 255, 255)
        self.cell(0, 10, 'TOUR PROVEN PERFORMANCE REPORT', 0, 1, 'C')
        self.set_font('helvetica', '', 8); self.cell(0, -2, f"Date: {datetime.date.today().strftime('%B %d, %Y')}", 0, 1, 'C')
        self.ln(12)

    def draw_player_header(self, answers):
        self.set_font('helvetica', 'B', 9); self.set_text_color(20, 40, 80)
        self.cell(0, 6, f"PLAYER: {clean_text(answers.get('Q01','')).upper()}", 0, 1, 'L')
        self.set_font('helvetica', '', 8); self.set_text_color(0, 0, 0)
        line1 = f"6i Carry: {answers.get('Q15','')}yd | Flight: {answers.get('Q16','')} | Target: {answers.get('Q17','')} | Miss: {answers.get('Q18','')}"
        line2 = f"Current Head: {answers.get('Q08','')} {answers.get('Q09','')} | Current Shaft: {answers.get('Q12','')} ({answers.get('Q11','')})"
        line3 = f"Length: {answers.get('Q13','')} | Swing Weight: {answers.get('Q14','')} | Grip: {answers.get('Q06','')} | Ball: {answers.get('Q07','')}"
        self.cell(0, 4, clean_text(line1), 0, 1, 'L')
        self.cell(0, 4, clean_text(line2), 0, 1, 'L')
        self.cell(0, 4, clean_text(line3), 0, 1, 'L')
        self.ln(2); self.line(10, self.get_y(), 200, self.get_y()); self.ln(4)

    def draw_recommendation_block(self, title, df, verdict_text):
        self.set_font('helvetica', 'B', 10); self.set_text_color(180, 0, 0); self.cell(0, 6, clean_text(title.upper()), 0, 1, 'L')
        self.set_font('helvetica', 'B', 8); self.set_fill_color(240, 240, 240); self.set_text_color(0, 0, 0)
        cols, w = ["Brand", "Model", "Flex", "Weight"], [40, 85, 30, 30]
        for i, col in enumerate(cols): self.cell(w[i], 6, col, 1, 0, 'C', True)
        self.ln(); self.set_font('helvetica', '', 8)
        for _, row in df.iterrows():
            for i, c in enumerate(['Brand', 'Model', 'Flex', 'Weight (g)']): self.cell(w[i], 5, clean_text(row[c]), 1, 0, 'C')
            self.ln()
        self.set_font('helvetica', 'B', 8); self.cell(0, 4, "Fitter's Technical Verdict:", 0, 1)
        self.set_font('helvetica', 'I', 8); self.multi_cell(0, 4, clean_text(verdict_text)); self.ln(4)

def create_pdf_bytes(player_name, all_winners, answers, verdicts):
    pdf = ProFittingPDF(); pdf.add_page(); pdf.draw_player_header(answers)
    mapping = {"Balanced Choice": "Balanced", "Maximum Stability (Anti-Hook)": "Maximum Stability", "Launch & Height Optimizer": "Launch & Height", "Feel & Smoothness": "Feel & Smoothness"}
    v_keys = list(verdicts.keys())
    for i, (label, calc_key) in enumerate(mapping.items()):
        pdf.draw_recommendation_block(label, all_winners[calc_key], verdicts[v_keys[i]])
    return bytes(pdf.output())

def send_email_with_pdf(recipient_email, player_name, pdf_bytes):
    try:
        user, pwd = st.secrets["email"]["user"], st.secrets["email"]["password"].replace(" ", "").strip()
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = f"Tour Proven <{user}>", recipient_email, f"Fitting Report: {player_name}"
        msg.attach(MIMEText(f"Hello {player_name},\n\nAttached is your one-page Performance Report.", 'plain'))
        part = MIMEApplication(pdf_bytes, Name=f"Report_{player_name}.pdf")
        part['Content-Disposition'] = f'attachment; filename="Report_{player_name}.pdf"'; msg.attach(part)
        server = smtplib.SMTP('smtp.gmail.com', 587); server.starttls(); server.login(user, pwd); server.send_message(msg); server.quit()
        return True
    except Exception as e: return str(e)
