import streamlit as st
import pandas as pd
import os

# --- 1. DATA LOADING (SMART PATHING) ---
@st.cache_data
def load_data():
    # These are the exact names from your root folder
    SHAFT_FILE = "Trackman testing data for colab 2/10/26 - Shafts.csv"
    FITTING_FILE = "Trackman testing data for colab 2/10/26 - Fittings.csv"
    
    # Fallback names in case you rename them later
    fallback_shaft = "Shafts.csv"
    fallback_fitting = "Fittings.csv"

    # Select the correct path for Shafts
    s_path = SHAFT_FILE if os.path.exists(SHAFT_FILE) else fallback_shaft
    # Select the correct path for Fittings
    f_path = FITTING_FILE if os.path.exists(FITTING_FILE) else fallback_fitting

    if not os.path.exists(s_path) or not os.path.exists(f_path):
        # This will trigger if NEITHER name works
        found_files = os.listdir('.')
        raise FileNotFoundError(f"Could not find CSVs. Root contains: {found_files}")

    df_shafts = pd.read_csv(s_path)
    df_fittings = pd.read_csv(f_path)
    return df_shafts, df_fittings

# --- 2. APP SETUP ---
st.set_page_config(page_title="Shaft Optimizer", layout="wide")

try:
    df_shafts, df_fittings = load_data()
    # Remove empty rows from the Google Sheet export
    df_fittings = df_fittings.dropna(subset=['Name', 'Current 6i Carry'])
except Exception as e:
    st.error("⚠️ File Connection Error")
    st.info(f"Details: {e}")
    st.stop()

# --- 3. PLAYER SELECTION ---
st.title("⛳ Precision Shaft Optimizer")

player_names = df_fittings['Name'].unique().tolist()
selected_player = st.selectbox("Select Player Profile", player_names)
p_data = df_fittings[df_fittings['Name'] == selected_player].iloc[0]

# --- 4. INPUTS (Mapping exactly to your column headers) ---
col1, col2, col3 = st.columns(3)
with col1:
    carry = st.number_input("6-Iron Carry (yards)", value=float(p_data['Current 6i Carry']))
with col2:
    # Match the miss to your Config.csv values
    miss = st.selectbox("Primary Miss", ["Hook", "Slice", "Push", "Pull", "Straight"], 
                        index=["Hook", "Slice", "Push", "Pull", "Straight"].index(p_data['Primary Miss']))
with col3:
    target_flight = st.selectbox("Target Flight", ["Low", "Mid-Low", "Mid", "Mid-High", "High"],
                                index=["Low", "Mid-Low", "Mid", "Mid-High", "High"].index(p_data['Target Flight']))

# --- 5. LOGIC ENGINE ---
df_s = df_shafts.copy()

# Scoring Logic (Craig Hudson Special: 195 carry + Hook miss)
target_flex = 10.0 if carry >= 195 else 8.5 if carry > 180 else 7.0
target_launch = 2.0 if miss == "Hook" else 5.0

# Calculate Penalty
df_s['Penalty'] = (abs(df_s['FlexScore'] - target_flex) * 25) + \
                  (abs(df_s['LaunchScore'] - target_launch) * 15)

# Stability Penalties (The Hook-Killer Logic)
if carry >= 190:
    # 130g+ is preferred; anything under 115g is heavily penalized
    df_s.loc[df_s['Weight (g)'] < 115, 'Penalty'] += 500
    # EI_Tip 10.0 (KBS Tour X) gets a penalty compared to 12.0 (DG/PX)
    df_s.loc[df_s['EI_Tip'] <= 10.0, 'Penalty'] += 200

if miss == "Hook":
    # Prioritize low torque
    df_s['Penalty'] += (df_s['Torque'] * 100)
    # Reward ultra-stiff tips
    df_s.loc[df_s['EI_Tip'] >= 12.0, 'Penalty'] -= 50 

# Generate Notes
def get_notes(row):
    notes = []
    if row['EI_Tip'] >= 12.0: notes.append("Reinforced Tip (Anti-Hook)")
    if row['Torque'] <= 1.3: notes.append("Low-Twist Control")
    if row['Weight (g)'] >= 130: notes.append("Heavy Tempo")
    if row['StabilityIndex'] >= 8.5: notes.append("Tour Stability")
    return " | ".join(notes) if notes else "Balanced Profile"

df_s['Fitters Note'] = df_s.apply(get_notes, axis=1)

# Sort: Lowest Penalty first, then highest FlexScore (to break ties with 6.5 vs 6.0)
recommendations = df_s.sort_values(['Penalty', 'FlexScore'], ascending=[True, False]).head(5)

# --- 6. DISPLAY ---
st.divider()
st.subheader(f"Recommendations for {selected_player}")

display_table = recommendations[['Brand', 'Model', 'Flex', 'Weight (g)', 'EI_Tip', 'Torque', 'Fitters Note']]
st.dataframe(display_table, use_container_width=True)

# Visual Comparison
st.write("### Profile Analysis")
st.scatter_chart(data=recommendations, x="EI_Tip", y="StabilityIndex", color="Model")
