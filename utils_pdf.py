# utils_pdf.py
from __future__ import annotations

from typing import Any, Dict, Optional

from fpdf import FPDF


def _safe_text(s: Any) -> str:
    # Keep it simple: convert to string and replace weird whitespace.
    txt = "" if s is None else str(s)
    txt = txt.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    txt = " ".join(txt.split())
    return txt


def _break_long_tokens(s: str) -> str:
    """
    Help fpdf line breaking by inserting spaces after common separators.
    This avoids super-long tokens like URLs/IDs causing overflow.
    """
    for sep in ["/", "_", "|", "—", "-", ":", ";"]:
        s = s.replace(sep, f"{sep} ")
    return s


class TourProvenPDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_auto_page_break(auto=True, margin=12)
        self.set_margins(12, 12, 12)

    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 8, "Tour Proven Shaft Fitting", ln=1)
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 9)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")

    def section_title(self, title: str) -> None:
        self.ln(2)
        self.set_font("Helvetica", "B", 12)
        self.set_x(self.l_margin)
        self.cell(0, 7, _safe_text(title), ln=1)
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def kv_line(self, k: str, v: Any) -> None:
        self.set_font("Helvetica", "B", 10)
        self.set_x(self.l_margin)
        self.cell(40, 5, _safe_text(k))
        self.set_font("Helvetica", "", 10)
        self.multi_cell(self.w - self.l_margin - self.r_margin - 40, 5, _safe_text(v))

    def safe_multicell(self, text: str, line_h: float = 4.5) -> None:
        """
        Key fix: always reset X to left margin and compute positive width.
        If width is too small, force a line break and retry.
        """
        self.set_x(self.l_margin)
        w = (self.w - self.r_margin) - self.get_x()
        if w <= 5:
            self.ln(line_h)
            self.set_x(self.l_margin)
            w = (self.w - self.r_margin) - self.get_x()

        txt = _break_long_tokens(_safe_text(text))
        self.multi_cell(w, line_h, txt)

    def bullet(self, text: str) -> None:
        self.set_font("Helvetica", "", 10)
        self.safe_multicell(f"• {text}", line_h=4.5)


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
    Designed to never crash on Phase 6 bullets.
    """
    pdf = TourProvenPDF(orientation="P", unit="mm", format="Letter")
    pdf.add_page()

    # ---- Player summary ----
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
            pdf.set_font("Helvetica", "B", 10)
            pdf.safe_multicell(line, line_h=4.7)
            if v:
                pdf.set_font("Helvetica", "", 10)
                pdf.safe_multicell(f"Verdict: {v}", line_h=4.5)
            pdf.ln(1)
    else:
        pdf.safe_multicell("No interview-based winners available.")

    # ---- Phase 6 tuning notes (safe) ----
    pdf.section_title("Phase 6 Optimization Notes")
    if phase6_recs and isinstance(phase6_recs, list):
        for r in phase6_recs:
            try:
                r_type = _safe_text(r.get("type", "Note"))
                txt = _safe_text(r.get("text", ""))
                sev = _safe_text(r.get("severity", "")).lower()
                prefix = "⚠️ " if sev == "warn" else ""
                pdf.bullet(f"{prefix}{r_type}: {txt}")
            except Exception:
                # Never allow a single bad record to crash the PDF
                continue
    else:
        pdf.safe_multicell("No Phase 6 notes available yet. Generate a winner in Trackman Lab first.")

    # Output bytes
    out = pdf.output(dest="S")
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    return str(out).encode("latin-1", "replace")
