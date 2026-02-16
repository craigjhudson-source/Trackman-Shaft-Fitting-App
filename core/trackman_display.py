import pandas as pd
import streamlit as st

KEY_COLS = [
    "Date",
    "Club",
    "ShaftTag",
    "Club Speed [mph]",
    "Ball Speed [mph]",
    "Smash Factor []",
    "Launch Angle [deg]",
    "Spin Rate [rpm]",
    "Carry Flat - Length [yds]",
    "Carry Flat - Side [yds]",
]

RENAME_UI = {
    "Club Speed [mph]": "Club Speed",
    "Ball Speed [mph]": "Ball Speed",
    "Smash Factor []": "Smash",
    "Launch Angle [deg]": "Launch",
    "Spin Rate [rpm]": "Spin",
    "Carry Flat - Length [yds]": "Carry",
    "Carry Flat - Side [yds]": "Offline",
}

def _metric_med_sd(df: pd.DataFrame, col: str):
    if col not in df.columns:
        return None
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.median()), float(s.std(ddof=1)) if len(s) > 1 else 0.0

def render_trackman_session(df: pd.DataFrame):

    st.subheader("Session Summary")

    items = [
        ("Ball Speed", "Ball Speed [mph]", "mph", 1),
        ("Launch", "Launch Angle [deg]", "°", 1),
        ("Spin", "Spin Rate [rpm]", "rpm", 0),
        ("Carry", "Carry Flat - Length [yds]", "yds", 1),
        ("Offline", "Carry Flat - Side [yds]", "yds", 1),
        ("Smash", "Smash Factor []", "", 2),
    ]

    cols = st.columns(len(items))
    for i, (label, colname, unit, dec) in enumerate(items):
        out = _metric_med_sd(df, colname)
        if out is None:
            cols[i].metric(label, "—")
        else:
            m, sd = out
            fmt = f"{{:.{dec}f}}"
            val = fmt.format(m) + (f" {unit}" if unit else "")
            delta = ("± " + fmt.format(sd) + (f" {unit}" if unit else "")) if sd is not None else ""
            cols[i].metric(label, val, delta)

    st.subheader("Shots (Key Metrics)")
    key = [c for c in KEY_COLS if c in df.columns]
    view = df[key].rename(columns=RENAME_UI)

    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        height=360
    )

    with st.expander("Raw Data (Advanced)"):
        st.dataframe(df, use_container_width=True, height=360)
