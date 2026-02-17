# utils_pdf.py
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import os
from fpdf import FPDF


def _safe_text(s: Any) -> str:
    txt = "" if s is None else str(s)
    txt = txt.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    txt = txt.replace("\u00A0", " ")  # non-breaking space
    txt = " ".join(txt.split())
    return txt


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
                # Register unicode font family "DejaVu"
                self.add_font("DejaVu", style="", fname=regular_ttf, uni=True)
                self._unicode_ok = True
                self._font_family = "DejaVu"
            except Exception:
                self._unicode_ok = False
                self._font_family = "Helvetica"

        # Register bold/italic if available (required to use style="B"/"I")
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
        """
        Safely set font style even if DejaVu bold/italic isn't available.
        Prevents: FPDFException in set_font().
        """
        fam = self._font_family
        stl = (style or "").upper()

        if fam == "DejaVu":
            if stl == "B" and not self._has_bold:
                stl = ""
            if stl == "I" and not self._has_italic:
                stl = ""
            # (BI not supported here; if you want it later we can add DejaVuSans-BoldOblique.ttf)
            if stl == "BI":
                stl = "B" if self._has_bold else ("I" if self._has_italic else "")

        self.set_font(fam, stl, size)

    def header(self):
        self._set_font_safe("B", 14)
        self.cell(0, 8, self._t("Tour Proven Shaft Fitting"), ln=1)
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
        self.cell(40, 5, self._t(k))
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


def create_pdf_bytes(
    player_name: str,
    winners: Dict[str, Any],
    answers: Dict[str, Any],
    verdicts: Dict[str, str],
    phase6_recs: Optional[Any] = None,
    environment: str = "",
) -> bytes:
    pdf = TourProvenPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()

    pdf.section_title("Player Summary")
    pdf.kv_line("Player", player_name)
    if answers:
        pdf.kv_line("Email", answers.get("Q02", ""))
        pdf.kv_line("Carry (6i)", f"{answers.get('Q15','')} yd")
        pdf.kv_line("Head", f"{answers.get('Q08','')} {answers.get('Q09','')}")
        pdf.kv_line("Current Shaft", f"{answers.get('Q10','')} {answers.get('Q12','')} ({answers.get('Q11','')})")
        pdf.kv_line("Specs", f"{answers.get('Q13','')} L / {answers.get('Q14','')} SW")
        pdf.kv_line("Grip / Ball", f"{answers.get('Q06','')} / {answers.get('Q07','')}")
    if environment:
        pdf.kv_line("Environment", environment)

    pdf.section_title("Interview-Based Starting Point")
    if isinstance(winners, dict) and winners:
        for cat, df in winners.items():
            try:
                model = df.iloc[0]["Model"]
            except Exception:
                model = ""
            v = verdicts.get(f"{cat}: {model}", verdicts.get(f"{cat}:", ""))
            line = f"{cat}: {model}".strip(": ").strip()
            if not line:
                continue

            pdf._set_font_safe("B", 10)
            pdf.safe_multicell(pdf._t(line), line_h=4.7)

            if v:
                pdf._set_font_safe("", 10)
                pdf.safe_multicell(pdf._t(f"Verdict: {v}"), line_h=4.5)
            pdf.ln(1)
    else:
        pdf.safe_multicell(pdf._t("No interview-based winners available."))

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
        pdf.safe_multicell(pdf._t("No Phase 6 notes available yet. Generate a winner in Trackman Lab first."))

    out = pdf.output(dest="S")
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    if isinstance(out, str):
        return out.encode("latin-1", "replace")
    return str(out).encode("latin-1", "replace")
