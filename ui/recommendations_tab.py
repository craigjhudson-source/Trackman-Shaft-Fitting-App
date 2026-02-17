# ui/recommendations_tab.py
from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import streamlit as st

from utils import create_pdf_bytes, send_email_with_pdf


def _winner_ready() -> bool:
    """
    "Winner chosen" proxy.
    In your current architecture, the winner selection + Phase 6 notes
    are produced from the Trackman Intelligence block and stored in session_state.

    We treat Phase 6 recs as the signal that a winner decision has occurred.
    """
    phase6 = st.session_state.get("phase6_recs", None)
    if phase6 is None:
        return False
    if isinstance(phase6, list) and len(phase6) == 0:
        return False
    return True


def render_recommendations_tab(
    *,
    p_name: str,
    p_email: str,
    ans: Dict[str, Any],
    all_winners: Dict[str, pd.DataFrame],
    verdicts: Dict[str, str],
    environment: str,
) -> None:
    """
    Renders the Recommendations tab.
    - Shows predictor winners + blurbs
    - Provides an explicit "Send PDF" prompt (no auto-send)
    - Only enables PDF send after Trackman winner/Phase6 is available
    """
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

    winner_ready = _winner_ready()

    if not winner_ready:
        st.warning(
            "PDF sending is enabled **after** a Trackman winner is chosen.\n\n"
            "Go to **🧪 Trackman Lab**, log swings, and let the Intelligence block generate the winner + Phase 6 notes.\n"
            "Then come back here to send the PDF."
        )

    if st.session_state.get("email_sent", False):
        st.success(f"📬 PDF already sent to {p_email}.")
        return

    # Ask if they want to send
    want_send = st.checkbox(f"Yes — send the PDF to {p_email}", value=False)

    # Button is enabled only when:
    # - they checked the box
    # - winner has been chosen (Phase 6 exists)
    can_send = bool(want_send) and bool(winner_ready)

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
