# --- 3. UI LAYOUT ---
all_data = get_data_from_gsheet()

if all_data:
    st.title("🇺🇸 Patriot Fitting Engine")
    
    # --- SIDEBAR: THE CONTROL CENTER ---
    with st.sidebar:
        st.header("1. Player Profile")
        player_name = st.text_input("Player Name", "John Doe")
        
        st.header("2. Fitting Priorities")
        feel_label = st.select_slider(
            "Impact of Feel:",
            options=["1 - Low", "2 - Med", "3 - Neutral", "4 - High", "5 - Pure Feel"],
            value="3 - Neutral"
        )
        
        # Manual Overrides for the "Engine"
        st.header("3. Manual Targets")
        # We set these as defaults; Trackman will suggest updates if uploaded
        t_flex = st.number_input("Target FlexScore", value=6.0, step=0.1, help="6.0 = Stiff, 5.0 = Regular")
        t_launch = st.number_input("Target LaunchScore", value=5.0, step=0.5, help="Low number = Low Launch shaft")
        
        st.header("4. Transition/Tempo")
        tempo = st.selectbox("Player Tempo", ["Smooth", "Moderate", "Aggressive/Fast"])

    # --- MAIN COLUMN: DATA & RESULTS ---
    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("📊 Trackman Input")
        tm_file = st.file_uploader("Upload Trackman Export", type=["xlsx", "csv"])
        
        if tm_file:
            stats = process_trackman(tm_file)
            if stats:
                st.metric("Avg Club Speed", f"{stats['speed']:.1f} mph")
                st.metric("Spin Rate", f"{int(stats['spin'])} rpm")
                
                # Logic to suggest changes based on Trackman
                suggested_flex = round((stats['speed'] / 10) - 4.0, 1)
                st.write(f"💡 *Based on speed, we recommend a **{suggested_flex}** FlexScore.*")
                
                if stats['spin'] > 3200:
                    st.warning("⚠️ High Spin detected. Consider dropping Target Launch to 3.0-4.0")

    with col2:
        st.subheader("🏆 Top Shaft Recommendations")
        if st.button("🔥 Run Patriot Analysis"):
            # Scoring Logic
            priority_map = {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0, "5": 5.0}
            feel_val = priority_map.get(feel_label[0], 3.0)
            
            # Flex is weighted heavier if Feel is high
            flex_weight = 40 * (0.5 + (feel_val * 0.2)) 
            
            df_s = all_data['Shafts'].copy()
            
            # THE MATH
            df_s['Penalty'] = df_s.apply(
                lambda r: (abs(pd.to_numeric(r['FlexScore'], errors='coerce') - t_flex) * flex_weight) + 
                          (abs(pd.to_numeric(r['LaunchScore'], errors='coerce') - t_launch) * 20), 
                axis=1
            )
            
            results = df_s.sort_values('Penalty').head(5)
            
            # Visual Table
            st.table(results[['ShaftTag', 'FlexScore', 'LaunchScore', 'Penalty']])
            
            # Summary for the Fitter
            st.info(f"Fitted {player_name} for a {tempo} transition.")
