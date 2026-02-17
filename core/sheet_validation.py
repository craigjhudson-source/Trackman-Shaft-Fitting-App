# core/sheet_validation.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd


# -----------------------------
# Report structure
# -----------------------------
@dataclass
class ValidationMessage:
    level: str  # "error" | "warn" | "info"
    code: str
    message: str
    fix: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    ok: bool
    errors: List[ValidationMessage] = field(default_factory=list)
    warnings: List[ValidationMessage] = field(default_factory=list)
    infos: List[ValidationMessage] = field(default_factory=list)

    def add(self, level: str, code: str, message: str, fix: Optional[str] = None, **context: Any) -> None:
        msg = ValidationMessage(level=level, code=code, message=message, fix=fix, context=context)
        if level == "error":
            self.errors.append(msg)
        elif level == "warn":
            self.warnings.append(msg)
        else:
            self.infos.append(msg)
        self.ok = (len(self.errors) == 0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [m.__dict__ for m in self.errors],
            "warnings": [m.__dict__ for m in self.warnings],
            "infos": [m.__dict__ for m in self.infos],
        }


# -----------------------------
# Helpers
# -----------------------------
def _has_tab(data: Dict[str, pd.DataFrame], tab: str) -> bool:
    return tab in data and isinstance(data.get(tab), pd.DataFrame)


def _norm_col(c: str) -> str:
    return str(c).strip()


def _cols(df: pd.DataFrame) -> List[str]:
    return [_norm_col(c) for c in list(df.columns)]


def _get_cfg_value(cfg_df: pd.DataFrame, key: str) -> Optional[str]:
    """
    Config sheet design in your workbook is "wide" (keys are columns).
    So "MIN_SHOTS" etc are columns.
    """
    if cfg_df is None or cfg_df.empty:
        return None
    cols = _cols(cfg_df)
    if key not in cols:
        return None
    # Try to find first non-empty value in that column
    s = cfg_df[key].astype(str).str.strip()
    s = s[s.notna() & (s != "") & (s.str.lower() != "nan")]
    if len(s) == 0:
        return None
    return str(s.iloc[0]).strip()


def _to_float(x: Optional[str]) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(str(x).strip())
    except Exception:
        return None


def _nonempty(df: pd.DataFrame) -> bool:
    return isinstance(df, pd.DataFrame) and (not df.empty) and (len(df.columns) > 0)


# -----------------------------
# Main validator
# -----------------------------
def validate_sheet_data(data: Dict[str, pd.DataFrame]) -> ValidationReport:
    """
    Validates the Google Sheet dataframes BEFORE the rest of the app runs.

    This should NEVER raise. It returns a report so the app can:
      - keep running
      - show precise warnings
      - avoid silent failures
    """
    report = ValidationReport(ok=True)

    if not isinstance(data, dict) or len(data) == 0:
        report.add(
            "error",
            "NO_DATA",
            "No sheet data provided to validator.",
            fix="Ensure the app successfully loaded the Google Sheet and passed a dict of DataFrames into validate_sheet_data().",
        )
        return report

    # ---- Tab existence (core)
    required_tabs = ["Heads", "Shafts", "Questions", "Config"]
    for tab in required_tabs:
        if not _has_tab(data, tab) or not _nonempty(data[tab]):
            report.add(
                "error",
                f"MISSING_TAB_{tab.upper()}",
                f"Missing or empty required sheet tab: '{tab}'.",
                fix=f"Confirm the Google Sheet has a tab named exactly '{tab}' with headers + at least 1 row of data.",
            )

    # Optional tabs
    for tab in ["Fittings", "Descriptions", "Responses", "AI_Context"]:
        if tab in data and not isinstance(data.get(tab), pd.DataFrame):
            report.add(
                "warn",
                f"BAD_TAB_TYPE_{tab.upper()}",
                f"Tab '{tab}' exists but is not a DataFrame.",
                fix="Ensure the data loader returns pandas DataFrames for each tab.",
            )

    # Stop early if core tabs missing (prevents noisy downstream checks)
    if len(report.errors) > 0:
        return report

    heads_df = data.get("Heads", pd.DataFrame())
    shafts_df = data.get("Shafts", pd.DataFrame())
    q_df = data.get("Questions", pd.DataFrame())
    cfg_df = data.get("Config", pd.DataFrame())
    fittings_df = data.get("Fittings", pd.DataFrame()) if _has_tab(data, "Fittings") else pd.DataFrame()
    desc_df = data.get("Descriptions", pd.DataFrame()) if _has_tab(data, "Descriptions") else pd.DataFrame()

    # ---- Shafts required columns
    shafts_required = ["ID", "ShaftTag"]
    shafts_cols = _cols(shafts_df)
    for c in shafts_required:
        if c not in shafts_cols:
            report.add(
                "error",
                f"SHAFTS_MISSING_COL_{c}",
                f"Shafts tab missing required column '{c}'.",
                fix="Add the column exactly as named (case-sensitive) or update the loader to preserve headers.",
            )

    # Duplicate Shaft IDs check
    if "ID" in shafts_cols and _nonempty(shafts_df):
        ids = shafts_df["ID"].astype(str).str.strip()
        ids = ids[ids.notna() & (ids != "") & (ids.str.lower() != "nan")]
        dupes = ids[ids.duplicated()].unique().tolist()
        if dupes:
            report.add(
                "error",
                "SHAFTS_DUPLICATE_ID",
                f"Duplicate Shaft IDs found: {dupes[:10]}{'...' if len(dupes) > 10 else ''}",
                fix="Shafts.ID must be unique. Make duplicates unique or merge rows.",
                duplicates=dupes,
            )

    # ---- Questions required columns
    q_required = ["QID", "Question", "Category", "InputType"]
    q_cols = _cols(q_df)
    for c in q_required:
        if c not in q_cols:
            report.add(
                "error",
                f"QUESTIONS_MISSING_COL_{c}",
                f"Questions tab missing required column '{c}'.",
                fix="Restore the Questions sheet headers exactly (QID/Question/Category/InputType...).",
            )

    # QID duplicates check
    if "QID" in q_cols and _nonempty(q_df):
        qids = q_df["QID"].astype(str).str.strip()
        qids = qids[qids.notna() & (qids != "") & (qids.str.lower() != "nan")]
        dup_qids = qids[qids.duplicated()].unique().tolist()
        if dup_qids:
            report.add(
                "error",
                "QUESTIONS_DUPLICATE_QID",
                f"Duplicate QIDs found: {dup_qids[:10]}{'...' if len(dup_qids) > 10 else ''}",
                fix="Each Questions.QID must be unique.",
                duplicates=dup_qids,
            )

    # ---- Config checks
    cfg_cols = _cols(cfg_df)
    if not cfg_cols:
        report.add(
            "error",
            "CONFIG_EMPTY",
            "Config tab appears empty or has no columns.",
            fix="Config must contain headers (keys) and option rows.",
        )

    # MIN_SHOTS sanity
    min_shots_raw = _get_cfg_value(cfg_df, "MIN_SHOTS")
    min_shots = _to_float(min_shots_raw)
    if min_shots is None:
        report.add(
            "warn",
            "CFG_MIN_SHOTS_MISSING",
            "Config key MIN_SHOTS not found or has no value.",
            fix="Add a column header MIN_SHOTS to Config and place a value like 5 or 7 in the first row.",
        )
    else:
        if min_shots <= 0:
            report.add(
                "warn",
                "CFG_MIN_SHOTS_ZERO",
                f"MIN_SHOTS is set to {min_shots_raw}. This disables shot-count confidence gates.",
                fix="Set MIN_SHOTS to something real (recommended 5–7) so confidence scoring means something.",
                value=min_shots_raw,
            )
        elif min_shots < 3:
            report.add(
                "info",
                "CFG_MIN_SHOTS_LOW",
                f"MIN_SHOTS is {min_shots_raw}. That’s very low for stable variance estimates.",
                fix="Consider 5–7 for tighter confidence scoring.",
                value=min_shots_raw,
            )

    # ---- Fittings tab landmine: Environment spelling
    if _nonempty(fittings_df):
        f_cols = _cols(fittings_df)
        has_correct = "Fitting Environment" in f_cols
        has_wrong = "Fitting Enviroment" in f_cols  # common misspelling we saw
        if has_wrong and not has_correct:
            report.add(
                "warn",
                "FITTINGS_ENV_SPELLING",
                "Fittings column is 'Fitting Enviroment' (misspelled). This can cause blanks or failed lookups.",
                fix="Rename the Fittings header to exactly: Fitting Environment",
                found="Fitting Enviroment",
                expected="Fitting Environment",
            )
        elif not has_correct and not has_wrong:
            report.add(
                "info",
                "FITTINGS_ENV_MISSING",
                "Fittings tab does not include a Fitting Environment column (or it’s named differently).",
                fix="If you want to write Q22 into Fittings, add the column header: Fitting Environment",
            )

    # ---- Descriptions join risk (Model text mismatches)
    # We cannot guarantee how your code joins, but we can flag mismatch risk early.
    if _nonempty(desc_df) and _nonempty(shafts_df):
        desc_cols = _cols(desc_df)
        # common patterns: "Model", "Description", "Verdict"
        model_col = None
        for candidate in ["Model", "Shaft", "ShaftModel", "Name"]:
            if candidate in desc_cols:
                model_col = candidate
                break
        if model_col is None:
            report.add(
                "info",
                "DESC_NO_MODEL_COL",
                "Descriptions tab exists but has no obvious Model column (Model/Shaft/Name).",
                fix="If you plan to use this tab, ensure it has a Model column or (better) move blurbs into Shafts.Description keyed by ID.",
            )
        else:
            # check overlap with shafts Model column if present
            shafts_model_col = "Model" if "Model" in shafts_cols else None
            if shafts_model_col is None:
                report.add(
                    "info",
                    "SHAFTS_NO_MODEL_COL",
                    "Shafts tab has no 'Model' column. Any Descriptions join-by-model is likely fragile.",
                    fix="Best practice: store the verdict blurb in Shafts.Description (keyed by Shafts.ID).",
                )
            else:
                a = set(desc_df[model_col].astype(str).str.strip())
                b = set(shafts_df[shafts_model_col].astype(str).str.strip())
                a = {x for x in a if x and x.lower() != "nan"}
                b = {x for x in b if x and x.lower() != "nan"}
                if a and b:
                    overlap = len(a.intersection(b))
                    ratio = overlap / max(1, len(a))
                    if ratio < 0.60:
                        report.add(
                            "warn",
                            "DESC_JOIN_MISMATCH_RISK",
                            f"Descriptions '{model_col}' values poorly overlap Shafts.Model (overlap {overlap}/{len(a)}). Likely join mismatches.",
                            fix="Move blurbs into Shafts.Description keyed by Shafts.ID, or change Descriptions to be keyed by ShaftID.",
                            overlap=overlap,
                            desc_count=len(a),
                            shafts_model_count=len(b),
                        )

    # ---- Responses tab likely deprecated
    if _has_tab(data, "Responses"):
        r_df = data.get("Responses", pd.DataFrame())
        if _nonempty(r_df):
            r_cols = _cols(r_df)
            # heuristic: if it references Q17 but Questions doesn't contain it, warn
            if "QID" in r_cols and "QID" in q_cols:
                qids = set(q_df["QID"].astype(str).str.strip())
                rqids = set(r_df["QID"].astype(str).str.strip())
                missing = sorted([x for x in rqids if x and x.lower() != "nan" and x not in qids])
                if missing:
                    report.add(
                        "info",
                        "RESPONSES_ORPHAN_QIDS",
                        f"Responses tab includes QIDs not found in Questions: {missing[:10]}{'...' if len(missing) > 10 else ''}",
                        fix="If Responses is obsolete, consider archiving it. If not obsolete, align QIDs with Questions.",
                        missing_qids=missing,
                    )

    return report


# -----------------------------
# Streamlit rendering helper
# -----------------------------
def render_report_streamlit(report: ValidationReport) -> None:
    """
    Optional Streamlit UI helper. Import and call this from app.py.
    This function is safe to call even if report is empty.
    """
    import streamlit as st  # local import keeps core clean

    if report is None:
        return

    if report.errors:
        st.error("🚫 Sheet Validation Errors (app may not function correctly):")
        for m in report.errors:
            st.write(f"**[{m.code}]** {m.message}")
            if m.fix:
                st.caption(f"Fix: {m.fix}")

    if report.warnings:
        st.warning("⚠️ Sheet Validation Warnings:")
        for m in report.warnings:
            st.write(f"**[{m.code}]** {m.message}")
            if m.fix:
                st.caption(f"Fix: {m.fix}")

    # keep infos collapsed so UI stays clean
    if report.infos:
        with st.expander("ℹ️ Sheet Validation Info", expanded=False):
            for m in report.infos:
                st.write(f"**[{m.code}]** {m.message}")
                if m.fix:
                    st.caption(f"Fix: {m.fix}")
