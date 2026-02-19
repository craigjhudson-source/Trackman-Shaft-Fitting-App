import smtplib
import streamlit as st
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication


def send_email_with_pdf(recipient_email: str, player_name: str, pdf_bytes: bytes, environment: str | None = None):
    """
    Email sender only.
    PDF generation lives in utils_pdf.py (single source of truth).
    """
    try:
        user = st.secrets["email"]["user"]
        pwd = st.secrets["email"]["password"].replace(" ", "").strip()

        msg = MIMEMultipart()
        msg["From"] = f"Tour Proven <{user}>"
        msg["To"] = recipient_email
        msg["Subject"] = f"Tour Proven Iron Build Report: {player_name}"

        # Best-effort: include goal if present (no hard dependency on any QID names)
        goal = ""
        try:
            answers = st.session_state.get("answers", {}) if hasattr(st, "session_state") else {}
            if isinstance(answers, dict):
                goal = str(answers.get("Q23", "") or "").strip()
        except Exception:
            goal = ""

        lines = [f"Hello {player_name},", ""]
        if environment:
            lines.append(f"Environment: {environment}")
        if goal:
            lines.append(f"Primary Performance Objective: {goal}")
        lines += ["", "Attached is your Tour Proven report.", "", "— Tour Proven"]

        msg.attach(MIMEText("\n".join(lines), "plain"))

        safe_name = "".join([c for c in (player_name or "Player") if c.isalnum() or c in (" ", "_", "-")]).strip()
        safe_name = safe_name.replace(" ", "_") or "Player"
        filename = f"TourProven_Report_{safe_name}.pdf"

        part = MIMEApplication(pdf_bytes, Name=filename)
        part["Content-Disposition"] = f'attachment; filename="{filename}"'
        msg.attach(part)

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(user, pwd)
        server.send_message(msg)
        server.quit()
        return True

    except Exception as e:
        return str(e)
