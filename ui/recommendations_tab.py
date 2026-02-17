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
    if df is None or df.empty:
        return pd.DataFrame()

    d = df.copy()
    if "ID" not in d.columns:
        try:
            d.insert(0, "ID", [str(x).strip() for x in d.index.tolist()])
        except Exception:
            pass
    d = d.reset_index(drop=True)

    cols = list(d.columns)
    if "ID" in cols:
        cols = ["ID"] + [c for c in cols if c != "ID"]
        d = d[cols]

    return d


def _get_goal_rankings() -> Optional[Dict[str, Any]]:
    gr = st.session_state.get("goal_rankings", None)
    return gr if isinstance(gr, dict) else None


def _get_goal_recs() -> Optional[Dict[str, Any]]:
    """
    Fallback payload produced by Trackman tab until full goal scoring leaderboard is activated.
    Expected shape (minimum):
      {
        "source": "...",
        "winner_summary": {...},
        "baseline_tag_id": ...,
        "environment": ...,
        "generated_at": ...
      }
    """
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


def _goal_best_to_card(best: Any, goal_name: str, baseline_id: Optional[str]) -> None:
    if best is None:
        return

    if isinstance(best, dict):
        lab = str(best.get("shaft_label", "")).strip()
        sid = str(best.get("shaft_id", "")).strip()
        reasons = best.get("reasons") or []
        g_scores = best.get("goal_scores") or {}
    else:
        lab = str(getattr(best, "shaft_label", "")).strip()
        sid = str(getattr(best, "shaft_id", "")).strip()
        reasons = getattr(best, "reasons", []) or []
        g_scores = getattr(best, "goal_scores", {}) or {}

    g_val = None
    try:
        if isinstance(g_scores, dict):
            g_val = float(g_scores.get(goal_name, 0.0) or 0.0)
    except Exception:
        g_val = None

    baseline_txt = f"(vs baseline {baseline_id})" if baseline_id else "(vs baseline)"

    st.markdown(f"**{goal_name}** {baseline_txt}")
    st.write(f"**{lab}**  (ID {sid})")
    if g_val is not None:
        st.caption(f"Goal score: {g_val:.2f}")
    if reasons:
        for b in reasons[:3]:
            st.write(f"- {b}")


def _refresh_controls() -> None:
    """
    Refresh button + optional auto-refresh signaling based on Trackman updates.
    """
    c1, c2, c3 = st.columns([1, 1, 3])

    # Manual refresh
    if c1.button("🔄 Refresh Recommendations"):
        st.rerun()

    # Show last Trackman update if available
    last = st.session_state.get("tm_last_update", "")
    if last:
        c3.caption(f"Last Trackman update: {last}")

    # Optional: auto-rerun once when Trackman version changes
    auto = c2.checkbox("Auto-refresh", value=True)
    if auto:
        current_v = int(st.session_state.get("tm_data_version", 0) or 0)
        seen_v = int(st.session_state.get("recs_seen_tm_version", -1) or -1)

        # If Trackman data changed since last time this tab ran, rerun once.
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

    top_by_goal = gr.get("top_by_goal", {}) if isinstance(gr.get("top_by_goal", {}), dict) else {}
    if top_by_goal:
        st.markdown("#### Best shaft by goal")
        gcols = st.columns(2)
        items = list(top_by_goal.items())
        for i, (goal_name, best) in enumerate(items):
            with gcols[0] if i % 2 == 0 else gcols[1]:
                _goal_best_to_card(best, goal_name, baseline_id)

    st.markdown("#### Goal Scorecard Leaderboard")
    rows = [_result_to_row(r) for r in results[:8]]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()


def _render_goal_based_from_goal_recs(goal_recs: Dict[str, Any]) -> None:
    """
    Fallback rendering: show at least the Trackman winner and context.
    """
    ws = goal_recs.get("winner_summary", None)
    baseline_tag_id = goal_recs.get("baseline_tag_id", None)
    env = goal_recs.get("environment", None)
    ts = goal_recs.get("generated_at", None)

    st.subheader("🎯 Goal-Based Recommendations (from Trackman Lab)")
    st.caption("Fallback mode (goal scoring leaderboard not yet activated).")

    meta_bits: List[str] = []
    if baseline_tag_id is not None and str(baseline_tag_id).strip():
        meta_bits.append(f"Baseline: {baseline_tag_id}")
    if env:
        meta_bits.append(f"Env: {env}")
    if ts:
        meta_bits.append(f"Updated: {ts}")
    if meta_bits:
        st.caption(" • ".join(meta_bits))

    if isinstance(ws, dict):
        headline = ws.get("headline") or "Best pick"
        shaft_label = ws.get("shaft_label") or "Winner selected"
        explain = ws.get("explain") or ""
        st.success(f"**{headline}:** {shaft_label}")
        if explain:
            st.caption(explain)
    else:
        st.info("Trackman winner is available but winner_summary payload is missing.")

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
    # Refresh controls at the top
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

    if gr and gr.get("results"):
        _render_goal_based_from_goal_rankings(gr)
    elif goal_recs and isinstance(goal_recs.get("winner_summary", None), dict):
        _render_goal_based_from_goal_recs(goal_recs)
    else:
        st.info(
            "Goal-based recommendations will appear here after you upload Trackman data in **🧪 Trackman Lab** "
            "and click **➕ Add** at least once."
        )
        st.divider()

    # Winner summary (still shown separately for now)
    ws = st.session_state.get("winner_summary", None)
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
                st.table(_table_with_id(all_winners[cat]))
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
