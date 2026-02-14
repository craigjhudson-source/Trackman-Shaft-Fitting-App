# core/trackman.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd


# Canonical metric -> list of substrings/aliases to match.
# We match by "contains" after normalizing columns (lowercase, remove units/brackets/punct).
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

# Optional: extra dispersion-ish fields if present
DISPERSION_ALIASES: Dict[str, List[str]] = {
    "carry_side": ["carry flat - side", "carry side"],
    "total_side": ["est. total flat - side", "total side"],
    "launch_dir": ["launch direction"],
}


def _norm_col(col: str) -> str:
    """Normalize a TrackMan column name to improve fuzzy matching."""
    c = str(col).strip().lower()
    c = re.sub(r"\[[^\]]*\]", "", c)  # remove [mph], [rpm], etc.
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


def load_trackman(uploaded_file) -> pd.DataFrame:
    """Load TrackMan export CSV/XLSX into a DataFrame."""
    name = getattr(uploaded_file, "name", "") or ""
    if name.lower().endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
    return df


def summarize_trackman(
    df: pd.DataFrame,
    shaft_tag: str,
    *,
    include_std: bool = True,
) -> Dict[str, float | str]:
    """
    Returns a single-row summary dict: means (and optional std devs).
    Keys are human-friendly labels used by the Streamlit table.
    """
    out: Dict[str, float | str] = {"Shaft ID": shaft_tag}

    def add_metric(label: str, canon_key: str) -> None:
        col = _find_col(df, METRIC_ALIASES.get(canon_key, []))
        if not col:
            return
        s = pd.to_numeric(df[col], errors="coerce")
        if s.notna().any():
            out[label] = round(float(s.mean()), 2)
            if include_std:
                out[f"{label} SD"] = round(float(s.std(ddof=0)), 2)

    # Core means you’ll want for Phase 4/5/6
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

    # Optional dispersion helpers if present
    def add_disp(label: str, aliases: List[str]) -> None:
        col = _find_col(df, aliases)
        if not col:
            return
        s = pd.to_numeric(df[col], errors="coerce")
        if s.notna().any():
            out[label] = round(float(s.mean()), 2)
            if include_std:
                out[f"{label} SD"] = round(float(s.std(ddof=0)), 2)

    for label, aliases in DISPERSION_ALIASES.items():
        pretty = {
            "carry_side": "Carry Side",
            "total_side": "Total Side",
            "launch_dir": "Launch Direction",
        }[label]
        add_disp(pretty, aliases)

    return out
