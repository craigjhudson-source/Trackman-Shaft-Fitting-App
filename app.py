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
                return df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
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

def save_to_fittings(answers):
    try:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        gc = gspread.authorize(creds)
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit'
        sh = gc.open_by_url(SHEET_URL)
        worksheet = sh.worksheet('Fittings')
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp]
        for i in range(1, 24):
            qid = f"Q{i:02d}"
            row.append(answers.get(qid, ""))
        worksheet.append_row(row)
    except Exception as e:
        st.error(f"Error saving to Sheets: {e}")

# --- 2. PDF & EMAIL UTILITIES ---
def create_pdf_bytes(player_name, winners, answers):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20)
    pdf.set_text_color(20, 40, 100)
    pdf.cell(200, 15, "PATRIOT GOLF PERFORMANCE REPORT", ln=True, align='C')
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 10, f"Player: {player_name}", ln=True)
    pdf.set_font("Arial", size=10)
    stats = [f"6i Carry: {answers.get('Q15', '—')}yd", f"Miss: {answers.get('Q18', '—')}", f"Target Flight: {answers.get('Q17', '—')}"]
    pdf.cell(0, 7, " | ".join(stats), ln=True)
    pdf.ln(10)
    for mode, row in winners.items():
        pdf.set_font("Arial", 'B', 12)
        pdf.set_text_color(180, 0, 0)
        pdf.cell(0, 10, f"MODE: {mode.upper()}", ln=True)
        pdf.set_font("Arial", size=11)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(10, 8, "") 
        pdf.cell(0, 8, f"ID: {row['ID']} | {row['Brand']} {row['Model']} ({row['Flex']} | {row['Weight (g)']}g)", ln=True)
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
        body = f"Hello {player_name},\n\nAttached is your personalized Patriot Golf shaft report.\n\nBest,\nPatriot Golf"
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
        st.error(f"Email Dispatch Error: {e}"); return False

# --- 3. STATE MANAGEMENT ---
if 'form_step' not in st.session_state: st.session_state.form_step = 0
if 'interview_complete' not in st.session_state: st.session_state.interview_complete = False
if 'answers' not in st.session_state: st.session_state.answers = {}
if 'email_sent' not in st.session_state: st.session_state.email_sent = False

def sync_all():
    for key in st.session_state:
        if key.startswith("widget_"):
            qid = key.replace("widget_", "")
            st.session_state.answers[qid] = st.session_state[key]

all_data = get_data_from_gsheet()

# --- 4. DYNAMIC QUESTIONNAIRE ---
if all_data:
    q_master = all_data['Questions']
    categories = list(dict.fromkeys(q_master['Category'].tolist()))
    
    if not st.session_state.interview_complete:
        st.title("Patriot Golf Performance Fitting")
        st.progress((st.session_state.form_step + 1) / len(categories))
        current_cat = categories[st.session_state.form_step]
        q_df = q_master[q_master['Category'] == current_cat]
        st.subheader(f"Section: {current_cat}")
        for _, row in q_df.iterrows():
            qid = str(row['QuestionID']).strip()
            qtext, qtype, qopts = row['QuestionText'], row['InputType'], str(row['Options']).strip()
            ans_val = st.session_state.answers.get(qid, "")
            if qtype == "Dropdown":
                opts = [""]
                if "Heads" in qopts:
                    brand_val = st.session_state.answers.get("Q08", "")
                    if "Brand" in qtext: opts += sorted(all_data['Heads']['Manufacturer'].unique().tolist())
                    else:
                        if brand_val: opts += sorted(all_data['Heads'][all_data['Heads']['Manufacturer'] == brand_val]['Model'].unique().tolist())
                        else: opts = ["Select Brand First"]
                elif "Shafts" in qopts:
                    s_brand = st.session_state.answers.get("Q10", "")
                    s_flex = st.session_state.answers.get("Q11", "")
                    if "Brand" in qtext: opts += sorted(all_data['Shafts']['Brand'].unique().tolist())
                    elif "Flex" in qtext:
                        if s_brand: opts += sorted(all_data['Shafts'][all_data['Shafts']['Brand'] == s_brand]['Flex'].unique().tolist())
                        else: opts = ["Select Brand First"]
                    elif "Model" in qtext:
                        if s_brand and s_flex:
                            filtered = all_data['Shafts'][(all_data['Shafts']['Brand'] == s_brand) & (all_data['Shafts']['Flex'] == s_flex)]
                            opts += sorted(filtered['Model'].unique().tolist())
                        elif s_brand: opts = ["Select Flex First"]
                        else: opts = ["Select Brand First"]
                elif "Config:" in qopts:
                    col = qopts.split(":")[1].strip()
                    if col in all_data['Config'].columns: opts += all_data['Config'][col].dropna().tolist()
                else: opts += all_data['Responses'][all_data['Responses']['QuestionID'] == qid]['ResponseOption'].tolist()
                opts = list(dict.fromkeys([str(x) for x in opts if x]))
                if "" not in opts: opts = [""] + opts
                st.selectbox(qtext, opts, index=opts.index(str(ans_val)) if str(ans_val) in opts else 0, key=f"widget_{qid}", on_change=sync_all)
            elif qtype == "Numeric": st.number_input(qtext, value=float(ans_val) if ans_val else 0.0, key=f"widget_{qid}", on_change=sync_all)
            else: st.text_input(qtext, value=str(ans_val), key=f"widget_{qid}", on_change=sync_all)
        st.divider()
        c1, c2, _ = st.columns([1,1,4])
        if c1.button("⬅️ Back") and st.session_state.form_step > 0:
            sync_all(); st.session_state.form_step -= 1; st.rerun()
        if st.session_state.form_step < len(categories) - 1:
            if c2.button("Next ➡️"): sync_all(); st.session_state.form_step += 1; st.rerun()
        else:
            if c2.button("🔥 Generate Prescription"):
                sync_all(); save_to_fittings(st.session_state.answers); st.session_state.interview_complete = True; st.rerun()

    else:
        # --- 5. RESULTS & REPORT ---
        player_name = st.session_state.answers.get('Q01', 'Player')
        player_email = st.session_state.answers.get('Q02', '')
        st.title(f"⛳ Fitting Matrix: {player_name}")
        
        # --- ULTRA-COMPACT TABLE SUMMARY ---
        st.subheader("📊 Questionnaire Summary")
        summary_cols = st.columns(len(categories))
        for i, cat in enumerate(categories):
            with summary_cols[i]:
                cat_qs = q_master[q_master['Category'] == cat]
                cat_data = []
                for _, row in cat_qs.iterrows():
                    qid = row['QuestionID']
                    if qid in st.session_state.answers and st.session_state.answers[qid]:
                        # Shorten the label for extreme compactness if needed
                        label = row['QuestionText'].replace("Current ", "").replace("Target ", "")
                        cat_data.append({"Field": label, "Value": st.session_state.answers[qid]})
                
                if cat_data:
                    st.markdown(f"**{cat}**")
                    st.dataframe(pd.DataFrame(cat_data), use_container_width=True, hide_index=True)

        if st.button("✏️ Edit Survey"):
            st.session_state.interview_complete = False
            st.session_state.email_sent = False
            st.rerun()

        st.divider()

        # LOGIC PREP
        try: carry_6i = float(st.session_state.answers.get('Q15', 150))
        except: carry_6i = 150.0
        primary_miss = st.session_state.answers.get('Q18', 'None')
        target_flight = st.session_state.answers.get('Q17', 'Mid')
        current_shaft_model = st.session_state.answers.get('Q12', 'Unknown')
        
        if carry_6i >= 195: f_tf, ideal_w = 8.5, 130
        elif carry_6i >= 180: f_tf, ideal_w = 7.0, 125
        elif carry_6i >= 165: f_tf, ideal_w = 6.0, 110
        elif carry_6i >= 150: f_tf, ideal_w = 5.0, 95
        else: f_tf, ideal_w = 4.0, 80

        df_all = all_data['Shafts'].copy()
        for col in ['FlexScore', 'LaunchScore', 'Weight (g)', 'StabilityIndex', 'EI_Mid']:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)

        def get_top_3(df_in, mode):
            df_temp = df_in.copy()
            df_temp['Penalty'] = abs(df_temp['FlexScore'] - f_tf) * 200
            if carry_6i >= 180: df_temp.loc[df_temp['FlexScore'] < 6.5, 'Penalty'] += 4000
            df_temp['Penalty'] += abs(df_temp['Weight (g)'] - ideal_w) * 15
            if mode == "Maximum Stability": df_temp['Penalty'] -= (df_temp['StabilityIndex'] * 600)
            elif mode == "Launch & Height": df_temp['Penalty'] -= (df_temp['LaunchScore'] * 500)
            elif mode == "Feel & Smoothness": df_temp['Penalty'] += (df_temp['EI_Mid'] * 400)
            res = df_temp.sort_values('Penalty').head(3)[['ID', 'Brand', 'Model', 'Flex', 'Weight (g)', 'Launch']]
            return res

        # --- RECOMMENDATION TABLES ---
        modes = [("Balanced", "⚖️"), ("Maximum Stability", "🛡️"), ("Launch & Height", "🚀"), ("Feel & Smoothness", "☁️")]
        winners = {}
        r1 = st.columns(2); r2 = st.columns(2); all_cols = r1 + r2
        for i, (mode, icon) in enumerate(modes):
            with all_cols[i]:
                st.subheader(f"{icon} {mode}")
                top_df = get_top_3(df_all, mode)
                winners[mode] = top_df.iloc[0]
                st.dataframe(top_df, use_container_width=True, hide_index=True, column_config={"ID": st.column_config.TextColumn("ID", width="small")})

        if not st.session_state.email_sent and player_email:
            with st.spinner(f"Emailing report..."):
                pdf_bytes = create_pdf_bytes(player_name, winners, st.session_state.answers)
                if send_email_with_pdf(player_email, player_name, pdf_bytes):
                    st.success("📬 Report Sent"); st.session_state.email_sent = True

        st.divider()
        st.subheader("🔬 Fitter's Technical Verdict")
        desc_lookup = dict(zip(all_data['Descriptions']['Model'], all_data['Descriptions']['Blurb'])) if not all_data['Descriptions'].empty else {}
        v1, v2 = st.columns(2)
        with v1:
            st.info(f"**Primary: {winners['Balanced']['Model']} (ID: {winners['Balanced']['ID']})**\n\n{desc_lookup.get(winners['Balanced']['Model'], 'Optimized.')}")
            st.error(f"**Anti-{primary_miss}: {winners['Maximum Stability']['Model']} (ID: {winners['Maximum Stability']['ID']})**")
        with v2:
            st.success(f"**Flight: {winners['Launch & Height']['Model']} (ID: {winners['Launch & Height']['ID']})**")
            st.warning(f"**Smoothness: {winners['Feel & Smoothness']['Model']} (ID: {winners['Feel & Smoothness']['ID']})**")

        if st.button("🆕 New Fitting"):
            st.session_state.clear(); st.rerun()
