# core/efficiency_optimizer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EfficiencyConfig:
    # Targets / tolerances (starter values; tune later)
    LAUNCH_TARGET: float = 16.0
    LAUNCH_TOL: float = 4.0

    SPIN_TARGET: float = 5800.0
    SPIN_TOL: float = 1800.0

    SMASH_GOOD: float = 1.38

    FTP_SD_BAD: float = 4.0
    CARRY_SD_BAD: float = 12.0

    # Weights
    W_LAUNCH: float = 0.28
    W_SPIN: float = 0.28
    W_SMASH: float = 0.22
    W_DISP: float = 0.22

    # Confidence soft-filter thresholds
    MIN_SHOTS: int = 8
    WARN_FACE_TO_PATH_SD: float = 3.0
    WARN_CARRY_SD: float = 10.0
    WARN_SMASH_SD: float = 0.10


def _to_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, str) and x.strip() == "":
            return None
        return float(x)
    except Exception:
        return None


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _window_score(value: Optional[float], target: float, tol: float) -> float:
    if value is None or tol <= 0:
        return 0.0
    diff = abs(value - target)
    return _clamp01(1.0 - (diff / tol))


def _ratio_score(value: Optional[float], good: float) -> float:
    if value is None or good <= 0:
        return 0.0
    return _clamp01(value / good)


def _inverse_score(value: Optional[float], bad: float) -> float:
    if value is None or bad <= 0:
        return 0.0
    return _clamp01(1.0 - (value / bad))


def compute_efficiency_row(row: pd.Series, cfg: EfficiencyConfig) -> Dict[str, float]:
    launch = _to_float(row.get("Launch Angle"))
    spin = _to_float(row.get("Spin Rate"))
    smash = _to_float(row.get("Smash Factor"))
    ftp_sd = _to_float(row.get("Face To Path SD"))
    carry_sd = _to_float(row.get("Carry SD"))

    launch_s = _window_score(launch, cfg.LAUNCH_TARGET, cfg.LAUNCH_TOL)
    spin_s = _window_score(spin, cfg.SPIN_TARGET, cfg.SPIN_TOL)
    smash_s = _ratio_score(smash, cfg.SMASH_GOOD)

    ftp_s = _inverse_score(ftp_sd, cfg.FTP_SD_BAD)
    carry_s = _inverse_score(carry_sd, cfg.CARRY_SD_BAD)
    disp_s = (0.60 * ftp_s) + (0.40 * carry_s)

    eff = (
        cfg.W_LAUNCH * launch_s
        + cfg.W_SPIN * spin_s
        + cfg.W_SMASH * smash_s
        + cfg.W_DISP * disp_s
    )

    return {
        "launch_eff": round(launch_s * 100.0, 1),
        "spin_eff": round(spin_s * 100.0, 1),
        "smash_eff": round(smash_s * 100.0, 1),
        "dispersion_eff": round(disp_s * 100.0, 1),
        "efficiency_score": round(eff * 100.0, 1),
    }


def compute_confidence_row(row: pd.Series, cfg: EfficiencyConfig) -> Tuple[float, Dict[str, bool]]:
    shot_count = _to_float(row.get("Shot Count")) or 0.0
    ftp_sd = _to_float(row.get("Face To Path SD")) or 0.0
    carry_sd = _to_float(row.get("Carry SD")) or 0.0
    smash_sd = _to_float(row.get("Smash Factor SD")) or 0.0

    flags = {
        "low_shots": shot_count < float(cfg.MIN_SHOTS),
        "high_face_to_path_sd": ftp_sd > float(cfg.WARN_FACE_TO_PATH_SD),
        "high_carry_sd": carry_sd > float(cfg.WARN_CARRY_SD),
        "high_smash_sd": smash_sd > float(cfg.WARN_SMASH_SD),
    }

    conf = 100.0
    if flags["low_shots"]:
        missing = max(0.0, float(cfg.MIN_SHOTS) - shot_count)
        conf -= min(30.0, 6.0 * missing)

    if flags["high_face_to_path_sd"]:
        conf -= 18.0
    if flags["high_carry_sd"]:
        conf -= 18.0
    if flags["high_smash_sd"]:
        conf -= 12.0

    conf = _clamp01(conf / 100.0) * 100.0
    return round(conf, 1), flags


def build_comparison_table(
    lab_df: pd.DataFrame,
    *,
    baseline_shaft_id: Optional[str],
    cfg: EfficiencyConfig,
) -> pd.DataFrame:
    if lab_df is None or lab_df.empty:
        return pd.DataFrame()

    df = lab_df.copy()

    baseline_row = None
    if baseline_shaft_id:
        m = df["Shaft ID"].astype(str) == str(baseline_shaft_id)
        if m.any():
            baseline_row = df[m].iloc[0]

    def delta(col: str, row: pd.Series) -> Optional[float]:
        if baseline_row is None:
            return None
        a = _to_float(row.get(col))
        b = _to_float(baseline_row.get(col))
        if a is None or b is None:
            return None
        return a - b

    rows = []
    for _, r in df.iterrows():
        eff_parts = compute_efficiency_row(r, cfg)
        conf, flags = compute_confidence_row(r, cfg)

        smash = _to_float(r.get("Smash Factor"))
        carry_sd = _to_float(r.get("Carry SD"))
        ftp_sd = _to_float(r.get("Face To Path SD"))

        dispersion_display = ftp_sd if ftp_sd not in (None, 0) else carry_sd

        rows.append(
            {
                "Shaft": r.get("Shaft Label") or r.get("Shaft ID"),
                "Shaft ID": str(r.get("Shaft ID")),
                "Carry Δ": delta("Carry", r),
                "Launch Δ": delta("Launch Angle", r),
                "Spin Δ": delta("Spin Rate", r),
                "Smash": smash,
                "Dispersion": dispersion_display,
                "Efficiency": eff_parts["efficiency_score"],
                "Confidence": conf,
                "_flags": flags,
                "_eff_parts": eff_parts,
            }
        )

    out = pd.DataFrame(rows)
    out = out.sort_values(["Efficiency", "Confidence"], ascending=[False, False]).reset_index(drop=True)
    return out


def pick_efficiency_winner(table_df: pd.DataFrame) -> Optional[pd.Series]:
    if table_df is None or table_df.empty:
        return None
    return table_df.iloc[0]
