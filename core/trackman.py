# core/trackman.py
from __future__ import annotations

import io
import re
from typing import Dict, List, Optional

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


def _maybe_cleanup_trackman_export(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    headers_are_default = all(str(c).strip().isdigit() for c in df.columns)

    def row_contains_keywords(row_idx: int) -> bool:
        if row_idx < 0 or row_idx >= len(df):
            return False
        row = df.iloc[row_idx].astype(str).str.lower()
        joined = " | ".join(row.tolist())
        return ("club speed" in joined) or ("ball speed" in joined) or ("smash" in joined) or ("spin rate" in joined)

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
        unit_hits = vals.str.contains(r"\b(mph|rpm|deg|°|m/s|yd|yards|ft|in|mm|s)\b", regex=True, na=False).sum()
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


def _read_csv_handle_sep_line(uploaded_file) -> pd.DataFrame:
    """
    TrackMan sometimes outputs:
      sep=,
      Date, TMD No, ... (real header lives in the first data row)
    Pandas will treat 'sep=' as header unless we skip it.
    """
    # Read raw bytes so we can inspect first line safely
    raw = uploaded_file.read()
    try:
        text = raw.decode("utf-8-sig", errors="ignore")
    except Exception:
        text = raw.decode(errors="ignore")

    lines = text.splitlines()
    if lines and lines[0].strip().lower().startswith("sep="):
        text = "\n".join(lines[1:])

    return pd.read_csv(io.StringIO(text))


def load_trackman(uploaded_file) -> pd.DataFrame:
    name = getattr(uploaded_file, "name", "") or ""
    if name.lower().endswith(".csv"):
        df = _read_csv_handle_sep_line(uploaded_file)
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
