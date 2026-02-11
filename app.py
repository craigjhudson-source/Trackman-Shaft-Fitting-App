import streamlit as st
import pandas as pd
import os

# --- 1. SMART DATA LOADING ---
@st.cache_data
def load_data():
    # These are the exact filenames from your data set
    # Note: If your environment doesn't show these in the 'root', you must upload them!
    SHAFT_FILE = "Trackman testing data for colab 2/10/26 - Shafts.csv"
    FITTING_FILE = "Trackman testing data for colab 2/10/26 - Fittings.csv"
    
    # Fallback names in case you rename the files to be simpler
    fallback_shaft = "Shafts.csv"
    fallback_fitting = "Fittings.csv"

    s_path = SHAFT_FILE if os.path.exists(SHAFT_FILE) else (fallback_shaft if os.path.exists(fallback_shaft) else None)
    f_path = FITTING_FILE if os.path.exists(FITTING_FILE) else (fallback_fitting if os.path.exists(fallback_fitting) else None)

    if not s_path or not f_path:
        # This error helps you debug by showing exactly what files the app can see
        found = os.listdir('.')
        raise FileNotFoundError(f"CSV Files not found in directory. Current files: {found}")

    df_shafts = pd.read_csv(s_path)
    df_fittings = pd.read_csv(f_path)
    return df_shafts, df_fittings

# --- 2. APP CONFIG ---
st.set_page_config(page_title="Shaft Optimizer Pro", layout="wide")

try:
    df_shafts, df_fittings = load_data()
    # Clean up empty rows from Google Sheets exports
    df_fittings = df_fittings.dropna(subset=['Name', 'Current 6i Carry'])
except Exception as e:
    st.error("⚠️ FILE NOT FOUND IN REPOSITORY")
    st.info(f"**Action Required:** You must upload your CSV files to your GitHub or Streamlit folder. {e}")
    st.stop()

# --- 3. PLAYER SELECTION ---
st.title("⛳ Precision Shaft Optimizer")

player_names = df_fittings['Name'].unique().tolist()
selected_player = st.selectbox("Select Player Profile", player_names)
p_data = df_fittings[df_fittings['Name'] == selected_player].iloc[0]

# --- 4. INPUTS (Mapping to your Fittings.csv columns) ---
col1, col2, col3 = st.columns(3)
with col1:
    carry = st.number_input("6-Iron Carry (yards)", value=float(p_data['Current 6i Carry']))
with col2:
    miss = st.selectbox("Primary Miss", ["Hook", "Slice", "Push", "Pull", "Straight"], 
                        index=["Hook", "Slice", "Push", "Pull", "Straight"].index(p_data['Primary Miss']))
with col3:
    target_flight = st.selectbox("Target Flight", ["Low", "Mid-Low", "Mid", "Mid-High", "High"],
                                index=["Low", "Mid-Low", "Mid", "Mid-High", "High"].index(p_data['Target Flight']))

# --- 5. THE OPTIMIZATION ENGINE ---
df_s = df_shafts.copy()

# Target Mapping Logic
# Craig carries 195, so we target the stiffest FlexScore (10.0)
target_flex = 10.0 if carry >= 195 else 8.5 if carry > 180 else 7.0
target_launch = 2.0 if miss == "Hook" else 5.0

# 1. Base Penalty (Distance from targets)
df_s['Penalty'] = (abs(df_s['FlexScore'] - target_flex) * 30) + \
                  (abs(df_s['LaunchScore'] - target_launch) * 20)

# 2. High Speed & Stability Logic (The Craig Hudson Rules)
if carry >= 190:
    # Prefer Heavy (130g+)
    df_s.loc[df_s['Weight (g)'] < 120, 'Penalty'] += 400
    # Tip Stability: We now know KBS Tour X is 10.0. 
    # We penalize tips <= 10.0 for elite speed to prevent face-closure.
    df_s.loc[df_s['EI_Tip'] <= 10.0, 'Penalty'] += 250

if miss == "Hook":
    # Anti-Hook: Prioritize Low Torque
    df_s['Penalty'] += (df_s['Torque'] * 120) 
    # Reward ultra-stiff tips (Project X/DG are 12.0)
    df_s.loc[df_s['EI_Tip'] >= 12.0, 'Penalty'] -= 100

# 3. FITTER'S NOTES GENERATOR
def get_fitter_notes(row):
    notes = []
    if row['EI_Tip'] >= 12.0: notes.append("Reinforced Tip (Anti-Hook)")
    if row['Torque'] <= 1.3: notes.append("Low-Twist Control")
    if row['Weight (g)'] >= 130: notes.append("Heavy Tempo Control")
    if row['StabilityIndex'] >= 8.5: notes.append("Tour-Grade Stability")
    
    # Note for the KBS if it shows up
    if row['EI_Tip'] <= 10.0 and carry > 190: 
        notes.append("Active Tip (Potential Draw Bias)")
        
    return " | ".join(notes) if notes else "Balanced Profile"

df_s['Fitters Note'] = df_s.apply(get_fitter_notes, axis=1)

# 4. FINAL SORT
# Sort by Penalty (low to high), then FlexScore (high to low)
recommendations = df_s.sort_values(['Penalty', 'FlexScore'], ascending=[True, False]).head(5)

# --- 6. DISPLAY RESULTS ---
st.divider()
st.subheader(f"Top Blueprints for {selected_player}")

# Informational insight for High Speed Hookers
if "Hook" in miss and carry >= 190:
    st.warning("⚠️ **Stability Alert:** Because you carry 190+ with a hook miss, we are prioritizing shafts with an **EI Tip of 12.0** and **Torque below 1.5** to keep the face from closing too early.")

display_cols = ['Brand', 'Model', 'Flex', 'Weight (g)', 'EI_Tip', 'Torque', 'Fitters Note']
st.dataframe(recommendations[display_cols], use_container_width=True)

# Comparison Visualization
st.write("### Stability Analysis: Tip Stiffness vs. Overall Stability")
st.scatter_chart(data=recommendations, x="EI_Tip", y="StabilityIndex", color="Model")
