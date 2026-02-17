# core/sheet_validation.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import pandas as pd
import streamlit as st


# ------------------ Models ------------------
@dataclass
class Issue:
    level: str  # "error" | "warn" | "info"
    code: str
    message: str
    fix: str = ""
    details: Optional[Any] = None


@dataclass
class ValidationReport:
    errors: List[Issue] = field(default_factory=list)
    warnings: List[Issue] = field(default_factory=list)
    info: List[Issue] = field(default_factory=list)

    def add(self, issue: Issue) -> None:
        if issue.level == "error":
            self.errors.append(issue)
        elif issue.level == "warn":
            self.warnings.append(issue)
        else:
            self.info.append(issue)


# ------------------ Helpers ------------------
def _df_has_cols(df: pd.DataFrame, cols: List[str]) -> bool:
    if df is None or df.empty:
        return False
    present = set([str(c).strip() for c in df.columns])
    return all(c in present for c in cols)


def _safe_cols(df: pd.DataFrame) -> List[str]:
    if df is None:
        return []
    return [str(c) for c in getattr(df, "columns", [])]


def _to_str_list(values) -> List[str]:
    out: List[str] = []
    for v in values:
        s = str(v).strip()
        if s:
            out.append(s)
    return out


def _config_columns(cfg_df: pd.DataFrame) -> List[str]:
    if cfg_df is None or cfg_df.empty:
        return []
    return [str(c).strip() for c in cfg_df.columns if str(c).strip()]


# ------------------ Validation ------------------
def validate_sheet_data(all_data: Dict[str, pd.DataFrame]) -> ValidationReport:
    """
    Validate the loaded sheet tabs/columns and report common foot-guns.

    IMPORTANT:
      - We do NOT attempt to enforce business logic here.
      - This is structural validation to prevent app breakage and silent misconfig.
    """
    report = ValidationReport()

    # --- Required tabs ---
    required_tabs = ["Heads", "Shafts", "Questions", "Config", "Descriptions"]
    for tab in required_tabs:
        if tab not in all_data or all_data[tab] is None:
            report.add(
                Issue(
                    level="error",
                    code="TAB_MISSING",
                    message=f"Missing required tab: '{tab}'",
                    fix=f"Create a tab named '{tab}' in the Google Sheet.",
                    details={"tab": tab},
                )
            )

    # If any required tab is missing, further checks may be unreliable
    # but we can still continue and surface more context.
    heads_df = all_data.get("Heads", pd.DataFrame())
    shafts_df = all_data.get("Shafts", pd.DataFrame())
    q_df = all_data.get("Questions", pd.DataFrame())
    cfg_df = all_data.get("Config", pd.DataFrame())
    desc_df = all_data.get("Descriptions", pd.DataFrame())
    resp_df = all_data.get("Responses", pd.DataFrame())  # may be obsolete/archived
    fittings_df = all_data.get("Fittings", pd.DataFrame())

    # --- Questions columns ---
    q_required = ["Category", "QuestionID", "QuestionText", "InputType", "Options"]
    if q_df is None or q_df.empty:
        report.add(
            Issue(
                level="error",
                code="QUESTIONS_EMPTY",
                message="Questions tab is empty or unreadable.",
                fix="Ensure the Questions tab has a header row and data rows.",
                details={"columns": _safe_cols(q_df)},
            )
        )
    else:
        missing = [c for c in q_required if c not in _safe_cols(q_df)]
        if missing:
            report.add(
                Issue(
                    level="error",
                    code="QUESTIONS_COLS_MISSING",
                    message=f"Questions tab missing required columns: {missing}",
                    fix="Add the missing columns (spelling must match exactly).",
                    details={"present": _safe_cols(q_df)},
                )
            )

        # Duplicate QuestionIDs
        if "QuestionID" in q_df.columns:
            qids = q_df["QuestionID"].astype(str).str.strip()
            dups = qids[qids != ""].value_counts()
            dups = dups[dups > 1]
            if len(dups) > 0:
                report.add(
                    Issue(
                        level="warn",
                        code="QUESTIONS_DUPLICATE_QIDS",
                        message=f"Duplicate QuestionIDs detected: {list(dups.index)[:20]}",
                        fix="Each QuestionID should be unique (including sub-IDs like Q16_1, Q16_2).",
                        details={"duplicates": dups.to_dict()},
                    )
                )

        # Config-driven dropdown keys must exist as Config columns
        if "Options" in q_df.columns and cfg_df is not None and not cfg_df.empty:
            cfg_cols = set(_config_columns(cfg_df))
            bad_cfg_keys: List[str] = []
            for opt in q_df["Options"].astype(str).tolist():
                s = str(opt).strip()
                if s.lower().startswith("config:"):
                    key = s.split(":", 1)[1].strip()
                    if key and key not in cfg_cols:
                        bad_cfg_keys.append(key)
            bad_cfg_keys = sorted(list(dict.fromkeys([k for k in bad_cfg_keys if k])))
            if bad_cfg_keys:
                report.add(
                    Issue(
                        level="warn",
                        code="CONFIG_KEYS_MISSING_FOR_QUESTIONS",
                        message=f"Some Questions reference Config keys that do not exist as Config columns: {bad_cfg_keys}",
                        fix="Either create those Config columns (exact spelling) or fix the Questions.Options values.",
                        details={"missing_keys": bad_cfg_keys, "config_columns": sorted(list(cfg_cols))},
                    )
                )

    # --- Config sanity ---
    if cfg_df is None or cfg_df.empty:
        report.add(
            Issue(
                level="error",
                code="CONFIG_EMPTY",
                message="Config tab is empty or unreadable.",
                fix="Ensure Config has a header row and at least one row of values.",
                details={"columns": _safe_cols(cfg_df)},
            )
        )
    else:
        if "MIN_SHOTS" not in cfg_df.columns:
            report.add(
                Issue(
                    level="warn",
                    code="CFG_MIN_SHOTS_MISSING",
                    message="Config is missing MIN_SHOTS; app will use default.",
                    fix="Add a Config column MIN_SHOTS (first row value like 8 or 10).",
                )
            )

    # --- Shafts sanity ---
    if shafts_df is None or shafts_df.empty:
        report.add(
            Issue(
                level="error",
                code="SHAFTS_EMPTY",
                message="Shafts tab is empty or unreadable.",
                fix="Ensure Shafts has a header row and data rows.",
                details={"columns": _safe_cols(shafts_df)},
            )
        )
    else:
        # Not all columns are required for UI, but ID is very important.
        if "ID" not in shafts_df.columns:
            report.add(
                Issue(
                    level="error",
                    code="SHAFTS_ID_MISSING",
                    message="Shafts tab is missing required column: 'ID'",
                    fix="Add an 'ID' column to Shafts and ensure each shaft has a stable numeric/string ID.",
                    details={"present": _safe_cols(shafts_df)},
                )
            )
        # Soft checks
        for col in ["Brand", "Model", "Flex"]:
            if col not in shafts_df.columns:
                report.add(
                    Issue(
                        level="warn",
                        code="SHAFTS_COL_MISSING",
                        message=f"Shafts tab missing column '{col}'. Some dropdowns/labels may degrade.",
                        fix=f"Add column '{col}' for best UX.",
                        details={"present": _safe_cols(shafts_df)},
                    )
                )

    # --- Heads sanity ---
    if heads_df is None or heads_df.empty:
        report.add(
            Issue(
                level="warn",
                code="HEADS_EMPTY",
                message="Heads tab is empty or unreadable. Head dropdowns may not work correctly.",
                fix="Ensure Heads has a header row and data rows.",
                details={"columns": _safe_cols(heads_df)},
            )
        )
    else:
        # Heads columns are used heuristically, so only warn.
        if "Manufacturer" not in heads_df.columns:
            report.add(
                Issue(
                    level="warn",
                    code="HEADS_MANUFACTURER_MISSING",
                    message="Heads tab missing column 'Manufacturer'. The app will fall back to the first column for brands.",
                    fix="Add a 'Manufacturer' column for best UX.",
                    details={"present": _safe_cols(heads_df)},
                )
            )
        if "Model" not in heads_df.columns:
            report.add(
                Issue(
                    level="warn",
                    code="HEADS_MODEL_MISSING",
                    message="Heads tab missing column 'Model'. Model dropdown may degrade.",
                    fix="Add a 'Model' column for best UX.",
                    details={"present": _safe_cols(heads_df)},
                )
            )

    # --- Descriptions sanity ---
    if desc_df is None or desc_df.empty:
        report.add(
            Issue(
                level="warn",
                code="DESCRIPTIONS_EMPTY",
                message="Descriptions tab is empty. Verdict blurbs will fall back to a generic message.",
                fix="Populate Descriptions with at least 'Model' and 'Blurb'.",
                details={"columns": _safe_cols(desc_df)},
            )
        )
    else:
        if "Model" not in desc_df.columns or "Blurb" not in desc_df.columns:
            report.add(
                Issue(
                    level="warn",
                    code="DESCRIPTIONS_COLS_MISSING",
                    message="Descriptions should include 'Model' and 'Blurb' columns for best report quality.",
                    fix="Add missing columns and map each shaft model to a blurb.",
                    details={"present": _safe_cols(desc_df)},
                )
            )

    # --- Responses orphan check (info-level) ---
    # You archived Responses; this should not break anything.
    if resp_df is not None and not resp_df.empty and _df_has_cols(resp_df, ["QuestionID", "ResponseOption"]):
        if q_df is not None and not q_df.empty and "QuestionID" in q_df.columns:
            qids = set(_to_str_list(q_df["QuestionID"].astype(str).tolist()))
            rids = set(_to_str_list(resp_df["QuestionID"].astype(str).tolist()))
            orphan = sorted([x for x in rids if x and x not in qids])
            if orphan:
                report.add(
                    Issue(
                        level="info",
                        code="RESPONSES_ORPHAN_QIDS",
                        message=f"Responses tab includes question IDs not found in Questions: {orphan}",
                        fix="If Responses is obsolete, consider archiving it. If not obsolete, align IDs with Questions.",
                        details={"orphan_ids": orphan},
                    )
                )
    else:
        # If Responses is missing/empty, we treat as info (common in your new sheet-driven design).
        report.add(
            Issue(
                level="info",
                code="RESPONSES_EMPTY_OR_ARCHIVED",
                message="Responses tab is empty/missing (OK). Dropdowns should be driven by Config and dynamic lookups.",
                fix="No action needed unless you want Responses as a fallback source again.",
            )
        )

    # --- Fittings tab presence (soft) ---
    if fittings_df is None or fittings_df.empty:
        report.add(
            Issue(
                level="info",
                code="FITTINGS_EMPTY_OR_UNLOADED",
                message="Fittings tab is empty/unloaded. Saving interview results may fail if the tab doesn't exist.",
                fix="Ensure a tab named 'Fittings' exists with a header row if you want to store fittings.",
                details={"columns": _safe_cols(fittings_df)},
            )
        )

    return report


# ------------------ Rendering ------------------
def render_report_streamlit(
    report: ValidationReport,
    *,
    title: str = "Sheet Validation",
    show_info: bool = True,
) -> None:
    """
    Render a compact validation report for admins.
    """
    if report is None:
        return

    if not report.errors and not report.warnings and (not show_info or not report.info):
        return

    # Summary header
    if report.errors:
        st.error(f"🧱 {title}: {len(report.errors)} error(s)")
    elif report.warnings:
        st.warning(f"⚠️ {title}: {len(report.warnings)} warning(s)")
    else:
        st.info(f"ℹ️ {title} Info")

    def _render_issues(label: str, issues: List[Issue]) -> None:
        if not issues:
            return
        st.markdown(f"**{label}**")
        for it in issues:
            st.markdown(f"[{it.code}] {it.message}")
            if it.fix:
                st.caption(f"Fix: {it.fix}")
            if it.details is not None:
                with st.expander(f"Details: {it.code}", expanded=False):
                    st.write(it.details)

    _render_issues("Errors", report.errors)
    _render_issues("Warnings", report.warnings)
    if show_info:
        _render_issues("Info", report.info)
