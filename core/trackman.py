# core/trackman.py
from __future__ import annotations

import re
from typing import Dict, List, Optional

import pandas as pd

# PDF parsing (best effort)
try:
    import PyPDF2  # type: ignore
except Exception:  # pragma: no cover
    PyPDF2 = None


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
    "total_side": ["est. total flat - side", "total side", "est total flat - side"],
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


def _read_csv_robust(uploaded_file) -> pd.DataFrame:
    """
    Robust CSV reader for TrackMan exports.
    Handles:
      - UTF-8 BOM
      - Excel/TrackMan "sep=," first line
      - occasional delimiter oddities
    """
    data = None
    try:
        data = uploaded_file.getvalue()
    except Exception:
        pass

    if isinstance(data, (bytes, bytearray)) and len(data) > 0:
        try:
            text = data.decode("utf-8-sig", errors="replace")
        except Exception:
            text = data.decode(errors="replace")

        lines = text.splitlines()
        if lines and lines[0].strip().lower().startswith("sep="):
            text = "\n".join(lines[1:])

        try:
            from io import StringIO

            return pd.read_csv(StringIO(text))
        except Exception:
            pass

    try:
        return pd.read_csv(uploaded_file, encoding="utf-8-sig")
    except Exception:
        pass

    try:
        return pd.read_csv(uploaded_file, sep=None, engine="python", encoding="utf-8-sig")
    except Exception:
        return pd.read_csv(uploaded_file)


def _maybe_cleanup_trackman_export(df: pd.DataFrame) -> pd.DataFrame:
    """
    TrackMan exports often include:
      - a junk/title row
      - embedded header row in row 0 or row 1
      - a units row (mph/rpm/deg) that should be dropped

    We detect and fix common cases without breaking clean exports.
    """
    if df is None or df.empty:
        return df

    headers_are_default = all(str(c).strip().isdigit() for c in df.columns)

    def row_contains_keywords(row_idx: int) -> bool:
        if row_idx < 0 or row_idx >= len(df):
            return False
        row = df.iloc[row_idx].astype(str).str.lower()
        joined = " | ".join(row.tolist())
        return (
            ("club speed" in joined)
            or ("ball speed" in joined)
            or ("smash" in joined)
            or ("spin rate" in joined)
            or ("carry flat" in joined)
            or ("use in stat" in joined)
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

    def is_units_row(row: pd.Series) -> bool:
        vals = row.astype(str).str.lower()
        unit_hits = vals.str.contains(r"\b(mph|rpm|deg|°|m/s|yd|yards)\b", regex=True, na=False).sum()
        return unit_hits >= max(3, int(len(vals) * 0.2))

    if len(df) > 0:
        try:
            mask_units = df.apply(is_units_row, axis=1)
            if mask_units.any():
                df = df.loc[~mask_units].reset_index(drop=True)
        except Exception:
            pass

    return df


def _filter_use_in_stat(df: pd.DataFrame) -> pd.DataFrame:
    """
    If 'Use In Stat' column exists, keep only TRUE shots.
    Handles TRUE/False, Yes/No, 1/0, etc.
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

    # If nothing matched, do not filter (safer than dropping everything)
    return df


def _load_trackman_pdf(uploaded_file) -> pd.DataFrame:
    """
    Best-effort parser for TrackMan 'Normalized' PDFs.

    We scan lines that contain 'Premium' and extract numeric fields after it.
    This mapping matches the common TrackMan shot-row layout.

    If your PDF format differs, CSV/XLSX is still recommended.
    """
    if PyPDF2 is None:
        raise RuntimeError("PyPDF2 not available in environment")

    try:
        data = uploaded_file.getvalue()
    except Exception:
        data = uploaded_file.read()

    from io import BytesIO

    reader = PyPDF2.PdfReader(BytesIO(data))
    full_text = ""
    for p in reader.pages:
        full_text += "\n" + (p.extract_text() or "")

    lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
    shot_lines = [ln for ln in lines if " premium " in f" {ln.lower()} "]

    rows = []
    for ln in shot_lines:
        # Use In Stat (optional)
        use_in_stat = None
        m_truefalse = re.search(r"\b(TRUE|FALSE)\b", ln, re.IGNORECASE)
        if m_truefalse:
            use_in_stat = m_truefalse.group(1).upper()

        if "Premium" not in ln:
            continue
        after = ln.split("Premium", 1)[1]

        floats = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", after)]
        if len(floats) < 30:
            continue

        # Index mapping validated against common TrackMan normalized PDFs
        row = {
            "Club Speed": floats[0],
            "Face To Path": floats[8],
            "Ball Speed": floats[9],
            "Smash Factor": floats[10],
            "Launch Angle": floats[11],
            "Launch Direction": floats[12],
            "Spin Rate": floats[13],
            "Carry Flat - Length": floats[22],
            "Carry Flat - Side": floats[23],
            "Carry Flat - Land Angle": floats[24],
            "Est. Total Flat - Side": floats[28],
            "Dynamic Lie": floats[29],
        }
        if use_in_stat is not None:
            row["Use In Stat"] = use_in_stat

        rows.append(row)

    return pd.DataFrame(rows)


def load_trackman(uploaded_file) -> pd.DataFrame:
    """
    Supports:
      - .csv
      - .xlsx
      - .pdf (best-effort)
    """
    name = getattr(uploaded_file, "name", "") or ""
    lower = name.lower()

    if lower.endswith(".pdf"):
        df = _load_trackman_pdf(uploaded_file)
    elif lower.endswith(".csv"):
        df = _read_csv_robust(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    df = _maybe_cleanup_trackman_export(df)
    df = _filter_use_in_stat(df)
    return df


def summarize_trackman(df: pd.DataFrame, shaft_tag: str, *, include_std: bool = True) -> Dict[str, float | str]:
    out: Dict[str, float | str] = {"Shaft ID": shaft_tag}

    try:
        out["Shot Count"] = int(len(df))
    except Exception:
        out["Shot Count"] = 0

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
