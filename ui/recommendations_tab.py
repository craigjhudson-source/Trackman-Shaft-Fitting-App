# ui/recommendations_tab.py
from __future__ import annotations

from typing import Any, Dict, Optional, List

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
    Ensures an ID column exists and is first.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    d = df.copy()
    if "ID" not in d.columns:
        # last resort fallback
        try:
            d.insert(0, "ID", [str(x).strip() for x in d.index.tolist()])
        except Exception:
            pass

    cols = list(d.columns)
    if "ID" in cols:
        cols = ["ID"] + [c for c in cols if c != "ID"]
        d = d[cols]

    return d.reset_index(drop=True)


def _get_goal_rankings() -> Optional[Dict[str, Any]]:
    gr = st.session_state.get("goal_rankings", None)
    return gr if isinstance(gr, dict) else None


def _get_goal_recs() -> Optional[Dict[str, Any]]:
    gr = st.session_state.get("goal_recs", None)
    return gr if isinstance(gr, dict) else None


def _result_to_row(r: Any) -> Dict[str, Any]:
    if r is None:
        return {}
    if isinstance(r, dict):
        return {
            "Shaft ID": str(r.get("shaft_id", "")).strip(),
            "Shaft": str(r.get("shaft_label", "")).strip(),
            "Score": float(r.get("overall_score", 0.0) or 0.0),
            "Why": " | ".join([str(x) for x in (r.get("reasons") or [])][:3]),
        }
    return {
        "Shaft ID": str(getattr(r, "shaft_id", "")).strip(),
        "Shaft": str(getattr(r, "shaft_label", "")).strip(),
        "Score": float(getattr(r, "overall_score", 0.0) or 0.0),
        "Why": " | ".join([str(x) for x in (getattr(r, "reasons", None) or [])][:3]),
    }


def _refresh_controls() -> None:
    c1, c2, c3 = st.columns([1, 1, 3])

    if c1.button("🔄 Refresh Recommendations"):
        st.rerun()

    last = st.session_state.get("tm_last_update", "")
    if last:
        c3.caption(f"Last Trackman update: {last}")

    auto = c2.checkbox("Auto-refresh", value=True)
    if auto:
        current_v = int(st.session_state.get("tm_data_version", 0) or 0)
        seen_v = int(st.session_state.get("recs_seen_tm_version", -1) or -1)

        if current_v != seen_v:
            st.session_state.recs_seen_tm_version = current_v
            if seen_v != -1:
                st.rerun()
        else:
            st.session_state.recs_seen_tm_version = current_v


def _render_goal_based_from_goal_rankings(gr: Dict[str, Any]) -> None:
    st.subheader("🎯 Goal-Based Recommendations (from Trackman Lab)")

    baseline_id = gr.get("baseline_shaft_id", None)
    results = gr.get("results", [])
    top = results[0] if results else None

    if top is not None:
        row = _result_to_row(top)
        st.success(f"**Best for your goals:** {row.get('Shaft','')}  (ID {row.get('Shaft ID','')})")
        why = row.get("Why", "")
        if why:
            st.caption(why)

    st.markdown("#### Goal Scorecard Leaderboard")
    rows = [_result_to_row(r) for r in results[:8]]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()


def _render_goal_based_from_winner_summary(ws: Dict[str, Any], source_label: str) -> None:
    """
    Fallback: show the current Trackman winner in the goal section,
    until full goal_rankings scoring is wired.
    """
    headline = ws.get("headline") or "Best pick"
    shaft_label = ws.get("shaft_label") or "Winner selected"
    explain = ws.get("explain") or ""

    st.subheader("🎯 Goal-Based Recommendations (from Trackman Lab)")
    st.caption(f"Fallback mode using {source_label} (leaderboard not yet active).")
    st.success(f"**{headline}:** {shaft_label}")
    if explain:
        st.caption(explain)
    st.divider()


def render_recommendations_tab(
    *,
    p_name: str,
    p_email: str,
    ans: Dict[str, Any],
    all_winners: Dict[str, pd.DataFrame],
    verdicts: Dict[str, str],
    environment: str,
) -> None:
    _refresh_controls()

    # Flight/Feel mapping
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

    # ---------------- Goal-based Trackman Recommendations ----------------
    gr = _get_goal_rankings()
    goal_recs = _get_goal_recs()
    ws = st.session_state.get("winner_summary", None)

    if gr and gr.get("results"):
        _render_goal_based_from_goal_rankings(gr)
    elif isinstance(goal_recs, dict) and isinstance(goal_recs.get("winner_summary", None), dict):
        _render_goal_based_from_winner_summary(goal_recs["winner_summary"], "goal_recs")
    elif isinstance(ws, dict) and (ws.get("shaft_label") or ws.get("explain")):
        _render_goal_based_from_winner_summary(ws, "winner_summary")
    else:
        st.info(
            "Goal-based recommendations will appear here after you upload Trackman data in **🧪 Trackman Lab** "
            "and click **➕ Add** at least once."
        )
        st.divider()

    # Winner summary (keep section for now; can remove later)
    if isinstance(ws, dict) and (ws.get("shaft_label") or ws.get("explain")):
        headline = ws.get("headline") or "Tour Proven Winner"
        shaft_label = ws.get("shaft_label") or "Winner selected"
        explain = ws.get("explain") or ""

        st.subheader("🏆 Winner (from Trackman Lab Intelligence)")
        st.success(f"**{headline}:** {shaft_label}")
        if explain:
            st.caption(explain)

    # Interview buckets
    st.subheader("🧠 Interview Starting Point (before Trackman)")
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
            st.markdown(f"### {c_name}")
            if cat in all_winners and isinstance(all_winners[cat], pd.DataFrame):
                d = _table_with_id(all_winners[cat])
                st.dataframe(d, use_container_width=True, hide_index=True)
                blurb = v_items[i][1] if i < len(v_items) else "Optimized."
                st.markdown(
                    f"<div class='verdict-text'><b>Verdict:</b> {blurb}</div>",
                    unsafe_allow_html=True,
                )

    st.divider()

    # PDF sending
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
