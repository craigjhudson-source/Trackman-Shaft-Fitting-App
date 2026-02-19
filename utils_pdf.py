from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List, Set

import os
from fpdf import FPDF

# Optional at runtime (Streamlit), but safe if not present
try:
    import streamlit as st  # type: ignore
except Exception:
    st = None  # type: ignore

import pandas as pd


def _safe_text(s: Any) -> str:
    txt = "" if s is None else str(s)
    txt = txt.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    txt = txt.replace("\u00A0", " ")  # non-breaking space
    txt = " ".join(txt.split())
    return txt


def _safe_str(x: Any) -> str:
    try:
        return str(x).strip()
    except Exception:
        return ""


def _break_long_tokens(s: str) -> str:
    for sep in ["/", "_", "|", "—", "–", "-", ":", ";"]:
        s = s.replace(sep, f"{sep} ")
    return s


def _latin1_fallback(s: str) -> str:
    if not s:
        return ""
    replacements = {
        "•": "-",
        "⚠️": "WARNING: ",
        "⚠": "WARNING: ",
        "→": "->",
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "\u200b": "",
    }
    for a, b in replacements.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def _find_ttf_candidates() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Returns (regular_ttf, bold_ttf, italic_ttf) where available.
    Streamlit Cloud/Linux friendly paths + repo-local fallback.
    """
    regular_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        os.path.join(os.getcwd(), "assets", "fonts", "DejaVuSans.ttf"),
        os.path.join(os.getcwd(), "fonts", "DejaVuSans.ttf"),
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        os.path.join(os.getcwd(), "assets", "fonts", "DejaVuSans-Bold.ttf"),
        os.path.join(os.getcwd(), "fonts", "DejaVuSans-Bold.ttf"),
    ]
    italic_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Oblique.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Oblique.ttf",
        os.path.join(os.getcwd(), "assets", "fonts", "DejaVuSans-Oblique.ttf"),
        os.path.join(os.getcwd(), "fonts", "DejaVuSans-Oblique.ttf"),
    ]

    def _first_existing(paths):
        for p in paths:
            try:
                if p and os.path.exists(p) and os.path.isfile(p):
                    return p
            except Exception:
                continue
        return None

    return _first_existing(regular_candidates), _first_existing(bold_candidates), _first_existing(italic_candidates)


class TourProvenPDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.set_auto_page_break(auto=True, margin=12)
        self.set_margins(12, 12, 12)

        self._unicode_ok = False
        self._font_family = "Helvetica"
        self._has_bold = False
        self._has_italic = False

        regular_ttf, bold_ttf, italic_ttf = _find_ttf_candidates()

        if regular_ttf:
            try:
                self.add_font("DejaVu", style="", fname=regular_ttf, uni=True)
                self._unicode_ok = True
                self._font_family = "DejaVu"
            except Exception:
                self._unicode_ok = False
                self._font_family = "Helvetica"

        if self._unicode_ok and bold_ttf:
            try:
                self.add_font("DejaVu", style="B", fname=bold_ttf, uni=True)
                self._has_bold = True
            except Exception:
                self._has_bold = False

        if self._unicode_ok and italic_ttf:
            try:
                self.add_font("DejaVu", style="I", fname=italic_ttf, uni=True)
                self._has_italic = True
            except Exception:
                self._has_italic = False

    def _t(self, s: Any) -> str:
        txt = _break_long_tokens(_safe_text(s))
        return txt if self._unicode_ok else _latin1_fallback(txt)

    def _set_font_safe(self, style: str, size: int) -> None:
        fam = self._font_family
        stl = (style or "").upper()

        if fam == "DejaVu":
            if stl == "B" and not self._has_bold:
                stl = ""
            if stl == "I" and not self._has_italic:
                stl = ""
            if stl == "BI":
                stl = "B" if self._has_bold else ("I" if self._has_italic else "")

        self.set_font(fam, stl, size)

    def header(self):
        self._set_font_safe("B", 14)
        self.cell(0, 8, self._t("Tour Proven Iron Build Report"), ln=1)
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self._set_font_safe("", 9)
        self.cell(0, 8, self._t(f"Page {self.page_no()}"), align="C")

    def section_title(self, title: str) -> None:
        self.ln(2)
        self._set_font_safe("B", 12)
        self.set_x(self.l_margin)
        self.cell(0, 7, self._t(title), ln=1)
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def kv_line(self, k: str, v: Any) -> None:
        self._set_font_safe("B", 10)
        self.set_x(self.l_margin)
        self.cell(55, 5, self._t(k))
        self._set_font_safe("", 10)
        self.safe_multicell(self._t(v), line_h=5)

    def safe_multicell(self, text: str, line_h: float = 4.5) -> None:
        self.set_x(self.l_margin)
        w = (self.w - self.r_margin) - self.get_x()
        if w <= 5:
            self.ln(line_h)
            self.set_x(self.l_margin)
            w = (self.w - self.r_margin) - self.get_x()

        try:
            self.multi_cell(w, line_h, text)
        except Exception:
            self.set_margins(12, 12, 12)
            self.set_x(self.l_margin)
            w2 = (self.w - self.r_margin) - self.get_x()
            if w2 <= 5:
                w2 = max(20, self.w - 24)
            t2 = text if self._unicode_ok else _latin1_fallback(text)
            self.multi_cell(w2, line_h, t2)

    def bullet(self, text: str) -> None:
        self._set_font_safe("", 10)
        prefix = "• " if self._unicode_ok else "- "
        self.safe_multicell(self._t(prefix + str(text)), line_h=4.5)


# -----------------------------
# Data extraction helpers
# -----------------------------
def _get_goal_payload_from_session() -> Optional[Dict[str, Any]]:
    if st is None:
        return None
    try:
        ss = st.session_state
        for k in ("goal_recommendations", "goal_rankings", "goal_recs"):
            v = ss.get(k, None)
            if isinstance(v, dict) and v:
                return v
    except Exception:
        return None
    return None


def _get_winner_summary_from_session() -> Optional[Dict[str, Any]]:
    if st is None:
        return None
    try:
        ws = st.session_state.get("winner_summary", None)
        return ws if isinstance(ws, dict) and ws else None
    except Exception:
        return None


def _get_tested_ids_from_session() -> Set[str]:
    out: Set[str] = set()
    if st is None:
        return out
    try:
        lab = st.session_state.get("tm_lab_data", None)
        if isinstance(lab, list) and len(lab) > 0:
            df = pd.DataFrame(lab)
            if not df.empty and "Shaft ID" in df.columns:
                vals = df["Shaft ID"].astype(str).str.strip().tolist()
                out.update([v for v in vals if v])
    except Exception:
        return out
    return out


def _get_pretest_shortlist_df_from_session() -> Optional[pd.DataFrame]:
    if st is None:
        return None
    try:
        df = st.session_state.get("pretest_shortlist_df", None)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return df.copy()
    except Exception:
        pass
    return None


def _gamer_row_from_answers(answers: Dict[str, Any]) -> Dict[str, Any]:
    brand = _safe_str(answers.get("Q10", ""))
    model = _safe_str(answers.get("Q12", ""))
    flex = _safe_str(answers.get("Q11", ""))
    return {
        "ID": "GAMER",
        "Brand": brand or "—",
        "Model": model or "Current Gamer",
        "Flex": flex or "—",
        "Weight (g)": "—",
    }


def _normalize_shortlist_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["ID", "Brand", "Model", "Flex", "Weight (g)"]
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = ""
        out[c] = out[c].astype(str).str.strip().replace({"nan": "", "None": "", "NaN": ""})
    out = out[cols].copy()
    # keep order, drop duplicate IDs (except GAMER)
    seen: Set[str] = set()
    rows: List[Dict[str, Any]] = []
    for _, r in out.iterrows():
        rid = _safe_str(r.get("ID", ""))
        key = rid if rid and rid.upper() != "GAMER" else f"GAMER|{_safe_str(r.get('Brand',''))}|{_safe_str(r.get('Model',''))}|{_safe_str(r.get('Flex',''))}"
        if key in seen:
            continue
        seen.add(key)
        rows.append({c: _safe_str(r.get(c, "")) for c in cols})
    return pd.DataFrame(rows, columns=cols)


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


def _next_round_from_goal_payload(gr: Dict[str, Any], max_n: int = 3) -> List[Dict[str, Any]]:
    baseline_id = _safe_str(gr.get("baseline_shaft_id", "") or "")
    results = gr.get("results", []) or []

    tested = _get_tested_ids_from_session()
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
# Public API
# -----------------------------
def create_pdf_bytes(
    player_name: str,
    winners: Dict[str, Any],          # legacy (ignored)
    answers: Dict[str, Any],
    verdicts: Dict[str, str],         # legacy (ignored)
    phase6_recs: Optional[Any] = None,
    environment: str = "",
) -> bytes:
    """
    V1 PDF output:
    - Player summary
    - Pre-test short list (GAMER + 2–3)
    - Post-TrackMan goal-based results (if available)
    - Winner summary (if available)
    - Phase 6 notes (if available)

    Note: winners/verdicts are intentionally ignored (legacy tables removed).
    """
    pdf = TourProvenPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()

    # -----------------------------
    # Player summary
    # -----------------------------
    pdf.section_title("Player Summary")
    pdf.kv_line("Player", player_name)

    if answers:
        pdf.kv_line("Email", answers.get("Q02", ""))
        pdf.kv_line("Carry (6i)", f"{answers.get('Q15','')} yd")
        pdf.kv_line("Head", f"{answers.get('Q08','')} {answers.get('Q09','')}")
        pdf.kv_line("Current Shaft", f"{answers.get('Q10','')} {answers.get('Q12','')} ({answers.get('Q11','')})")
        pdf.kv_line("Specs", f"{answers.get('Q13','')} L / {answers.get('Q14','')} SW")
        pdf.kv_line("Grip / Ball", f"{answers.get('Q06','')} / {answers.get('Q07','')}")
        # Rename display label (Q23 remains the storage key)
        pdf.kv_line("Primary Performance Objective", answers.get("Q23", ""))

        # Flight / Feel (optional)
        flight = _safe_str(answers.get("Q16_1", ""))
        happy = _safe_str(answers.get("Q16_2", ""))
        target = _safe_str(answers.get("Q16_3", ""))
        flight_line = flight
        if happy:
            flight_line = f"{flight_line} ({happy})" if flight_line else f"({happy})"
        if target:
            flight_line = f"{flight_line} -> {target}" if flight_line else target
        if flight_line:
            pdf.kv_line("Flight", flight_line)

        feel = _safe_str(answers.get("Q19_1", ""))
        fh = _safe_str(answers.get("Q19_2", ""))
        ft = _safe_str(answers.get("Q19_3", ""))
        feel_line = feel
        if fh:
            feel_line = f"{feel_line} ({fh})" if feel_line else f"({fh})"
        if ft:
            feel_line = f"{feel_line} -> {ft}" if feel_line else ft
        if feel_line:
            pdf.kv_line("Feel", feel_line)

    if environment:
        pdf.kv_line("Environment", environment)

    # -----------------------------
    # Pre-test shortlist
    # -----------------------------
    pdf.section_title("Pre-Test Short List (Interview-Driven)")

    ss_short = _get_pretest_shortlist_df_from_session()
    if ss_short is not None and not ss_short.empty:
        shortlist_df = _normalize_shortlist_df(ss_short)
        # Guarantee gamer shown first (session df should already be non-gamer only)
        gamer = _gamer_row_from_answers(answers or {})
        rows = [gamer] + shortlist_df.to_dict(orient="records")
    else:
        # Best-effort fallback (no shafts DF available inside PDF util)
        rows = [_gamer_row_from_answers(answers or {})]

    for r in rows:
        rid = _safe_str(r.get("ID", ""))
        line = f"{rid} | {r.get('Brand','')} {r.get('Model','')} ({r.get('Flex','')}) | {r.get('Weight (g)','')}g"
        pdf.bullet(line)

    # -----------------------------
    # Post-TrackMan results (goal payload)
    # -----------------------------
    gr = _get_goal_payload_from_session()
    if isinstance(gr, dict) and gr:
        results = gr.get("results", []) or []
        top_by_goal = gr.get("top_by_goal", {}) if isinstance(gr.get("top_by_goal", {}), dict) else {}
        baseline_id = _safe_str(gr.get("baseline_shaft_id", "") or gr.get("baseline_tag_id", "") or "")

        pdf.section_title("Goal-Based Results (Post-TrackMan)")

        if baseline_id:
            pdf.kv_line("Baseline Shaft ID", baseline_id)

        if results:
            top = results[0]
            row = _result_to_row(top)
            pdf._set_font_safe("B", 10)
            pdf.safe_multicell(pdf._t(f"Best overall: {row.get('Shaft','')} (ID {row.get('Shaft ID','')})"), line_h=4.7)
            why = _safe_str(row.get("Why", ""))
            if why:
                pdf._set_font_safe("", 10)
                pdf.safe_multicell(pdf._t(f"Why: {why}"), line_h=4.5)

            pdf.ln(1)
            pdf._set_font_safe("B", 10)
            pdf.safe_multicell(pdf._t("Top leaderboard (first 5):"), line_h=4.7)
            pdf._set_font_safe("", 10)
            for r in results[:5]:
                rr = _result_to_row(r)
                pdf.bullet(f"{rr.get('Shaft','')} | ID {rr.get('Shaft ID','')} | Score {rr.get('Score',0):.2f}")

        if top_by_goal:
            pdf.ln(1)
            pdf._set_font_safe("B", 10)
            pdf.safe_multicell(pdf._t("Best by goal:"), line_h=4.7)
            pdf._set_font_safe("", 10)
            for goal_name, best in list(top_by_goal.items())[:8]:
                b = _result_to_row(best)
                pdf.bullet(f"{goal_name}: {b.get('Shaft','')} (ID {b.get('Shaft ID','')})")

        # Next round suggestions (filtered)
        if results:
            next_round = _next_round_from_goal_payload(gr, max_n=3)
            pdf.ln(1)
            pdf._set_font_safe("B", 10)
            pdf.safe_multicell(pdf._t("Next round to test (suggested):"), line_h=4.7)
            pdf._set_font_safe("", 10)
            if next_round:
                for r in next_round:
                    pdf.bullet(f"{r.get('Shaft','')} (ID {r.get('Shaft ID','')})")
            else:
                pdf.safe_multicell(pdf._t("No new candidates suggested yet (log more shafts or widen test set)."))

    # -----------------------------
    # Winner summary (TrackMan intelligence)
    # -----------------------------
    ws = _get_winner_summary_from_session()
    if isinstance(ws, dict) and ws:
        headline = _safe_str(ws.get("headline", "Tour Proven Winner"))
        shaft_label = _safe_str(ws.get("shaft_label", ""))
        explain = _safe_str(ws.get("explain", ""))

        if shaft_label or explain:
            pdf.section_title("Winner Summary (TrackMan Intelligence)")
            if shaft_label:
                pdf._set_font_safe("B", 10)
                pdf.safe_multicell(pdf._t(f"{headline}: {shaft_label}"), line_h=4.7)
            if explain:
                pdf._set_font_safe("", 10)
                pdf.safe_multicell(pdf._t(explain), line_h=4.5)

    # -----------------------------
    # Phase 6 notes
    # -----------------------------
    pdf.section_title("Phase 6 Optimization Notes")
    if phase6_recs and isinstance(phase6_recs, list):
        for r in phase6_recs:
            try:
                r_type = _safe_text(r.get("type", "Note"))
                txt = _safe_text(r.get("text", ""))
                sev = _safe_text(r.get("severity", "")).lower()
                prefix = "⚠️ " if (sev == "warn" and pdf._unicode_ok) else ("WARNING: " if sev == "warn" else "")
                pdf.bullet(f"{prefix}{r_type}: {txt}")
            except Exception:
                continue
    else:
        pdf.safe_multicell(pdf._t("No Phase 6 notes available yet. Generate a winner in TrackMan Lab first."))

    out = pdf.output(dest="S")
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    if isinstance(out, str):
        return out.encode("latin-1", "replace")
    return str(out).encode("latin-1", "replace")
