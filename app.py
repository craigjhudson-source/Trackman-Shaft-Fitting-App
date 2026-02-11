# --- UPDATED TRACKMAN PARSER ---
def process_trackman(file):
    try:
        # Check if it's CSV or Excel
        if file.name.endswith('.csv'):
            df_raw = pd.read_csv(file)
        else:
            df_raw = pd.read_excel(file)
            
        # Find header row (Search for 'Club Speed [mph]')
        # We use a more flexible search in case CSV formatting shifts columns
        header_row = None
        for i in range(len(df_raw)):
            if 'Club Speed [mph]' in df_raw.iloc[i].values:
                header_row = i
                break
        
        if header_row is not None:
            # Re-read or slice the dataframe from that point
            if file.name.endswith('.csv'):
                df = pd.read_csv(file, skiprows=header_row + 1)
            else:
                df = pd.read_excel(file, skiprows=header_row + 1)
                
            df = df.dropna(subset=['Club Speed [mph]'])
            
            return {
                "speed": pd.to_numeric(df['Club Speed [mph]'], errors='coerce').mean(),
                "launch": pd.to_numeric(df['Launch Angle [deg]'], errors='coerce').mean(),
                "spin": pd.to_numeric(df['Spin Rate [rpm]'], errors='coerce').mean(),
                "carry": pd.to_numeric(df['Carry Flat - Length [yds]'], errors='coerce').mean()
            }
        else:
            st.error("⚠️ Could not find 'Club Speed [mph]' header. Check your Trackman export settings.")
            return None
    except Exception as e:
        st.error(f"⚠️ Trackman Parsing Error: {e}")
        return None

# --- UPDATED UPLOADER UI ---
# Change the file_uploader line to this:
tm_file = st.file_uploader("Upload Trackman Export", type=["xlsx", "csv"])
