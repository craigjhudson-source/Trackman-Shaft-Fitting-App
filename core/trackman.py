# core/trackman.py
from __future__ import annotations

import io
import re
from typing import Dict, List, Optional, Union

import pandas as pd


METRIC_ALIASES: Dict[str, List[str]] = {
    "club_speed": ["club speed"],
    "ball_speed": ["ball speed"],
    "smash": ["smash factor", "smashfactor"],
    "carry": ["carry flat - length", "carry length", "carry"],
    "spin": ["spin rate"],
    "launch": ["launch angle"],
    "landing_angle": ["land. angle", "landing angle", "carry flat - land angle"],
    "face_to_path": ["face to path"],
    "dynamic_lie": ["dynamic lie"],
    "impact_offset": ["impact offset"],
    "impact_height": ["impact height"],
    "club_path": ["club path"],
    "attack_angle": ["attack angle"],
    "face_angle": ["face angle"],
    "spin_axis": ["spin axis"],
    "curve": ["curve"],
}

DISPERSION_ALIASES: Dict[str, List[str]] = {
    "carry_side": ["carry flat - side", "carry side"],
    "total_side": ["est. total flat - side", "total side"],
    "launch_dir": ["launch direction"],
}


def _norm_col(col: str) -> str:
    c = str(col).strip().lower()
    c = re.sub(r"\[[^\]]*\]", "", c)  # remove units: [mph], [rpm], etc.
    c = c.replace(".", " ")
    c = c.replace("-", " ")
    c = re.sub(r"\s+", " ", c).strip()
    return c


def _find_col(df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
    norm_map = {c: _norm_col(c) for c in df.columns}
    for col, n in norm_map.items():
        for a in aliases:
            if a in n:
                return col
    return None


def _read_uploaded_bytes(uploaded_file) -> bytes:
    """
    Streamlit uploader objects usually support .getvalue().
    Fallback to .read() if needed.
    """
    if uploaded_file is None:
        return b""
    if hasattr(uploaded_file, "getvalue"):
        return uploaded_file.getvalue()
    if hasattr(uploaded_file, "read"):
        return uploaded_file.read()
    return b""


def _read_csv_trackman(raw_bytes: bytes) -> pd.DataFrame:
    """
    Handles TrackMan CSV exports that often begin with:
      sep=,
    and may include UTF-8 BOMs.

    We:
      - decode with utf-8-sig (strips BOM)
      - remove a leading 'sep=...' line if present
      - read into pandas
    """
    text = raw_bytes.decode("utf-8-sig", errors="ignore")
    lines = text.splitlines()

    # Remove leading empty lines
    while lines and not lines[0].strip():
        lines.pop(0)

    # Handle TrackMan/Excel "sep=," header
    if lines and lines[0].strip().lower().startswith("sep="):
        lines = lines[1:]

    cleaned = "\n".join(lines)
    # engine="python" is more forgiving with weird rows
    return pd.read_csv(io.StringIO(cleaned), engine="python")


def _maybe_cleanup_trackman_export(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fix common export issues:
      - extra title row(s)
      - units row (mph, rpm, deg)
    """
    if df is None or df.empty:
        return df

    # If headers look like 0..N, it's probably missing proper headers.
    headers_are_default = all(str(c).strip().isdigit() for c in df.columns)

    def row_contains_keywords(row_idx: int) -> bool:
        if row_idx < 0 or row_idx >= len(df):
            return False
        row = df.iloc[row_idx].astype(str).str.lower()
        joined = " | ".join(row.tolist())
        return (
            "club speed" in joined
            or "ball speed" in joined
            or "smash" in joined
            or "spin rate" in joined
            or "launch angle" in joined
        )

    if headers_are_default or row_contains_keywords(0) or row_contains_keywords(1):
        if row_contains_keywords(0):
            df2 = df.copy()
            df2.columns = df2.iloc[0].astype(str).tolist()
            df2 = df2.iloc[1:].reset_index(drop=True)
            df = df2
        elif row_contains_keywords(1):
            df2 = df.copy()
            df2.columns = df2.iloc[1].astype(str).tolist()
            df2 = df2.iloc[2:].reset_index(drop=True)
            df = df2

    # Drop likely units rows
    def is_units_row(row: pd.Series) -> bool:
        vals = row.astype(str).str.lower()
        unit_hits = vals.str.contains(r"\b(mph|rpm|deg|°|m/s|yd|yards)\b", regex=True, na=False).sum()
        return unit_hits >= max(3, int(len(vals) * 0.2))

    try:
        if len(df) > 0:
            mask_units = df.apply(is_units_row, axis=1)
            if mask_units.any():
                df = df.loc[~mask_units].reset_index(drop=True)
    except Exception:
        pass

    return df


def _filter_use_in_stat(df: pd.DataFrame) -> pd.DataFrame:
    """
    If 'Use In Stat' exists, keep only TRUE/YES/1/Y.
    """
    if df is None or df.empty:
        return df

    col = _find_col(df, ["use in stat", "use in stats"])
    if not col:
        return df

    s = df[col].astype(str).str.strip().str.lower()
    keep = s.isin(["true", "yes", "1", "y"])
    if keep.any():
        return df.loc[keep].reset_index(drop=True)
    return df


def load_trackman(uploaded_file) -> pd.DataFrame:
    """
    Supports:
      - CSV (including 'sep=,' leading line)
      - XLSX
      - PDF (best-effort; generally recommend exporting CSV/XLSX from TrackMan)
    """
    name = getattr(uploaded_file, "name", "") or ""
    name_l = name.lower()

    if name_l.endswith(".csv"):
        raw_bytes = _read_uploaded_bytes(uploaded_file)
        df = _read_csv_trackman(raw_bytes)

    elif name_l.endswith(".xlsx"):
        df = pd.read_excel(uploaded_file)

    elif name_l.endswith(".pdf"):
        # Best-effort PDF support (TrackMan PDFs are often not machine-readable tables)
        # We'll try to extract text and see if it contains a CSV-like block.
        try:
            import pdfplumber  # type: ignore
        except Exception as e:
            raise RuntimeError("PDF support requires pdfplumber. Export CSV/XLSX for best results.") from e

        raw_bytes = _read_uploaded_bytes(uploaded_file)
        text_all = ""
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t:
                    text_all += "\n" + t

        # Heuristic: if PDF text contains a "sep=" CSV-ish header, try parsing it.
        # Otherwise, fail with guidance.
        m = re.search(r"(?im)^sep=.*$", text_all)
        if not m:
            raise RuntimeError(
                "TrackMan PDF appears not to contain machine-readable tables. "
                "Please export CSV/XLSX from TrackMan for best results."
            )

        # Try to parse from the sep= line onward as CSV
        csv_like = text_all[m.start():]
        df = _read_csv_trackman(csv_like.encode("utf-8", errors="ignore"))

    else:
        # Attempt Excel fallback
        df = pd.read_excel(uploaded_file)

    df = _maybe_cleanup_trackman_export(df)
    df = _filter_use_in_stat(df)

    return df


def summarize_trackman(df: pd.DataFrame, shaft_tag: str, *, include_std: bool = True) -> Dict[str, float | str]:
    out: Dict[str, float | str] = {"Shaft ID": shaft_tag}

    # Shot count after filtering
    out["Shot Count"] = int(len(df)) if df is not None else 0

    def add_metric(label: str, canon_key: str) -> None:
        col = _find_col(df, METRIC_ALIASES.get(canon_key, []))
        if not col:
            return
        s = pd.to_numeric(df[col], errors="coerce")
        if s.notna().any():
            out[label] = round(float(s.mean()), 2)
            if include_std:
                out[f"{label} SD"] = round(float(s.std(ddof=0)), 2)

    add_metric("Club Speed", "club_speed")
    add_metric("Ball Speed", "ball_speed")
    add_metric("Smash Factor", "smash")
    add_metric("Carry", "carry")
    add_metric("Spin Rate", "spin")
    add_metric("Launch Angle", "launch")
    add_metric("Landing Angle", "landing_angle")
    add_metric("Face To Path", "face_to_path")
    add_metric("Dynamic Lie", "dynamic_lie")
    add_metric("Impact Offset", "impact_offset")
    add_metric("Impact Height", "impact_height")
    add_metric("Club Path", "club_path")
    add_metric("Attack Angle", "attack_angle")
    add_metric("Face Angle", "face_angle")
    add_metric("Spin Axis", "spin_axis")
    add_metric("Curve", "curve")

    def add_disp(pretty: str, aliases: List[str]) -> None:
        col = _find_col(df, aliases)
        if not col:
            return
        s = pd.to_numeric(df[col], errors="coerce")
        if s.notna().any():
            out[pretty] = round(float(s.mean()), 2)
            if include_std:
                out[f"{pretty} SD"] = round(float(s.std(ddof=0)), 2)

    add_disp("Carry Side", DISPERSION_ALIASES["carry_side"])
    add_disp("Total Side", DISPERSION_ALIASES["total_side"])
    add_disp("Launch Direction", DISPERSION_ALIASES["launch_dir"])

    return out
