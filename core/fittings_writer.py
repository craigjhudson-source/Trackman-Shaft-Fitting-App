# core/fittings_writer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


def _norm_header(s: Any) -> str:
    """
    Normalize headers/text for robust matching:
    - normalize NBSP
    - collapse whitespace
    - lowercase
    """
    txt = "" if s is None else str(s)
    txt = txt.replace("\u00A0", " ")
    txt = " ".join(txt.strip().split())
    return txt.lower()


def _norm_qid(s: Any) -> str:
    """
    Normalize QuestionID so Q16.1 and Q16_1 resolve consistently.
    """
    txt = "" if s is None else str(s).strip()
    return txt.replace(".", "_").upper()


@dataclass
class FittingMeta:
    timestamp: str
    name: str
    email: str
    phone: str


def build_questiontext_to_qid(questions_df_rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Build map of normalized QuestionText -> normalized QID
    Expects each row dict to have keys: 'QuestionText', 'QuestionID'
    """
    out: Dict[str, str] = {}
    for r in questions_df_rows:
        qtext = _norm_header(r.get("QuestionText", ""))
        qid = _norm_qid(r.get("QuestionID", ""))
        if qtext and qid:
            out[qtext] = qid
    return out


def build_fittings_row(
    *,
    fittings_headers: List[str],
    questiontext_to_qid: Dict[str, str],
    answers: Dict[str, Any],
    meta: FittingMeta,
) -> List[Any]:
    """
    Create a row aligned to the Fittings header row.

    Priority per header:
      1) Meta columns (Timestamp/Name/Email/Phone)
      2) If header is literally a QID like "Q16_2"
      3) If header matches a QuestionText in Questions tab
      4) Blank
    """
    meta_map = {
        _norm_header("Timestamp"): meta.timestamp,
        _norm_header("Name"): meta.name,
        _norm_header("Email"): meta.email,
        _norm_header("Phone"): meta.phone,
    }

    row_out: List[Any] = []
    for h in fittings_headers:
        h_raw = "" if h is None else str(h)
        h_norm = _norm_header(h_raw)

        if not h_norm:
            row_out.append("")
            continue

        # 1) meta fields
        if h_norm in meta_map:
            row_out.append(meta_map[h_norm])
            continue

        # 2) QID header direct (rare, but safe)
        h_as_qid = _norm_qid(h_raw)
        if h_as_qid.startswith("Q") and len(h_as_qid) >= 3 and "_" in h_as_qid:
            row_out.append(answers.get(h_as_qid, ""))
            continue

        # 3) header text -> qid
        qid = questiontext_to_qid.get(h_norm)
        if qid:
            row_out.append(answers.get(qid, ""))
        else:
            row_out.append("")

    return row_out
