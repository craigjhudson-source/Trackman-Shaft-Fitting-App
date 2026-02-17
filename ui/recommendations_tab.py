# ui/recommendations_tab.py
from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import streamlit as st

from utils import create_pdf_bytes, send_email_with_pdf


def _winner_ready() -> bool:
    """
    Winner chosen signal:
      - preferred: st.session_state.winner_summary exists
      - fallback: phase6_recs exists
    """
    ws = st.session_state.get("winner_summary", None)
    if isinstance(ws, dict) and (ws.get("shaft_label") or ws.get("explain")):
        return True

    phase6 = st.session_state.get("phase6_recs", None)
    if isinstance(phase6, list) and len(phase6) > 0:
        return True

    return False


def render_recommendations_tab(
    *,
    p_name: str,
    p_email: str,
    ans: Dict[str, Any],
    all_winners: Dict[str, pd.DataFrame],
    verdicts: Dict[str, str],
    environment: str,
) -> None:
    # Header bar
    st.markdown(
        f"""<div class="profile-bar"><div class="profile-grid">
<div><b>CARRY:</b> {ans.get('Q15','')}yd</div>
<div><b>HEAD:</b> {ans.get('Q08','')} {ans.get('Q09','')}</div>
<div><b>CURRENT:</b> {ans.get('Q12','')} ({ans.get('Q11','')})</div>
<div><b>SPECS:</b> {ans.get('Q13','')} L / {ans.get('Q14','')} SW</div>
<div><b>GRIP/BALL:</b> {ans.get('Q06','')}/{ans.get('Q07','')}</div>
<div><b>ENVIRONMENT:</b> {environment}</div>
</div></div>""",
        unsafe_allow_html=True,
    )

    # Show winner summary if we have it
    ws = st.session_state.get("winner_summary", None)
    if isinstance(ws, dict) and (ws.get("shaft_label") or ws.get("explain")):
        headline = ws.get("headline") or "Tour Proven Winner"
        shaft_label = ws.get("shaft_label") or "Winner selected"
        explain = ws.get("explain") or ""

        st.subheader("🏆 Winner (from Trackman Lab)")
        st.success(f"**{headline}:** {shaft_label}")
        if explain:
            st.caption(explain)

    # Predictor buckets
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
            if cat in all_winners:
                st.table(all_winners[cat])
                blurb = v_items[i][1] if i < len(v_items) else "Optimized."
                st.markdown(
                    f"<div class='verdict-text'><b>Verdict:</b> {blurb}</div>",
                    unsafe_allow_html=True,
                )

    st.divider()

    # --- PDF sending flow (explicit) ---
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
    can_send = bool(want_send)

    if st.button("Generate & Send PDF", disabled=not can_send):
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
