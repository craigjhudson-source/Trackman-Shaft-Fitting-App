import re
import smtplib
import streamlit as st
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# Delegate PDF generation to the hardened engine
from utils_pdf import create_pdf_bytes as create_pdf_bytes  # noqa: F401


def clean_text(text):
    # Retained for backward compatibility with any callers/utilities.
    return re.sub(r"[^\x00-\x7F]+", "", str(text)) if text else ""


def send_email_with_pdf(recipient_email, player_name, pdf_bytes, environment=None):
    try:
        user = st.secrets["email"]["user"]
        pwd = st.secrets["email"]["password"].replace(" ", "").strip()

        msg = MIMEMultipart()
        msg["From"] = f"Tour Proven <{user}>"
        msg["To"] = recipient_email
        msg["Subject"] = f"Fitting Report: {player_name}"

        env_line = f"\nEnvironment: {environment}\n" if environment else "\n"
        body = f"Hello {player_name},{env_line}\nAttached is your Performance Report."
        msg.attach(MIMEText(body, "plain"))

        part = MIMEApplication(pdf_bytes, Name=f"Report_{player_name}.pdf")
        part["Content-Disposition"] = f'attachment; filename="Report_{player_name}.pdf"'
        msg.attach(part)

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(user, pwd)
        server.send_message(msg)
        server.quit()
        return True

    except Exception as e:
        return str(e)
