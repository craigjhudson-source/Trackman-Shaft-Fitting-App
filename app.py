import streamlit as st
import pandas as pd
import os
import glob

# --- 1. SMART FILE LOADER ---
@st.cache_data
def load_data():
    # This looks for any file in your folder that contains 'Shafts' or 'Fittings'
    # This solves the "File Not Found" error caused by the long Google Sheets names
    shaft_files = glob.glob("*Shafts.csv")
    fitting_files = glob.glob("*Fittings.csv")
    
    if not shaft_files or not fitting_files:
        # Debugging info for the sidebar
        current_files = os.listdir('.')
        st.sidebar.error(f"Missing CSV files! Found: {current_files}")
        st.stop()
        
    df_shafts = pd.read_csv(shaft_files[0])
    df_fittings = pd.read_csv(fitting_files[0])
    
    # Standardize column names (remove whitespace)
    df_shafts.columns = df_shafts.columns.str.strip()
    df_fittings.columns = df_fittings.columns.str.strip()
    
    return df_shafts, df_fittings

# --- 2. CONFIG & THEME ---
st.set_page_config(page_title="Shaft Optimizer", layout="wide")

try:
    df_shafts, df_fittings = load_data()
    # Filter out empty rows from the Google Sheet
    df_fittings = df_fittings.dropna(subset=['Name', 'Current 6i Carry'])
except Exception as e:
    st.error(f"Initialization Error: {e}")
    st.stop()

# --- 3. PLAYER SELECTION ---
st.title("⛳ Precision Shaft Optimizer")
st.markdown("### Stability-First Recommendation Engine")

player_list = df_fittings['Name'].unique().tolist()
selected_name = st.selectbox("Select Player Profile", player_list)
p = df_fittings[df_fittings['Name'] == selected_name].iloc[0]

# --- 4. DATA MAPPING & TARGETS ---
# Inputs pre-filled from the Google Sheet data
col1, col2, col3 = st.columns(3)
with col1:
    carry = st.number_input("6-Iron Carry (yards)", value=float(p['Current 6i Carry']))
with col2:
    miss = st.selectbox("Primary Miss", ["Hook", "Slice", "Push", "Pull", "Straight"], 
                        index=["Hook", "Slice", "Push", "Pull", "Straight"].index(p['Primary Miss']))
with col3:
    target_flight = st.selectbox("Target Flight", ["Low", "Mid-Low", "Mid", "Mid-High", "High"],
                                index=["Low", "Mid-Low", "Mid", "Mid-High", "High"].index(p['Target Flight']))

# Logic Constants (from your Responses/Config logic)
target_flex = 10.0 if carry >= 195 else 8.5 if carry >= 180 else 7.0
flight_map = {"Low": 2.0, "Mid-Low": 3.5, "Mid": 5.0, "Mid-High": 6.5, "High": 8.0}
target_launch = flight_map.get(target_flight, 5.0)

# --- 5. THE OPTIMIZATION ENGINE ---
df_s = df_shafts.copy()

# A. BASE PENALTY (Launch & Flex Match)
df_s['Penalty'] = (abs(df_s['FlexScore'] - target_flex) * 35) + \
                  (abs(df_s['LaunchScore'] - target_launch) * 15)

# B. STABILITY RULES (The "Craig Hudson" Adjustment)
if carry >= 190:
    # 1. Weight Penalty: High speed needs mass for tempo
    df_s.loc[df_s['Weight (g)'] < 120, 'Penalty'] += 500 
    
    # 2. Tip Stiffness (The KBS Fix): 
    # Since KBS Tour X is 10.0 and PX/DG are 12.0, we penalize the 10.0 tip for elite speed.
    df_s.loc[df_s['EI_Tip'] <= 10.5, 'Penalty'] += 300 

if miss == "Hook":
    # 3. Torque Penalty: Lower torque is better for hookers
    df_s['Penalty'] += (df_s['Torque'] * 150)
    
    # 4. Anti-Left Bonus: Reward the ultra-stable 12.0 tips
    df_s.loc[df_s['EI_Tip'] >= 11.5, 'Penalty'] -= 100

# C. GENERATE FITTER NOTES
def get_notes(row):
    notes = []
    if row['EI_Tip'] >= 12.0: notes.append("Reinforced Tip (Anti-Hook)")
    if row['Torque'] <= 1.3: notes.append("Low-Twist Face Control")
    if row['Weight (g)'] >= 130: notes.append("Heavy Tempo Control")
    if row['EI_Tip'] <= 10.0 and carry > 190: notes.append("Active Tip (Potential Draw)")
    return " | ".join(notes) if notes else "Balanced Profile"

df_s['Fitters Note'] = df_s.apply(get_fitter_notes, axis=1)

# D. SORTING
# Lowest penalty first. Break ties with higher FlexScore (stiffer is safer for high speed).
recs = df_s.sort_values(['Penalty', 'FlexScore'], ascending=[True, False]).head(5)

# --- 6. DISPLAY ---
st.divider()
st.subheader(f"Top 5 Recommendations for {selected_name}")

if carry >= 190 and miss == "Hook":
    st.info("💡 **Logic Note:** We are prioritizing shafts with **EI_Tip >= 12.0** and **Low Torque** to stabilize the face through impact for your speed.")

display_df = recs[['Brand', 'Model', 'Flex', 'Weight (g)', 'EI_Tip', 'Torque', 'Fitters Note']]
st.table(display_df)

# CHART
st.write("### Profile Comparison: Tip Stiffness vs Stability Index")
st.scatter_chart(data=recs, x="EI_Tip", y="StabilityIndex", color="Model")
