# core/trackman.py
from __future__ import annotations

import re
from typing import Dict, List, Optional, Any

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
    """
    Finds the first matching column based on normalized header text.
    Also supports deduped headers like "Club Speed__1" by stripping "__<n>".
    """
    if df is None or df.empty:
        return None

    def strip_suffix(x: str) -> str:
        return re.sub(r"__\d+$", "", x)

    norm_map = {c: _norm_col(strip_suffix(str(c))) for c in df.columns}

    for col, n in norm_map.items():
        for a in aliases:
            if a in n:
                return col
    return None


def _dedupe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure unique column names (PyArrow/Streamlit hard-fails on duplicates).
    """
    if df is None or df.empty:
        return df
    cols = [str(c) for c in df.columns]
    seen = {}
    new_cols = []
    for c in cols:
        if c in seen:
            seen[c] += 1
            new_cols.append(f"{c}__{seen[c]}")
        else:
            seen[c] = 0
            new_cols.append(c)
    df = df.copy()
    df.columns = new_cols
    return df


def _maybe_cleanup_trackman_export(df: pd.DataFrame) -> pd.DataFrame:
    """
    Attempts to clean common TrackMan CSV/XLSX shapes:
      - junk title rows
      - header row living in row 0 or row 1
      - units row ("mph", "rpm", "deg") that breaks numeric parsing
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
            or ("carry" in joined)
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

    return df


def load_trackman(uploaded_file) -> pd.DataFrame:
    """
    Reads CSV/XLSX. (PDF handled in app.py with a message; we do not parse it here.)
    """
    name = getattr(uploaded_file, "name", "") or ""
    if name.lower().endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    df = _maybe_cleanup_trackman_export(df)
    df = _filter_use_in_stat(df)

    # IMPORTANT: make columns unique for Streamlit/Arrow + stable matching
    df = _dedupe_columns(df)

    return df


def summarize_trackman(
    df: pd.DataFrame,
    shaft_tag: str,
    *,
    include_std: bool = True
) -> Dict[str, float | str]:
    out: Dict[str, float | str] = {"Shaft ID": shaft_tag}

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


def debug_trackman(uploaded_file) -> Dict[str, Any]:
    """
    Returns a debug bundle to help you see exactly what the parser read.
    Safe for Streamlit display (preview df will be deduped).
    """
    try:
        df = load_trackman(uploaded_file)
        cols = [str(c) for c in df.columns]

        preview = df.head(12).copy()
        # Extra-safe: ensure no dupes for arrow conversion
        preview = _dedupe_columns(preview)

        return {
            "ok": True,
            "rows_after_cleanup": int(len(df)),
            "columns": cols[:200],
            "head_preview": preview,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
