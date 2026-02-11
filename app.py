import streamlit as st
import pandas as pd
import os

# --- 1. DATA LOADING (Updated Paths) ---
@st.cache_data
def load_data():
    # We use the exact filenames provided in your environment
    shaft_file = 'Trackman testing data for colab 2/10/26 - Shafts.csv'
    fitting_file = 'Trackman testing data for colab 2/10/26 - Fittings.csv'
    
    # Check if the "folder style" name exists, if not, try the local name
    if not os.path.exists(shaft_file):
        shaft_file = 'Shafts.csv'
    if not os.path.exists(fitting_file):
        fitting_file = 'Fittings.csv'

    df_shafts = pd.read_csv(shaft_file)
    df_fittings = pd.read_csv(fitting_file)
    return df_shafts, df_fittings

# --- 2. APP SETUP ---
st.set_page_config(page_title="Shaft Optimizer", layout="wide")

# DEBUGGER IN SIDEBAR (To help you find the right names)
with st.sidebar:
    if st.checkbox("Show File Debugger"):
        st.write("Files found in root:")
        st.write(os.listdir('.'))

try:
    df_shafts, df_fittings = load_data()
    # Clean up empty rows in fittings
    df_fittings = df_fittings.dropna(subset=['Name', 'Current 6i Carry'])
except Exception as e:
    st.error(f"⚠️ Error: {e}")
    st.info("Check the 'File Debugger' in the sidebar to ensure the CSV names match exactly.")
    st.stop()

# --- 3. PLAYER SELECTION ---
st.title("⛳ Precision Shaft Optimizer")

player_names = df_fittings['Name'].unique().tolist()
selected_player = st.selectbox("Select Player Profile", player_names)
p_data = df_fittings[df_fittings['Name'] == selected_player].iloc[0]

# --- 4. INPUTS (Pre-filled from Fittings.csv) ---
col1, col2, col3 = st.columns(3)
with col1:
    carry = st.number_input("6-Iron Carry (yards)", value=float(p_data['Current 6i Carry']))
with col2:
    miss = st.selectbox("Primary Miss", ["Hook", "Slice", "Push", "Pull", "Straight"], 
                        index=["Hook", "Slice", "Push", "Pull", "Straight"].index(p_data['Primary Miss']))
with col3:
    target_flight = st.selectbox("Target Flight", ["Low", "Mid-Low", "Mid", "Mid-High", "High"],
                                index=["Low", "Mid-Low", "Mid", "Mid-High", "High"].index(p_data['Target Flight']))

# --- 5. LOGIC ENGINE ---
df_s = df_shafts.copy()

# Target Mapping (Dynamic)
target_flex = 10.0 if carry > 190 else 8.5 if carry > 180 else 7.0
target_launch = 2.0 if miss == "Hook" else 5.0

# Calculate Penalty Score
df_s['Penalty'] = (abs(df_s['FlexScore'] - target_flex) * 25) + \
                  (abs(df_s['LaunchScore'] - target_launch) * 15)

# Stability Rules for High Speed / Hooks
if carry >= 190:
    df_s.loc[df_s['Weight (g)'] < 120, 'Penalty'] += 200
    df_s.loc[df_s['EI_Tip'] < 11.5, 'Penalty'] += 150 # Corrected: 10.0 tip now penalized for Craig

if miss == "Hook":
    df_s['Penalty'] += (df_s['Torque'] * 100)
    df_s.loc[df_s['EI_Tip'] >= 12.0, 'Penalty'] -= 50 # Bonus for the stiffest tips

# Generate Notes
def get_notes(row):
    notes = []
    if row['EI_Tip'] >= 12.0: notes.append("Reinforced Tip (Anti-Hook)")
    if row['Torque'] <= 1.3: notes.append("Low-Twist Control")
    if row['Weight (g)'] >= 130: notes.append("Heavy Tempo")
    if row['StabilityIndex'] >= 8.5: notes.append("Tour Stability")
    return " | ".join(notes) if notes else "Balanced"

df_s['Fitters Note'] = df_s.apply(get_notes, axis=1)

# Sort: Top matches have lowest penalty, then highest FlexScore
recommendations = df_s.sort_values(['Penalty', 'FlexScore'], ascending=[True, False]).head(5)

# --- 6. DISPLAY ---
st.divider()
st.subheader(f"Top 5 Recommendations for {selected_player}")

# Format the table for display
display_table = recommendations[['Brand', 'Model', 'Flex', 'Weight (g)', 'EI_Tip', 'Torque', 'Fitters Note']]
st.dataframe(display_table, use_container_width=True)

# Comparison Chart
st.write("### Tip Stiffness vs Overall Stability")
st.scatter_chart(data=recommendations, x="EI_Tip", y="StabilityIndex", color="Model")
