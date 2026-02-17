# ui/recommendations_tab.py
from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import streamlit as st

from utils_pdf import create_pdf_bytes
from utils import send_email_with_pdf


def _winner_ready() -> bool:
    ws = st.session_state.get("winner_summary", None)
    if isinstance(ws, dict) and (ws.get("shaft_label") or ws.get("explain")):
        return True
    phase6 = st.session_state.get("phase6_recs", None)
    return isinstance(phase6, list) and len(phase6) > 0


def _fmt_pref_line(primary: str, followup: str) -> str:
    p = (primary or "").strip()
    f = (followup or "").strip()
    if not p and not f:
        return ""
    if f:
        return f"{p} → {f}" if p else f
    return p


def _table_with_id(df: pd.DataFrame) -> pd.DataFrame:
    """
    Streamlit st.table() shows the DataFrame index as the first column.
    We want that to be the Shaft ID instead (and hide the default row index).
    This works whether the ID is stored as index OR already as a column.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    d = df.copy()

    # If index looks like Shaft IDs and there's no explicit ID column, promote it.
    if "ID" not in d.columns:
        try:
            idx = d.index
            # if most index values are numeric-ish, treat as IDs
            numeric_like = 0
            total = 0
            for v in idx.tolist():
                total += 1
                s = str(v).strip()
                if s and s.replace(".", "", 1).isdigit():
                    numeric_like += 1
            if total > 0 and (numeric_like / total) >= 0.8:
                d.insert(0, "ID", [str(x).strip() for x in d.index.tolist()])
                d = d.reset_index(drop=True)
            else:
                d = d.reset_index(drop=True)
        except Exception:
            d = d.reset_index(drop=True)
    else:
        # Ensure ID is the first column and drop the index
        d = d.reset_index(drop=True)
        cols = list(d.columns)
        if "ID" in cols:
            cols = ["ID"] + [c for c in cols if c != "ID"]
            d = d[cols]

    return d


def render_recommendations_tab(
    *,
    p_name: str,
    p_email: str,
    ans: Dict[str, Any],
    all_winners: Dict[str, pd.DataFrame],
    verdicts: Dict[str, str],
    environment: str,
) -> None:
    # Correct Flight/Feel mapping
    flight_current = str(ans.get("Q16_1", "")).strip()
    flight_happy = str(ans.get("Q16_2", "")).strip()
    flight_target = str(ans.get("Q16_3", "")).strip()

    feel_current = str(ans.get("Q19_1", "")).strip()
    feel_happy = str(ans.get("Q19_2", "")).strip()
    feel_target = str(ans.get("Q19_3", "")).strip()

    flight_line = flight_current
    if flight_happy:
        flight_line = f"{flight_line} ({flight_happy})" if flight_line else f"({flight_happy})"
    if flight_target:
        flight_line = _fmt_pref_line(flight_line, flight_target)

    feel_line = feel_current
    if feel_happy:
        feel_line = f"{feel_line} ({feel_happy})" if feel_line else f"({feel_happy})"
    if feel_target:
        feel_line = _fmt_pref_line(feel_line, feel_target)

    st.markdown(
        f"""<div class="profile-bar"><div class="profile-grid">
<div><b>CARRY:</b> {ans.get('Q15','')}yd</div>
<div><b>HEAD:</b> {ans.get('Q08','')} {ans.get('Q09','')}</div>
<div><b>CURRENT:</b> {ans.get('Q12','')} ({ans.get('Q11','')})</div>
<div><b>SPECS:</b> {ans.get('Q13','')} L / {ans.get('Q14','')} SW</div>
<div><b>GRIP/BALL:</b> {ans.get('Q06','')}/{ans.get('Q07','')}</div>
<div><b>ENVIRONMENT:</b> {environment}</div>
<div><b>FLIGHT:</b> {flight_line or "<span class='smallcap'>not answered</span>"}</div>
<div><b>FEEL:</b> {feel_line or "<span class='smallcap'>not answered</span>"}</div>
</div></div>""",
        unsafe_allow_html=True,
    )

    ws = st.session_state.get("winner_summary", None)
    if isinstance(ws, dict) and (ws.get("shaft_label") or ws.get("explain")):
        headline = ws.get("headline") or "Tour Proven Winner"
        shaft_label = ws.get("shaft_label") or "Winner selected"
        explain = ws.get("explain") or ""

        st.subheader("🏆 Winner (from Trackman Lab)")
        st.success(f"**{headline}:** {shaft_label}")
        if explain:
            st.caption(explain)

    v_items = list(verdicts.items())
    col1, col2 = st.columns(2)
    cats = [
        ("Balanced", "⚖️ Balanced"),
        ("Maximum Stability", "🛡️ Stability"),
        ("Launch & Height", "🚀 Launch"),
        ("Feel & Smoothness", "☁️ Feel"),
    ]

    for i, (cat, c_name) in enumerate(cats):
        with col1 if i < 2 else col2:
            st.subheader(c_name)
            if cat in all_winners and isinstance(all_winners[cat], pd.DataFrame):
                st.table(_table_with_id(all_winners[cat]))
                blurb = v_items[i][1] if i < len(v_items) else "Optimized."
                st.markdown(
                    f"<div class='verdict-text'><b>Verdict:</b> {blurb}</div>",
                    unsafe_allow_html=True,
                )

    st.divider()
    st.subheader("📄 Send PDF Report")

    if not p_email:
        st.info("Add the player's email in the interview to enable PDF sending.")
        return

    if st.session_state.get("email_sent", False):
        st.success(f"📬 PDF already sent to {p_email}.")
        return

    if not _winner_ready():
        st.warning(
            "PDF sending is enabled **after** you choose a winner in **🧪 Trackman Lab**.\n\n"
            "Log swings and let the Intelligence block generate the winner. Then return here to send the PDF."
        )
        return

    want_send = st.checkbox(f"Yes — send the PDF to {p_email}", value=False)
    if st.button("Generate & Send PDF", disabled=not want_send):
        with st.spinner("Generating PDF and sending email..."):
            pdf_bytes = create_pdf_bytes(
                p_name,
                all_winners,
                ans,
                verdicts,
                phase6_recs=st.session_state.get("phase6_recs", None),
                environment=environment,
            )
            ok = send_email_with_pdf(p_email, p_name, pdf_bytes, environment=environment)
            if ok is True:
                st.success(f"📬 Sent to {p_email}!")
                st.session_state.email_sent = True
            else:
                st.error(f"Email failed: {ok}")
