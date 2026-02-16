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

import io
import pandas as pd


def _looks_like_units_row(row_values) -> bool:
    """
    Returns True if a row looks like TrackMan unit labels: [mph], [deg], [rpm], [yds], [].
    """
    hits = 0
    total = 0
    for v in row_values:
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        total += 1
        if (s.startswith("[") and s.endswith("]")) or s == "[]":
            hits += 1
    return total > 0 and (hits / total) >= 0.4


def _build_columns_from_header_and_units(header_row, units_row=None):
    cols = []
    for i, name in enumerate(header_row):
        n = "" if name is None else str(name).strip()
        u = ""
        if units_row is not None and i < len(units_row):
            u = "" if units_row[i] is None else str(units_row[i]).strip()

        if u and ((u.startswith("[") and u.endswith("]")) or u == "[]"):
            col = f"{n} {u}".strip()
        else:
            col = n

        cols.append(col if col else f"Col_{i}")
    return cols


def _read_excel_raw(uploaded_file) -> pd.DataFrame:
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    data = uploaded_file.read()
    return pd.read_excel(io.BytesIO(data), sheet_name=0, header=None)


def _read_csv_best_effort(uploaded_file) -> pd.DataFrame:
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    data = uploaded_file.read()
    try:
        return pd.read_csv(io.BytesIO(data))
    except Exception:
        return pd.read_csv(io.BytesIO(data), sep=None, engine="python")


import io
import pandas as pd
import numpy as np


def _looks_like_units_row(row_values) -> bool:
    hits = 0
    total = 0
    for v in row_values:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        s = str(v).strip()
        if not s:
            continue
        total += 1
        if (s.startswith("[") and s.endswith("]")) or s == "[]":
            hits += 1
    return total > 0 and (hits / total) >= 0.35  # allow sparse unit rows


def _make_unique_columns(cols):
    """
    TrackMan exports can contain duplicate header names.
    If columns are duplicated, df[col] returns a DataFrame -> breaks to_numeric.
    This makes them unique by appending .2, .3, etc.
    """
    counts = {}
    out = []
    for c in cols:
        c = str(c).strip()
        if c not in counts:
            counts[c] = 1
            out.append(c)
        else:
            counts[c] += 1
            out.append(f"{c}.{counts[c]}")
    return out


def _build_columns_from_header_and_units(header_row, units_row=None):
    cols = []
    for i, name in enumerate(header_row):
        n = "" if name is None or (isinstance(name, float) and np.isnan(name)) else str(name).strip()
        u = ""
        if units_row is not None and i < len(units_row):
            uu = units_row[i]
            u = "" if uu is None or (isinstance(uu, float) and np.isnan(uu)) else str(uu).strip()

        if u and ((u.startswith("[") and u.endswith("]")) or u == "[]"):
            col = f"{n} {u}".strip()
        else:
            col = n

        cols.append(col if col else f"Col_{i}")

    return _make_unique_columns(cols)


def _read_excel_raw(uploaded_file) -> pd.DataFrame:
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    data = uploaded_file.read()
    return pd.read_excel(io.BytesIO(data), sheet_name=0, header=None)


def _read_csv_best_effort(uploaded_file) -> pd.DataFrame:
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    data = uploaded_file.read()
    try:
        return pd.read_csv(io.BytesIO(data))
    except Exception:
        return pd.read_csv(io.BytesIO(data), sep=None, engine="python")


def load_trackman(uploaded_file) -> pd.DataFrame:
    """
    Robust loader for TrackMan CSV/XLSX (including Normalized XLSX with embedded headers).
    Fixes duplicate column names and avoids 2-D to_numeric crashes.
    """
    name = getattr(uploaded_file, "name", "") or ""
    lower = name.lower()

    # ---- CSV ----
    if lower.endswith(".csv"):
        df = _read_csv_best_effort(uploaded_file)
        if df is None or df.empty:
            return pd.DataFrame()
        df.columns = _make_unique_columns([str(c).strip() for c in df.columns])
        return df

    # ---- XLSX ----
    if not (lower.endswith(".xlsx") or lower.endswith(".xls")):
        raise ValueError("Unsupported file type")

    raw = _read_excel_raw(uploaded_file)
    if raw is None or raw.empty:
        return pd.DataFrame()

    # Find header row by searching for "TMD No"
    header_idx = None
    for i in range(min(len(raw), 40)):
        row = raw.iloc[i].tolist()
        row_str = [
            str(x).strip().lower()
            if x is not None and not (isinstance(x, float) and np.isnan(x))
            else ""
            for x in row
        ]
        if "tmd no" in row_str:
            header_idx = i
            break

    if header_idx is None:
        header_idx = 0

    header_row = raw.iloc[header_idx].tolist()

    units_row = None
    if header_idx + 1 < len(raw):
        candidate_units = raw.iloc[header_idx + 1].tolist()
        if _looks_like_units_row(candidate_units):
            units_row = candidate_units

    cols = _build_columns_from_header_and_units(header_row, units_row=units_row)

    data_start = header_idx + 1 + (1 if units_row is not None else 0)
    out = raw.iloc[data_start:].copy()
    out.columns = cols

    # Drop fully-empty columns and reset index
    out = out.dropna(axis=1, how="all").reset_index(drop=True)

    # Safe numeric coercion: only attempt on 1-D Series columns
    for c in list(out.columns):
        try:
            s = out[c]
            if isinstance(s, pd.Series):
                out[c] = pd.to_numeric(s, errors="coerce")
        except Exception:
            # Leave as-is if conversion fails
            pass

    return out



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


import io
import pandas as pd


def debug_trackman(uploaded_file):
    """
    Safe debug helper for TrackMan uploads.
    Returns:
      {
        "ok": bool,
        "error": str (if not ok),
        "rows_after_cleanup": int,
        "columns": list[str],
        "head_preview": pd.DataFrame
      }
    Never throws.
    """
    try:
        name = getattr(uploaded_file, "name", "") or ""

        # Make sure we can read from the start
        try:
            uploaded_file.seek(0)
        except Exception:
            pass

        data = uploaded_file.read()
        if not data:
            return {"ok": False, "error": "Empty upload stream (no bytes read)."}

        # Wrap bytes in a fresh file-like object so downstream reads are reliable
        buf = io.BytesIO(data)
        try:
            buf.name = name
        except Exception:
            pass

        # Try your main loader first
        try:
            df = load_trackman(buf)
            cols = [str(c) for c in getattr(df, "columns", [])]
            head = df.head(15).copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
            return {
                "ok": True,
                "rows_after_cleanup": int(len(df)) if isinstance(df, pd.DataFrame) else 0,
                "columns": cols[:200],
                "head_preview": head,
            }
        except Exception as e_load:
            # Fallback: raw read to at least show what the sheet looks like
            try:
                buf2 = io.BytesIO(data)
                try:
                    buf2.name = name
                except Exception:
                    pass

                if name.lower().endswith(".csv"):
                    df_raw = pd.read_csv(buf2, header=None)
                else:
                    df_raw = pd.read_excel(buf2, sheet_name=0, header=None)

                head = df_raw.head(15).copy()
                cols = [f"Col_{i}" for i in range(df_raw.shape[1])] if df_raw is not None else []
                return {
                    "ok": False,
                    "error": f"load_trackman failed: {e_load}",
                    "rows_after_cleanup": int(len(df_raw)) if isinstance(df_raw, pd.DataFrame) else 0,
                    "columns": cols[:200],
                    "head_preview": head,
                }
            except Exception as e_fallback:
                return {"ok": False, "error": f"Debug fallback failed: {e_fallback}"}

    except Exception as e:
        return {"ok": False, "error": str(e)}

