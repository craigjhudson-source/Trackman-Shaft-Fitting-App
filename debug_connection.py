import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

st.title("📡 Google Sheets Connection Debugger")

# 1. Check Secrets Formatting
st.subheader("Step 1: Checking Secrets")
try:
    creds_dict = st.secrets["gcp_service_account"]
    st.success(f"✅ Found secrets for: {creds_dict.get('client_email')}")
except Exception as e:
    st.error(f"❌ Could not find 'gcp_service_account' in st.secrets: {e}")
    st.stop()

# 2. Test Credential Scoping
st.subheader("Step 2: Testing Authentication Handshake")
try:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    st.success("✅ Handshake successful. Scopes accepted.")
except Exception as e:
    st.error(f"❌ Auth Handshake failed: {e}")
    st.info("Check if 'Google Sheets API' and 'Google Drive API' are ENABLED in GCP Console.")
    st.stop()

# 3. Test File Access (The "Shared" check)
st.subheader("Step 3: Testing Sheet Access")
SHEET_URL = 'https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit'
try:
    sh = gc.open_by_url(SHEET_URL)
    st.success(f"✅ Successfully opened: {sh.title}")
    
    # Test read access
    worksheet_list = [w.title for w in sh.worksheets()]
    st.write(f"Found tabs: {', '.join(worksheet_list)}")
except gspread.exceptions.SpreadsheetNotFound:
    st.error("❌ Spreadsheet Not Found!")
    st.warning(f"ACTION REQUIRED: Go to your Google Sheet and Share it with: {creds_dict.get('client_email')} (Give it Editor access).")
except Exception as e:
    st.error(f"❌ Access Error: {e}")


