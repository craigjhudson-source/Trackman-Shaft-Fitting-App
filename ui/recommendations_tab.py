from __future__ import annotations

from typing import Any, Dict, Optional, List, Set, Tuple

import pandas as pd
import streamlit as st

from utils_pdf import create_pdf_bytes
from utils import send_email_with_pdf


def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return float(default)
        if isinstance(x, str):
            s = x.strip()
            if s == "" or s.lower() in {"nan", "none", "—", "-"}:
                return float(default)
            return float(s)
        return float(x)
    except Exception:
        return float(default)


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
        if current_v != seen_v:
            st.session_state.recs_seen_tm_version = current_v
            if seen_v != -1:
                st.rerun()
        else:
            st.session_state.recs_seen_tm_version = current_v


# -----------------------------
# Goal-based output (NEW canonical)
# -----------------------------
def _get_goal_payload() -> Optional[Dict[str, Any]]:
    """
    Canonical source: st.session_state.goal_recommendations

    Back-compat fallbacks:
      - st.session_state.goal_rankings (older)
      - st.session_state.goal_recs (bridge payload written by Trackman tab)
    """
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


def _baseline_logged() -> bool:
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
        return True
    except Exception:
        return True


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


def _index_is_row_numbers(idx: pd.Index) -> bool:
    """
    True if idx looks like 0..N-1 or 1..N (row-number index).
    """
    try:
        vals = list(idx.tolist())
        if len(vals) == 0:
            return True

        if isinstance(idx, pd.RangeIndex) and idx.start == 0 and idx.step == 1:
            return True

        nums = pd.to_numeric(pd.Series(vals), errors="coerce")
        if nums.isna().any():
            return False

        n = len(vals)
        seq0 = list(range(0, n))
        seq1 = list(range(1, n + 1))

        if nums.astype(int).tolist() == seq0:
            return True
        if nums.astype(int).tolist() == seq1:
            return True

        return False
    except Exception:
        return True


def _extract_id_series(d: pd.DataFrame) -> Optional[pd.Series]:
    """
    Prefer an explicit ID column, otherwise use a non-row-number index
    (even if numeric), because shaft IDs can be numeric.
    """
    if d is None or d.empty:
        return None

    cols = [str(c) for c in d.columns]
    if "ID" in cols:
        return d["ID"].astype(str).str.strip()

    for k in ["Shaft ID", "shaft_id", "shaftId", "ShaftId"]:
        if k in cols:
            return d[k].astype(str).str.strip()

    try:
        if _index_is_row_numbers(d.index):
            return None
        return pd.Series([str(x).strip() for x in d.index.tolist()])
    except Exception:
        return None


def _table_with_id(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    d = df.copy()

    if "ID" in d.columns:
        try:
            d["ID"] = d["ID"].astype(str).str.strip()
            d["ID"] = d["ID"].replace({"nan": "", "None": "", "NaN": ""})
        except Exception:
            pass
        cols = ["ID"] + [c for c in d.columns if c != "ID"]
        return d[cols].reset_index(drop=True)

    id_series = _extract_id_series(d)
    if id_series is not None:
        d = d.copy()
        d.insert(0, "ID", [str(x).strip() for x in id_series.values])
        d["ID"] = d["ID"].astype(str).str.strip().replace({"nan": "", "None": "", "NaN": ""})
        cols = ["ID"] + [c for c in d.columns if c != "ID"]
        return d[cols].reset_index(drop=True)

    return d.reset_index(drop=True)


def _gamer_identity(ans: Dict[str, Any]) -> Tuple[str, str, str]:
    brand = str(ans.get("Q10", "")).strip().lower()
    model = str(ans.get("Q12", "")).strip().lower()
    flex = str(ans.get("Q11", "")).strip().lower()
    return brand, model, flex


def _gamer_row(ans: Dict[str, Any]) -> Dict[str, Any]:
    brand = str(ans.get("Q10", "")).strip()
    model = str(ans.get("Q12", "")).strip()
    flex = str(ans.get("Q11", "")).strip()
    label = " ".join([x for x in [brand, model] if x]).strip() or "Current Gamer"
    return {
        "ID": "GAMER",
        "Brand": brand or "—",
        "Model": model or label,
        "Flex": flex or "—",
        "Weight (g)": "—",
    }


def _goal_key_from_q23(q23: str) -> str:
    s = (q23 or "").strip().lower()

    if any(k in s for k in ["lower", "bring down", "flatten", "reduce height", "too high"]):
        return "lower"
    if any(k in s for k in ["higher", "more height", "launch", "help launch", "get up"]):
        return "higher"
    if any(k in s for k in ["dispersion", "tighten", "accuracy", "left/right", "stable", "stability"]):
        return "stability"
    if any(k in s for k in ["feel", "smooth", "load", "harsh", "boardy"]):
        return "feel"
    return "balanced"


def _bucket_priority_from_q23(q23: str) -> List[str]:
    key = _goal_key_from_q23(q23)

    if key == "higher":
        return ["Launch & Height", "Balanced", "Feel & Smoothness", "Maximum Stability"]
    if key == "lower":
        return ["Maximum Stability", "Balanced", "Feel & Smoothness", "Launch & Height"]
    if key == "stability":
        return ["Maximum Stability", "Balanced", "Launch & Height", "Feel & Smoothness"]
    if key == "feel":
        return ["Feel & Smoothness", "Balanced", "Maximum Stability", "Launch & Height"]
    return ["Balanced", "Maximum Stability", "Launch & Height", "Feel & Smoothness"]


def _normalize_shortlist(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    d = df.copy()

    for c in ["ID", "Brand", "Model", "Flex", "Weight (g)"]:
        if c not in d.columns:
            d[c] = ""
        try:
            d[c] = d[c].astype(str).str.strip()
        except Exception:
            pass

    d["ID"] = d["ID"].replace({"nan": "", "None": "", "NaN": ""})
    keep = ["ID", "Brand", "Model", "Flex", "Weight (g)"]
    return d[keep].reset_index(drop=True)


def _dedupe_shortlist(df: pd.DataFrame, gamer_ans: Dict[str, Any]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    d = _normalize_shortlist(df)
    g_brand, g_model, g_flex = _gamer_identity(gamer_ans)

    def _norm(x: str) -> str:
        return (x or "").strip().lower()

    keep_rows: List[int] = []
    for i, r in d.iterrows():
        rid = _norm(str(r.get("ID", "")))
        b = _norm(str(r.get("Brand", "")))
        m = _norm(str(r.get("Model", "")))
        f = _norm(str(r.get("Flex", "")))

        if rid != "gamer" and b == g_brand and m == g_model and f == g_flex:
            continue
        keep_rows.append(i)

    d = d.iloc[keep_rows].reset_index(drop=True)

    seen_ids: Set[str] = set()
    seen_keys: Set[Tuple[str, str, str]] = set()
    out_rows: List[Dict[str, Any]] = []

    for _, r in d.iterrows():
        rid = str(r.get("ID", "")).strip()
        b = str(r.get("Brand", "")).strip()
        m = str(r.get("Model", "")).strip()
        f = str(r.get("Flex", "")).strip()

        key = (_norm(b), _norm(m), _norm(f))

        if rid and rid.upper() != "GAMER":
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
        else:
            if key in seen_keys:
                continue
            seen_keys.add(key)

        out_rows.append(
            {"ID": rid, "Brand": b, "Model": m, "Flex": f, "Weight (g)": str(r.get("Weight (g)", "")).strip()}
        )

    return pd.DataFrame(out_rows)


def _pick_interview_short_list(
    all_winners: Dict[str, pd.DataFrame],
    ans: Dict[str, Any],
    max_additional: int = 3,
) -> pd.DataFrame:
    picks: List[pd.DataFrame] = []
    used: Set[str] = set()

    priorities = _bucket_priority_from_q23(str(ans.get("Q23", "")).strip())

    for key in priorities:
        df = all_winners.get(key, None)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue

        t = _table_with_id(df)
        t = _normalize_shortlist(t)
        if t.empty:
            continue

        r = t.iloc[[0]].copy()

        rid = str(r.iloc[0].get("ID", "")).strip()
        if rid:
            if rid in used:
                continue
            used.add(rid)
        else:
            b = str(r.iloc[0].get("Brand", "")).strip().lower()
            m = str(r.iloc[0].get("Model", "")).strip().lower()
            f = str(r.iloc[0].get("Flex", "")).strip().lower()
            k = f"{b}|{m}|{f}"
            if k in used:
                continue
            used.add(k)

        picks.append(r)

        if len(picks) >= max_additional:
            break

    if not picks:
        return pd.DataFrame()

    out = pd.concat(picks, axis=0, ignore_index=True)
    return _normalize_shortlist(out)


def _result_to_row(r: Any) -> Dict[str, Any]:
    if r is None:
        return {}

    if isinstance(r, dict):
        sid = str(r.get("shaft_id", "")).strip() or str(r.get("Shaft ID", "")).strip()
        lab = str(r.get("shaft_label", "")).strip() or str(r.get("Shaft", "")).strip()
        score = _to_float(r.get("overall_score", r.get("Score", 0.0)), 0.0)
        why = " | ".join([str(x) for x in (r.get("reasons") or [])][:3]).strip()
        if not why:
            why = str(r.get("Why", "") or "").strip()
        return {"Shaft ID": sid, "Shaft": lab, "Score": score, "Why": why}

    sid = str(getattr(r, "shaft_id", "")).strip()
    lab = str(getattr(r, "shaft_label", "")).strip()
    score = _to_float(getattr(r, "overall_score", 0.0), 0.0)
    why = " | ".join([str(x) for x in (getattr(r, "reasons", None) or [])][:3]).strip()
    return {"Shaft ID": sid, "Shaft": lab, "Score": score, "Why": why}


def _goal_best_to_card(best: Any, goal_name: str, baseline_id: Optional[str]) -> None:
    if best is None:
        return

    if isinstance(best, dict):
        lab = str(best.get("shaft_label", "")).strip() or str(best.get("Shaft", "")).strip()
        sid = str(best.get("shaft_id", "")).strip() or str(best.get("Shaft ID", "")).strip()
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
    if isinstance(reasons, list) and reasons:
        for b in reasons[:3]:
            st.write(f"- {b}")


def _next_round_from_goal_payload(gr: Dict[str, Any], max_n: int = 3) -> List[Dict[str, Any]]:
    baseline_id = str(gr.get("baseline_shaft_id", "") or "").strip()
    results = gr.get("results", []) or []

    tested = _tested_shaft_ids()
    if baseline_id:
        tested.add(baseline_id)

    out: List[Dict[str, Any]] = []
    for r in results:
        row = _result_to_row(r)
        sid = str(row.get("Shaft ID", "")).strip()
        if not sid:
            continue
        if sid in tested:
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

    q23 = str(ans.get("Q23", "")).strip()

    # Flight/Feel mapping (safe if blank)
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
<div><b>PRIMARY GOAL (Q23):</b> {q23 or "<span class='smallcap'>not answered</span>"}</div>
</div></div>""",
        unsafe_allow_html=True,
    )

    # -----------------------------
    # Goal-based recommendations (Trackman / Goal Engine)
    # -----------------------------
    gr = _get_goal_payload()

    has_results = isinstance(gr, dict) and isinstance(gr.get("results", None), list) and len(gr.get("results", [])) > 0
    has_winner_only = isinstance(gr, dict) and isinstance(gr.get("winner_summary", None), dict)

    if has_results or has_winner_only:
        st.subheader("🎯 Goal-Based Recommendations (post-Trackman)")

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
                st.caption("Filtered to avoid repeating shafts already logged in Trackman Lab.")
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
            "Goal-based recommendations will appear here after you upload Trackman data in **🧪 Trackman Lab** "
            "and click **➕ Add** at least once.\n\n"
            "This section reads from `st.session_state.goal_recommendations`."
        )
        st.divider()

    # -----------------------------
    # Winner summary (Trackman Lab intelligence)
    # -----------------------------
    ws = st.session_state.get("winner_summary", None)
    if isinstance(ws, dict) and (ws.get("shaft_label") or ws.get("explain")):
        headline = ws.get("headline") or "Tour Proven Winner"
        shaft_label = ws.get("shaft_label") or "Winner selected"
        explain = ws.get("explain") or ""
        st.subheader("🏆 Winner (from Trackman Lab Intelligence)")
        st.success(f"**{headline}:** {shaft_label}")
        if explain:
            st.caption(explain)

    # -----------------------------
    # Pre-test shortlist (interview-driven)
    # -----------------------------
    if not _baseline_logged():
        st.subheader("🧠 Pre-Test Short List (before baseline testing is logged)")
        st.caption("Driven by Q23. Stays short until baseline is logged; then Trackman/goal scoring takes over.")

        gamer = pd.DataFrame([_gamer_row(ans)])
        shortlist = _pick_interview_short_list(all_winners, ans, max_additional=3)

        combined = gamer
        if isinstance(shortlist, pd.DataFrame) and not shortlist.empty:
            combined = pd.concat([gamer, shortlist], axis=0, ignore_index=True)

        combined = _dedupe_shortlist(combined, ans)

        st.dataframe(_table_with_id(combined), use_container_width=True, hide_index=True)
        st.divider()
    else:
        with st.expander("Show legacy interview section (optional)", expanded=False):
            st.subheader("🧠 Interview Starting Point (reference only)")
            st.caption("Baseline is logged — Trackman/goal scoring should be your main decision driver now.")

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
                    df = all_winners.get(cat, None)
                    if isinstance(df, pd.DataFrame) and not df.empty:
                        st.dataframe(_table_with_id(df), use_container_width=True, hide_index=True)
                        blurb = v_items[i][1] if i < len(v_items) else "Optimized."
                        st.markdown(
                            f"<div class='verdict-text'><b>Verdict:</b> {blurb}</div>",
                            unsafe_allow_html=True,
                        )

        st.divider()

    # -----------------------------
    # PDF sending
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
