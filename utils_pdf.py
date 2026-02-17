# utils_pdf.py
from __future__ import annotations

from typing import Any, Dict, Optional

import os
from fpdf import FPDF


def _safe_text(s: Any) -> str:
    # Convert to string and normalize whitespace
    txt = "" if s is None else str(s)
    txt = txt.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    txt = txt.replace("\u00A0", " ")  # non-breaking space
    txt = " ".join(txt.split())
    return txt


def _break_long_tokens(s: str) -> str:
    """
    Help fpdf line breaking by inserting spaces after common separators.
    This avoids super-long tokens like URLs/IDs causing overflow.
    """
    # Keep separators simple; unicode-friendly
    for sep in ["/", "_", "|", "—", "–", "-", ":", ";"]:
        s = s.replace(sep, f"{sep} ")
    return s


def _latin1_fallback(s: str) -> str:
    """
    If we cannot load a Unicode font, core fonts are latin-1 only.
    This turns text into a safe representation that will not crash.
    """
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


def _find_dejavu_ttf() -> Optional[str]:
    """
    Try common font locations (Streamlit Cloud/Linux friendly).
    If you later decide to commit a font into the repo, add its path here too.
    """
    candidates = [
        # Common Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        # Sometimes present in slim images
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        # Repo-local (if you decide to add it later)
        os.path.join(os.getcwd(), "assets", "fonts", "DejaVuSans.ttf"),
        os.path.join(os.getcwd(), "fonts", "DejaVuSans.ttf"),
    ]
    for p in candidates:
        try:
            if p and os.path.exists(p) and os.path.isfile(p):
                return p
        except Exception:
            continue
    return None


class TourProvenPDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.set_auto_page_break(auto=True, margin=12)
        self.set_margins(12, 12, 12)

        # Try to enable Unicode font support
        self._unicode_ok = False
        self._font_family = "Helvetica"

        ttf = _find_dejavu_ttf()
        if ttf:
            try:
                # fpdf2 unicode font registration
                self.add_font("DejaVu", style="", fname=ttf, uni=True)
                self._unicode_ok = True
                self._font_family = "DejaVu"
            except Exception:
                # If anything goes wrong, stay in core font mode safely
                self._unicode_ok = False
                self._font_family = "Helvetica"

    def _t(self, s: Any) -> str:
        """
        Prepare text for PDF output. If unicode font is available, keep as-is.
        Otherwise, sanitize for latin-1 core fonts to avoid crashes.
        """
        txt = _break_long_tokens(_safe_text(s))
        return txt if self._unicode_ok else _latin1_fallback(txt)

    def header(self):
        self.set_font(self._font_family, "B", 14)
        self.cell(0, 8, self._t("Tour Proven Shaft Fitting"), ln=1)
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font(self._font_family, "", 9)
        self.cell(0, 8, self._t(f"Page {self.page_no()}"), align="C")

    def section_title(self, title: str) -> None:
        self.ln(2)
        self.set_font(self._font_family, "B", 12)
        self.set_x(self.l_margin)
        self.cell(0, 7, self._t(title), ln=1)
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def kv_line(self, k: str, v: Any) -> None:
        self.set_font(self._font_family, "B", 10)
        self.set_x(self.l_margin)
        self.cell(40, 5, self._t(k))
        self.set_font(self._font_family, "", 10)
        self.safe_multicell(self._t(v), line_h=5)

    def safe_multicell(self, text: str, line_h: float = 4.5) -> None:
        """
        Always reset X to left margin and compute positive width.
        If width is too small, force a line break and retry.
        Works for both unicode and core-font fallback.
        """
        self.set_x(self.l_margin)
        w = (self.w - self.r_margin) - self.get_x()
        if w <= 5:
            self.ln(line_h)
            self.set_x(self.l_margin)
            w = (self.w - self.r_margin) - self.get_x()

        try:
            self.multi_cell(w, line_h, text)
        except Exception:
            # last resort safety: reset margins and retry with conservative width
            self.set_margins(12, 12, 12)
            self.set_x(self.l_margin)
            w2 = (self.w - self.r_margin) - self.get_x()
            if w2 <= 5:
                w2 = max(20, self.w - 24)
            # In fallback mode, make sure we don't crash on unicode
            t2 = text if self._unicode_ok else _latin1_fallback(text)
            self.multi_cell(w2, line_h, t2)

    def bullet(self, text: str) -> None:
        self.set_font(self._font_family, "", 10)
        # Use real bullet when unicode font is available, else use dash
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
    """
    Drop-in replacement for utils.create_pdf_bytes signature.
    Unicode-capable when DejaVu font is available; otherwise safe fallback.
    """
    pdf = TourProvenPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()

    # ---- Player summary ----
    pdf.section_title("Player Summary")
    pdf.kv_line("Player", player_name)
    if answers:
        pdf.kv_line("Email", answers.get("Q02", ""))
        pdf.kv_line("Carry (6i)", f"{answers.get('Q15','')} yd")
        pdf.kv_line("Head", f"{answers.get('Q08','')} {answers.get('Q09','')}")
        pdf.kv_line(
            "Current Shaft",
            f"{answers.get('Q10','')} {answers.get('Q12','')} ({answers.get('Q11','')})",
        )
        pdf.kv_line("Specs", f"{answers.get('Q13','')} L / {answers.get('Q14','')} SW")
        pdf.kv_line("Grip / Ball", f"{answers.get('Q06','')} / {answers.get('Q07','')}")
    if environment:
        pdf.kv_line("Environment", environment)

    # ---- Predictor winners ----
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

            pdf.set_font(pdf._font_family, "B", 10)
            pdf.safe_multicell(pdf._t(line), line_h=4.7)

            if v:
                pdf.set_font(pdf._font_family, "", 10)
                pdf.safe_multicell(pdf._t(f"Verdict: {v}"), line_h=4.5)
            pdf.ln(1)
    else:
        pdf.safe_multicell(pdf._t("No interview-based winners available."))

    # ---- Phase 6 tuning notes ----
    pdf.section_title("Phase 6 Optimization Notes")
    if phase6_recs and isinstance(phase6_recs, list):
        for r in phase6_recs:
            try:
                r_type = _safe_text(r.get("type", "Note"))
                txt = _safe_text(r.get("text", ""))
                sev = _safe_text(r.get("severity", "")).lower()

                # Keep emoji only when unicode font is available; else readable fallback
                prefix = "⚠️ " if (sev == "warn" and pdf._unicode_ok) else ("WARNING: " if sev == "warn" else "")
                pdf.bullet(f"{prefix}{r_type}: {txt}")
            except Exception:
                continue
    else:
        pdf.safe_multicell(pdf._t("No Phase 6 notes available yet. Generate a winner in Trackman Lab first."))

    out = pdf.output(dest="S")
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)

    # If fpdf returns a str, encode safely
    if isinstance(out, str):
        return out.encode("latin-1", "replace")

    return str(out).encode("latin-1", "replace")
