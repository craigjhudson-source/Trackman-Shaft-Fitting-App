from __future__ import annotations

from typing import Any, Dict, Optional, List, Set, Tuple

import pandas as pd
import streamlit as st

from utils_pdf import create_pdf_bytes
from utils import send_email_with_pdf

from core.pretest_shortlist import build_pretest_shortlist


# -----------------------------
# Utilities
# -----------------------------
def _safe_str(x: Any) -> str:
    try:
        return str(x).strip()
    except Exception:
        return ""


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

        # ✅ If TrackMan data version changed, always rerun when we actually have data (>0).
        # This fixes the "must click refresh after Add" problem when seen_v is still -1.
        if current_v != seen_v:
            st.session_state.recs_seen_tm_version = current_v
            st.session_state.recs_seen_tm_version = current_v

            # Only rerun if TrackMan has been updated/added at least once.
            if current_v > 0:
                st.rerun()

        # Keep the "seen" version in sync even when version is 0 (no lab data yet)
        else:
            st.session_state.recs_seen_tm_version = current_v


# -----------------------------
# Goal payload (canonical)
# -----------------------------
def _get_goal_payload() -> Optional[Dict[str, Any]]:
    gr = st.session_state.get("goal_recommendations", None)
    if isinstance(gr, dict) and gr:
        return gr
    gr2 = st.session_state.get("goal_rankings", None)
    if isinstance(gr2, dict) and gr2:
        return gr2
    gr3 = st.session_state.get("goal_recs", None)
    if isinstance(gr3, dict) and gr3:
        return gr3
    return None


def _tested_shaft_ids() -> Set[str]:
    out: Set[str] = set()
    try:
        lab = st.session_state.get("tm_lab_data", None)
        if not isinstance(lab, list) or len(lab) == 0:
            return out
        df = pd.DataFrame(lab)
        if df.empty:
            return out
        if "Shaft ID" in df.columns:
            vals = df["Shaft ID"].astype(str).str.strip()
            out.update([v for v in vals.tolist() if v])
    except Exception:
        return out
    return out


def _result_to_row(r: Any) -> Dict[str, Any]:
    if r is None:
        return {}
    if isinstance(r, dict):
        return {
            "Shaft ID": _safe_str(r.get("shaft_id", "")) or _safe_str(r.get("Shaft ID", "")),
            "Shaft": _safe_str(r.get("shaft_label", "")) or _safe_str(r.get("Shaft", "")),
            "Score": float(r.get("overall_score", r.get("Score", 0.0)) or 0.0),
            "Why": " | ".join([str(x) for x in (r.get("reasons") or [])][:3]) or _safe_str(r.get("Why", "")),
        }
    return {
        "Shaft ID": _safe_str(getattr(r, "shaft_id", "")),
        "Shaft": _safe_str(getattr(r, "shaft_label", "")),
        "Score": float(getattr(r, "overall_score", 0.0) or 0.0),
        "Why": " | ".join([str(x) for x in (getattr(r, "reasons", None) or [])][:3]),
    }


def _goal_best_to_card(best: Any, goal_name: str, baseline_id: Optional[str]) -> None:
    if best is None:
        return

    if isinstance(best, dict):
        lab = _safe_str(best.get("shaft_label", "")) or _safe_str(best.get("Shaft", ""))
        sid = _safe_str(best.get("shaft_id", "")) or _safe_str(best.get("Shaft ID", ""))
        reasons = best.get("reasons") or []
        g_scores = best.get("goal_scores") or {}
    else:
        lab = _safe_str(getattr(best, "shaft_label", ""))
        sid = _safe_str(getattr(best, "shaft_id", ""))
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


def _next_round_from_goal_payload(gr: Dict[str, Any], max_n: int = 3) -> List[Dict[str, Any]]:
    baseline_id = _safe_str(gr.get("baseline_shaft_id", "") or "")
    results = gr.get("results", []) or []

    tested = _tested_shaft_ids()
    if baseline_id:
        tested.add(baseline_id)

    out: List[Dict[str, Any]] = []
    for r in results:
        row = _result_to_row(r)
        sid = _safe_str(row.get("Shaft ID", ""))
        if not sid:
            continue
        if sid in tested:
            continue
        out.append(row)
        if len(out) >= max_n:
            break

    return out


# -----------------------------
# Gamer row (pull weight if possible)
# -----------------------------
def _gamer_identity(ans: Dict[str, Any]) -> Tuple[str, str, str]:
    brand = _safe_str(ans.get("Q10", "")).lower()
    model = _safe_str(ans.get("Q12", "")).lower()
    flex = _safe_str(ans.get("Q11", "")).lower()
    return brand, model, flex


def _lookup_gamer_weight(shafts_df: pd.DataFrame, ans: Dict[str, Any]) -> str:
    if not isinstance(shafts_df, pd.DataFrame) or shafts_df.empty:
        return "—"

    b, m, f = _gamer_identity(ans)
    if not b or not m:
        return "—"

    df = shafts_df.copy()
    for c in ["Brand", "Model", "Flex", "Weight (g)"]:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].astype(str).str.strip()

    hit = df[
        (df["Brand"].str.lower() == b)
        & (df["Model"].str.lower() == m)
        & ((df["Flex"].str.lower() == f) if f else True)
    ]

    if hit.empty and f:
        hit = df[(df["Brand"].str.lower() == b) & (df["Model"].str.lower() == m)]

    if hit.empty:
        return "—"

    w = _safe_str(hit.iloc[0].get("Weight (g)", ""))
    return w if w else "—"


def _gamer_row(ans: Dict[str, Any], shafts_df: pd.DataFrame) -> Dict[str, Any]:
    brand = _safe_str(ans.get("Q10", ""))
    model = _safe_str(ans.get("Q12", ""))
    flex = _safe_str(ans.get("Q11", ""))
    label = " ".join([x for x in [brand, model] if x]).strip() or "Current Gamer"
    weight = _lookup_gamer_weight(shafts_df, ans)

    return {
        "ID": "GAMER",
        "Brand": brand or "—",
        "Model": model or label,
        "Flex": flex or "—",
        "Weight (g)": weight,
    }


def _dedupe_shortlist(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    d = df.copy()
    for c in ["ID", "Brand", "Model", "Flex", "Weight (g)"]:
        if c not in d.columns:
            d[c] = ""
        d[c] = d[c].astype(str).str.strip()

    out_rows = []
    seen: Set[str] = set()

    for _, r in d.iterrows():
        rid = _safe_str(r.get("ID", ""))
        key = (
            rid
            if rid and rid.upper() != "GAMER"
            else f"GAMER|{_safe_str(r.get('Brand',''))}|{_safe_str(r.get('Model',''))}|{_safe_str(r.get('Flex',''))}"
        )
        if key in seen:
            continue
        seen.add(key)
        out_rows.append(
            {
                "ID": rid,
                "Brand": _safe_str(r.get("Brand", "")),
                "Model": _safe_str(r.get("Model", "")),
                "Flex": _safe_str(r.get("Flex", "")),
                "Weight (g)": _safe_str(r.get("Weight (g)", "")),
            }
        )

    return pd.DataFrame(out_rows)


def _get_shafts_df_for_ui() -> pd.DataFrame:
    shafts_df = st.session_state.get("shafts_df_for_ui", None)
    if isinstance(shafts_df, pd.DataFrame) and not shafts_df.empty:
        return shafts_df
    shafts_df = st.session_state.get("all_shafts_df", None)
    if isinstance(shafts_df, pd.DataFrame) and not shafts_df.empty:
        return shafts_df
    return pd.DataFrame()


# -----------------------------
# MAIN RENDER
# -----------------------------
def render_recommendations_tab(
    *,
    p_name: str,
    p_email: str,
    ans: Dict[str, Any],
    all_winners: Dict[str, pd.DataFrame],  # kept only for PDF signature compatibility
    verdicts: Dict[str, str],              # kept only for PDF signature compatibility
    environment: str,
) -> None:
    # ✅ First-load auto-render: single rerun once per fitting
    if not bool(st.session_state.get("recs_autoload_done", False)):
        st.session_state.recs_autoload_done = True
        st.rerun()

    _refresh_controls()

    # Rename display label (keep Q23 key for data contract)
    primary_objective = _safe_str(ans.get("Q23", ""))

    flight_current = _safe_str(ans.get("Q16_1", ""))
    flight_happy = _safe_str(ans.get("Q16_2", ""))
    flight_target = _safe_str(ans.get("Q16_3", ""))

    feel_current = _safe_str(ans.get("Q19_1", ""))
    feel_happy = _safe_str(ans.get("Q19_2", ""))
    feel_target = _safe_str(ans.get("Q19_3", ""))

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
<div><b>PRIMARY PERFORMANCE OBJECTIVE:</b> {primary_objective or "<span class='smallcap'>not answered</span>"}</div>
</div></div>""",
        unsafe_allow_html=True,
    )

    # -----------------------------
    # Post-TrackMan (goal payload)
    # -----------------------------
    gr = _get_goal_payload()
    has_results = isinstance(gr, dict) and isinstance(gr.get("results", None), list) and len(gr.get("results", [])) > 0
    has_winner_only = isinstance(gr, dict) and isinstance(gr.get("winner_summary", None), dict)

    if has_results or has_winner_only:
        st.subheader("🎯 Goal-Based Recommendations (post-TrackMan)")

        baseline_id = None
        if isinstance(gr, dict):
            baseline_id = (
                gr.get("baseline_shaft_id", None)
                or gr.get("baseline_tag_id", None)
                or st.session_state.get("baseline_tag_id", None)
            )

        if has_results:
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
                        _goal_best_to_card(best, goal_name, str(baseline_id) if baseline_id else None)

            st.markdown("#### Goal Scorecard Leaderboard")
            rows = [_result_to_row(r) for r in results[:8]]
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            next_round = _next_round_from_goal_payload(gr, max_n=3)
            st.subheader("🧪 Next Round to Test (after first round)")
            if next_round:
                st.caption("Filtered to avoid repeating shafts already logged in TrackMan Lab.")
                st.dataframe(pd.DataFrame(next_round), use_container_width=True, hide_index=True)
            else:
                st.info("No new shafts to recommend yet — log additional candidates or widen the test set.")

        if (not has_results) and has_winner_only:
            ws = gr.get("winner_summary", {})
            shaft_label = ws.get("shaft_label") or "Winner selected"
            explain = ws.get("explain") or ""
            st.success(f"**Best for your goals:** {shaft_label}")
            if explain:
                st.caption(explain)

        st.divider()
    else:
        st.info(
            "Goal-based recommendations appear after you upload TrackMan data in **🧪 TrackMan Lab** "
            "and click **➕ Add** at least once."
        )
        st.divider()

    # -----------------------------
    # Winner summary (TrackMan intelligence)
    # -----------------------------
    ws = st.session_state.get("winner_summary", None)
    if isinstance(ws, dict) and (ws.get("shaft_label") or ws.get("explain")):
        headline = ws.get("headline") or "Tour Proven Winner"
        shaft_label = ws.get("shaft_label") or "Winner selected"
        explain = ws.get("explain") or ""
        st.subheader("🏆 Winner (from TrackMan Lab Intelligence)")
        st.success(f"**{headline}:** {shaft_label}")
        if explain:
            st.caption(explain)

    # -----------------------------
    # Pre-test shortlist (INTERVIEW-DRIVEN, ALWAYS)
    # -----------------------------
    shafts_df = _get_shafts_df_for_ui()

    st.subheader("🧪 Pre-Test Short List (Interview-Driven)")
    st.caption("Always: Gamer + 2–3 shafts (5 swings each). Driven by Q23 + Q16 constraints. Uses Shafts!ID.")

    gamer = pd.DataFrame([_gamer_row(ans, shafts_df)])

    # Prefer shortlist precomputed in app.py (so we avoid double logic / drift)
    shortlist = st.session_state.get("pretest_shortlist_df", None)
    if isinstance(shortlist, pd.DataFrame) and not shortlist.empty:
        shortlist_df = shortlist.copy()
    else:
        shortlist_df = build_pretest_shortlist(shafts_df, ans, n=3)

    combined = (
        pd.concat([gamer, shortlist_df], axis=0, ignore_index=True)
        if isinstance(shortlist_df, pd.DataFrame) and not shortlist_df.empty
        else gamer
    )
    combined = _dedupe_shortlist(combined)

    st.dataframe(combined, use_container_width=True, hide_index=True)

    st.divider()

    # -----------------------------
    # PDF sending (still uses legacy signature for now)
    # -----------------------------
    st.subheader("📄 Send PDF Report")

    if not p_email:
        st.info("Add the player's email in the interview to enable PDF sending.")
        return

    if st.session_state.get("email_sent", False):
        st.success(f"📬 PDF already sent to {p_email}.")
        return

    if not _winner_ready():
        st.warning(
            "PDF sending is enabled **after** you choose a winner in **🧪 TrackMan Lab**.\n\n"
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
