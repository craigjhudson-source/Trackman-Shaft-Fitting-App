# ui/recommendations_tab.py
from __future__ import annotations

from typing import Any, Dict, Optional, List, Tuple

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


def _refresh_controls() -> None:
    """
    Refresh button + optional auto-refresh signaling based on Trackman updates.
    """
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


def _get_goal_rankings() -> Optional[Dict[str, Any]]:
    gr = st.session_state.get("goal_rankings", None)
    return gr if isinstance(gr, dict) else None


def _baseline_logged() -> bool:
    """
    True when we have Trackman lab rows AND baseline appears to be present.
    (Prevents showing big “old” interview buckets until baseline exists.)
    """
    lab = st.session_state.get("tm_lab_data", None)
    if not isinstance(lab, list) or len(lab) == 0:
        return False

    baseline_id = st.session_state.get("baseline_tag_id", None)
    if baseline_id is None:
        return False

    try:
        b = str(baseline_id).strip()
        if not b:
            return False
        df = pd.DataFrame(lab)
        if df.empty:
            return False
        if "Shaft ID" in df.columns:
            return (df["Shaft ID"].astype(str).str.strip() == b).any()
        # If we can’t verify Shaft ID, still consider “some lab exists”
        return True
    except Exception:
        return True


def _extract_id_series(d: pd.DataFrame) -> Optional[pd.Series]:
    """
    Returns a best-effort ID series from a DF.
    Priority:
      1) "ID"
      2) common variants: "Shaft ID", "shaft_id", "shaftId"
      3) index only if it's clearly not a default RangeIndex
    """
    if d is None or d.empty:
        return None

    cols = [str(c) for c in d.columns]
    if "ID" in cols:
        return d["ID"].astype(str).str.strip()

    for k in ["Shaft ID", "shaft_id", "shaftId", "ShaftId"]:
        if k in cols:
            return d[k].astype(str).str.strip()

    # Only use index if it doesn't look like a default 0..N RangeIndex
    try:
        if isinstance(d.index, pd.RangeIndex):
            return None
        idx = pd.Series([str(x).strip() for x in d.index.tolist()])
        # if most are numeric 0..N-1, it's probably not a real ID
        numeric = pd.to_numeric(idx, errors="coerce")
        if numeric.notna().mean() > 0.8:
            # still might be real IDs, but default row-ish IDs are common—avoid
            return None
        return idx
    except Exception:
        return None


def _table_with_id(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensures a stable "ID" column for display. Avoids falling back to row numbers
    when an ID-like column exists.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    d = df.copy()

    id_series = _extract_id_series(d)
    if id_series is not None:
        d = d.copy()
        d.insert(0, "ID", id_series.values)
        # Remove duplicate ID-like columns if present
        for k in ["Shaft ID", "shaft_id", "shaftId", "ShaftId"]:
            if k in d.columns:
                d = d.drop(columns=[k], errors="ignore")

    # If we still don't have ID, leave it out (better than wrong row numbers)
    if "ID" in d.columns:
        cols = ["ID"] + [c for c in d.columns if c != "ID"]
        d = d[cols]

    # Always hide index in Streamlit tables
    d = d.reset_index(drop=True)
    return d


def _gamer_row(ans: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simple “Gamer” display row (ID may be unknown here, but this keeps the UI honest).
    """
    brand = str(ans.get("Q10", "")).strip()
    model = str(ans.get("Q12", "")).strip()
    flex = str(ans.get("Q11", "")).strip()
    wt = str(ans.get("Q14", "")).strip()  # not perfect, but better than blank in UI

    label = " ".join([x for x in [brand, model] if x]).strip() or "Current Gamer"
    return {
        "ID": "GAMER",
        "Brand": brand or "—",
        "Model": model or label,
        "Flex": flex or "—",
        "Weight (g)": wt or "—",
    }


def _pick_interview_short_list(
    all_winners: Dict[str, pd.DataFrame],
    max_additional: int = 3,
) -> pd.DataFrame:
    """
    Returns 2–3 unique shafts from the existing interview winners, without showing
    the full legacy 4 tables.
    """
    picks: List[pd.DataFrame] = []
    seen: set = set()

    # Prefer Balanced first, then Stability, then Launch
    order = ["Balanced", "Maximum Stability", "Launch & Height", "Feel & Smoothness"]
    for key in order:
        df = all_winners.get(key, None)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue

        t = _table_with_id(df)
        if t.empty:
            continue

        # take up to 1 per bucket to keep it short
        r = t.iloc[[0]].copy()
        sid = str(r.iloc[0].get("ID", "")).strip()
        if sid and sid in seen:
            continue
        if sid:
            seen.add(sid)
        picks.append(r)

        if len(picks) >= max_additional:
            break

    if not picks:
        return pd.DataFrame()

    out = pd.concat(picks, axis=0, ignore_index=True)
    # Keep only common columns if present
    keep = [c for c in ["ID", "Brand", "Model", "Flex", "Weight (g)"] if c in out.columns]
    return out[keep] if keep else out


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


def _next_round_from_goal_rankings(gr: Dict[str, Any], max_n: int = 3) -> List[Dict[str, Any]]:
    """
    Suggest next shafts to test after the first round:
    - pulls from goal_rankings results
    - excludes baseline
    """
    baseline_id = str(gr.get("baseline_shaft_id", "") or "").strip()
    results = gr.get("results", [])
    out: List[Dict[str, Any]] = []

    for r in results or []:
        row = _result_to_row(r)
        sid = str(row.get("Shaft ID", "")).strip()
        if not sid:
            continue
        if baseline_id and sid == baseline_id:
            continue
        out.append(row)
        if len(out) >= max_n:
            break

    return out


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
    if gr and gr.get("results"):
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

        # Next round list (this is what you asked for: “after first round…”)
        next_round = _next_round_from_goal_rankings(gr, max_n=3)
        if next_round:
            st.subheader("🧪 Next Round to Test (after first round)")
            st.caption("These are the next shafts to test to chase your stated goal/flight change.")
            st.dataframe(pd.DataFrame(next_round), use_container_width=True, hide_index=True)

        st.divider()
    else:
        st.info(
            "Goal-based recommendations will appear here after you upload Trackman data in **🧪 Trackman Lab** "
            "and click **➕ Add** at least once (and the goal scorer writes `goal_rankings`)."
        )
        st.divider()

    # Winner summary (even if goal_rankings missing)
    ws = st.session_state.get("winner_summary", None)
    if isinstance(ws, dict) and (ws.get("shaft_label") or ws.get("explain")):
        headline = ws.get("headline") or "Tour Proven Winner"
        shaft_label = ws.get("shaft_label") or "Winner selected"
        explain = ws.get("explain") or ""

        st.subheader("🏆 Winner (from Trackman Lab Intelligence)")
        st.success(f"**{headline}:** {shaft_label}")
        if explain:
            st.caption(explain)

    # ---------------- Interview Section (Slim + modern) ----------------
    if not _baseline_logged():
        st.subheader("🧠 Pre-Test Short List (before baseline testing is logged)")
        st.caption(
            "We keep this light on purpose. Once you log your baseline in Trackman Lab, "
            "Trackman/goal scoring takes over."
        )

        gamer = pd.DataFrame([_gamer_row(ans)])
        shortlist = _pick_interview_short_list(all_winners, max_additional=3)

        combined = gamer
        if isinstance(shortlist, pd.DataFrame) and not shortlist.empty:
            combined = pd.concat([gamer, shortlist], axis=0, ignore_index=True)

        st.dataframe(_table_with_id(combined), use_container_width=True, hide_index=True)

        with st.expander("Legacy interview buckets (optional)", expanded=False):
            st.caption("These are kept for reference, but are no longer the main UI once Trackman baseline exists.")
            cats = [
                ("Balanced", "⚖️ Balanced"),
                ("Maximum Stability", "🛡️ Stability"),
                ("Launch & Height", "🚀 Launch"),
                ("Feel & Smoothness", "☁️ Feel"),
            ]
            col1, col2 = st.columns(2)
            v_items = list(verdicts.items())

            for i, (cat, c_name) in enumerate(cats):
                with col1 if i < 2 else col2:
                    st.markdown(f"### {c_name}")
                    if cat in all_winners and isinstance(all_winners[cat], pd.DataFrame):
                        st.dataframe(_table_with_id(all_winners[cat]), use_container_width=True, hide_index=True)
                        blurb = v_items[i][1] if i < len(v_items) else "Optimized."
                        st.markdown(
                            f"<div class='verdict-text'><b>Verdict:</b> {blurb}</div>",
                            unsafe_allow_html=True,
                        )

        st.divider()
    else:
        st.subheader("🧠 Interview Starting Point (reference only)")
        st.caption("Baseline is logged — Trackman/goal scoring should be your main decision driver now.")
        with st.expander("Show interview buckets", expanded=False):
            cats = [
                ("Balanced", "⚖️ Balanced"),
                ("Maximum Stability", "🛡️ Stability"),
                ("Launch & Height", "🚀 Launch"),
                ("Feel & Smoothness", "☁️ Feel"),
            ]
            col1, col2 = st.columns(2)
            v_items = list(verdicts.items())
            for i, (cat, c_name) in enumerate(cats):
                with col1 if i < 2 else col2:
                    st.markdown(f"### {c_name}")
                    if cat in all_winners and isinstance(all_winners[cat], pd.DataFrame):
                        st.dataframe(_table_with_id(all_winners[cat]), use_container_width=True, hide_index=True)
                        blurb = v_items[i][1] if i < len(v_items) else "Optimized."
                        st.markdown(
                            f"<div class='verdict-text'><b>Verdict:</b> {blurb}</div>",
                            unsafe_allow_html=True,
                        )

        st.divider()

    # ---------------- PDF sending ----------------
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
