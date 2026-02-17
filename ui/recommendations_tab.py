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


def _fmt_flight_line(ans: Dict[str, Any]) -> str:
    """
    Sheet truth:
      Q16_1 = Current Flight
      Q16_2 = Are you happy with your current flight? (Yes/No/Unsure)
      Q16_3 = If not, do you want it higher or lower?
    """
    cur = str(ans.get("Q16_1", "")).strip()
    happy = str(ans.get("Q16_2", "")).strip()
    change = str(ans.get("Q16_3", "")).strip()

    if not cur and not happy and not change:
        return ""

    # If they are unhappy (No/Unsure), show desired change
    if happy.lower() in {"no", "unsure"} and change:
        # ex: "Mid (No) → Higher"
        if cur:
            return f"{cur} ({happy}) → {change}"
        return f"{happy} → {change}"

    # Otherwise just show current + happy
    if cur and happy:
        return f"{cur} ({happy})"
    return cur or happy


def _fmt_feel_line(ans: Dict[str, Any]) -> str:
    """
    Sheet truth:
      Q19_1 = Current Shaft Feel
      Q19_2 = Are you happy with your current feel? (Yes/No/Unsure)
      Q19_3 = If not, what do you want it to feel like?
    """
    cur = str(ans.get("Q19_1", "")).strip()
    happy = str(ans.get("Q19_2", "")).strip()
    target = str(ans.get("Q19_3", "")).strip()

    if not cur and not happy and not target:
        return ""

    if happy.lower() in {"no", "unsure"} and target:
        if cur:
            return f"{cur} ({happy}) → {target}"
        return f"{happy} → {target}"

    if cur and happy:
        return f"{cur} ({happy})"
    return cur or happy


def render_recommendations_tab(
    *,
    p_name: str,
    p_email: str,
    ans: Dict[str, Any],
    all_winners: Dict[str, pd.DataFrame],
    verdicts: Dict[str, str],
    environment: str,
) -> None:
    flight_line = _fmt_flight_line(ans)
    feel_line = _fmt_feel_line(ans)

    # Header bar
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

    # Winner summary (if available)
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

    # ---------------- PDF controls ----------------
    st.subheader("📄 PDF Report")

    if not _winner_ready():
        st.warning(
            "PDF is available **after** you pick a winner in **🧪 Trackman Lab** "
            "(or Phase 6 notes exist)."
        )
        return

    # Generate PDF (always allowed once winner exists)
    if st.button("Generate PDF", type="primary"):
        with st.spinner("Generating PDF..."):
            pdf_bytes = create_pdf_bytes(
                p_name,
                all_winners,
                ans,
                verdicts,
                phase6_recs=st.session_state.get("phase6_recs", None),
                environment=environment,
            )
        st.download_button(
            label="Download PDF",
            data=pdf_bytes,
            file_name=f"Report_{p_name}.pdf",
            mime="application/pdf",
        )

    st.divider()

    # Send PDF (only if email provided)
    if not p_email:
        st.info("Add the player's email in the interview to enable **Send PDF**.")
        return

    if st.session_state.get("email_sent", False):
        st.success(f"📬 PDF already sent to {p_email}.")
        return

    if st.button(f"Send PDF to {p_email}"):
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
