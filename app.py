import streamlit as st
import pandas as pd
import numpy as np

# --- 1. DATA LOADING ---
@st.cache_data
def load_data():
    # Ensure these filenames match your uploaded CSV files exactly
    df_shafts = pd.read_csv('Trackman testing data for colab 2/10/26 - Shafts.csv')
    df_fittings = pd.read_csv('Trackman testing data for colab 2/10/26 - Fittings.csv')
    return df_shafts, df_fittings

try:
    df_shafts, df_fittings = load_data()
except Exception as e:
    st.error(f"Error loading CSV files: {e}")
    st.stop()

# --- 2. UI HEADER ---
st.title("⛳ Precision Shaft Optimizer")
st.markdown("### Advanced Stability Engine v2.1")

# --- 3. SIDEBAR / INPUTS ---
with st.sidebar:
    st.header("Player Profile")
    # Pulling dynamic name list from your Fittings.csv
    player_names = df_fittings['Name'].unique().tolist()
    selected_player = st.selectbox("Select Player", player_names)
    
    # Get player specific data
    p_data = df_fittings[df_fittings['Name'] == selected_player].iloc[0]
    
    carry = st.number_input("6-Iron Carry (yards)", value=float(p_data['Carry']))
    miss = st.selectbox("Primary Miss", ["Hook", "Slice", "Push", "Pull", "Straight"], 
                        index=["Hook", "Slice", "Push", "Pull", "Straight"].index(p_data['Miss']))
    
    st.divider()
    st.write(f"**Current Iron:** {p_data['CurrentIron']}")
    st.write(f"**Current Shaft:** {p_data['CurrentShaft']}")

# --- 4. TARGET MAPPING LOGIC ---
# Converting categorical launch/spin needs to numerical scores
tf = 8.0 if carry > 185 else 6.0  # Target Flex Score
tl = 2.0 if "Hook" in miss else 5.0  # Target Launch (Lower for hooks)

# --- 5. THE ENGINE ---
df_s = df_shafts.copy()

# Ensure numeric types for calculation
cols_to_fix = ['EI_Tip', 'StabilityIndex', 'Torque', 'Weight (g)', 'FlexScore', 'LaunchScore']
for col in cols_to_fix:
    df_s[col] = pd.to_numeric(df_s[col], errors='coerce')

# 1. Baseline Penalty (Flex & Launch)
df_s['Penalty'] = (abs(df_s['FlexScore'] - tf) * 30) + (abs(df_s['LaunchScore'] - tl) * 20)

# 2. High Speed & Hook Logic
if carry >= 190:
    # Penalize light shafts and soft tips for elite speeds
    df_s.loc[df_s['Weight (g)'] < 115, 'Penalty'] += 500 
    df_s.loc[df_s['EI_Tip'] < 11.0, 'Penalty'] += 250
    df_s.loc[df_s['StabilityIndex'] < 7.5, 'Penalty'] += 200

if "Hook" in miss:
    # Higher torque increases penalty; high EI_Tip reduces it
    df_s['Penalty'] += (df_s['Torque'] * 100) 
    df_s.loc[df_s['EI_Tip'] >= 12.0, 'Penalty'] -= 50

# 3. GENERATE DYNAMIC FITTER'S NOTES
def generate_notes(row):
    notes = []
    # Using your actual data: 12.0 is the reinforced threshold
    if row['EI_Tip'] >= 12.0: 
        notes.append("Reinforced Tip (Anti-Hook)")
    elif row['EI_Tip'] <= 10.0 and carry > 190:
        notes.append("Active Tip (Potential Draw Bias)")
        
    if row['StabilityIndex'] >= 8.5: notes.append("Tour-Grade Stability")
    if row['Torque'] <= 1.3: notes.append("Low-Twist Face Control")
    if row['Weight (g)'] >= 130: notes.append("Heavy Tempo Control")
    
    return " | ".join(notes) if notes else "Balanced Profile Profile"

df_s['Fitters Note'] = df_s.apply(generate_notes, axis=1)

# 4. FINAL SORT
# Sort by Penalty (asc), then FlexScore (desc) to ensure 6.5 > 6.0 for fast players
recs = df_s.sort_values(['Penalty', 'FlexScore', 'StabilityIndex'], 
                       ascending=[True, False, False]).head(5)

# --- 6. DISPLAY RESULTS ---
st.divider()
st.subheader(f"🚀 Recommended Blueprints for {selected_player}")

# Informational insight
if "Hook" in miss and carry > 185:
    st.info("💡 **Fitter Insight:** High carry + Hook miss requires an EI_Tip $\geq 12.0$ and Torque $\leq 1.6$ to stabilize the face through impact.")

# The Output Table
display_cols = ['Brand', 'Model', 'Flex', 'Weight (g)', 'Launch', 'Spin', 'Fitters Note']
st.table(recs[display_cols])

# --- 7. COMPARISON CHART ---
st.write("### Stability Comparison (Stability Index vs Tip Stiffness)")
st.scatter_chart(data=recs, x="EI_Tip", y="StabilityIndex", color="Model")
