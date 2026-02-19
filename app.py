# app.py
from __future__ import annotations

from typing import Dict, Any, Optional, List, Callable
import sys
import types

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

from core.session_state import init_session_state
from core.sheet_validation import validate_sheet_data, render_report_streamlit

# ✅ Stage-1 ONLY engine (frozen architecture)
from core.pretest_shortlist import build_pretest_shortlist


# ------------------ HARD LEGACY DISCONNECT (core/shaft_predictor.py) ------------------
# Patch requirement: core/shaft_predictor.py must be fully disconnected so nothing can leak to UI/PDF.
# NOTE: Streamlit (via inspect) iterates sys.modules and asks for module.__file__/dunder attrs.
# So our blocker must be "inspect-safe" (never raises on dunder metadata access).
class _BlockedLegacyModule(types.ModuleType):
    def __init__(self, name: str, msg: str):
        super().__init__(name)
        self.__blocked_msg = msg

        # Make common introspection attributes safe
        self.__file__ = "<blocked legacy module>"
        self.__package__ = name.rpartition(".")[0]
        self.__path__ = []  # type: ignore[assignment]
        self.__spec__ = None  # type: ignore[assignment]
        self.__loader__ = None  # type: ignore[assignment]

    def __getattr__(self, item: str):
        # Never break introspection / inspect() / hasattr()
        if item.startswith("__"):
            return None
        if item in ("__file__", "__spec__", "__path__", "__loader__", "__package__", "__name__"):
            return None

        # Anything non-dunder is an attempted legacy access -> hard fail
        raise RuntimeError(self.__blocked_msg)


_LEGACY_BLOCK_MSG = (
    "Legacy engine is disabled: core/shaft_predictor.py must not be imported or used. "
    "Stage-1 must come ONLY from core/pretest_shortlist.py."
)

# Block both common import paths (defensive)
for _modname in ("core.shaft_predictor", "shaft_predictor"):
    sys.modules[_modname] = _BlockedLegacyModule(_modname, _LEGACY_BLOCK_MSG)


# ------------------ Streamlit config ------------------
st.set_page_config(page_title="Tour Proven Shaft Fitting", layout="wide", page_icon="⛳")

st.markdown(
    """
<style>
[data-testid="stTable"] { font-size: 12px !important; }

.profile-bar {
  background-color: #142850;
  color: white;
  padding: 20px;
  border-radius: 10px;
  margin-bottom: 25px;
}

.profile-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 15px;
}

.verdict-text {
  font-style: italic;
  color: #bfbfbf;
  margin-bottom: 25px;
  font-size: 13px;
  border-left: 3px solid #b40000;
  padding-left: 10px;
}

.rec-warn {
  border-left: 4px solid #b40000;
  padding-left: 10px;
  margin: 6px 0;
}

.rec-info {
  border-left: 4px solid #2c6bed;
  padding-left: 10px;
  margin: 6px 0;
}

.smallcap {
  color: #9aa0a6;
  font-size: 12px;
}
</style>
""",
    unsafe_allow_html=True,
)

# ✅ MUST happen before any UI uses session_state
init_session_state(st)

# Non-breaking signal for downstream UI modules
st.session_state["legacy_predictor_disabled"] = True


# ------------------ Google Sheets helpers ------------------
def get_google_creds(scopes: List[str]) -> Credentials:
    creds_dict = dict(st.secrets["gcp_service_account"])

    pk = creds_dict.get("private_key", "")
    if pk:
        pk = pk.replace("\\n", "\n")
        if "-----BEGIN PRIVATE KEY-----" in pk:
            pk = pk[pk.find("-----BEGIN PRIVATE KEY-----") :]
        creds_dict["private_key"] = pk.strip()

    return Credentials.from_service_account_info(creds_dict, scopes=scopes)


def cfg_float(cfg_df: pd.DataFrame, key: str, default: float) -> float:
    try:
        if cfg_df is not None and not cfg_df.empty and key in cfg_df.columns:
            return float(str(cfg_df.iloc[0][key]).strip())
    except Exception:
        pass
    return float(default)


@st.cache_data(ttl=600)
def get_data_from_gsheet() -> Optional[Dict[str, pd.DataFrame]]:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = get_google_creds(scopes)
    gc = gspread.authorize(creds)

    sh = gc.open_by_url(
        "https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit"
    )

    def get_clean_df(ws_name: str) -> pd.DataFrame:
        rows = sh.worksheet(ws_name).get_all_values()
        if not rows or len(rows) < 2:
            return pd.DataFrame()
        headers = [(h.strip() if str(h).strip() else f"Col_{i}") for i, h in enumerate(rows[0])]
        df = pd.DataFrame(rows[1:], columns=headers)
        for c in df.columns:
            if df[c].dtype == "object":
                df[c] = df[c].astype(str).str.strip()
        return df

    tabs = ["Heads", "Shafts", "Questions", "Responses", "Config", "Descriptions", "Fittings", "Admin"]
    out: Dict[str, pd.DataFrame] = {}
    for t in tabs:
        try:
            out[t] = get_clean_df(t)
        except Exception:
            out[t] = pd.DataFrame()
    return out


def _safe_import(name: str, importer: Callable[[], Callable[..., None]]) -> Optional[Callable[..., None]]:
    """
    Import a render function safely so SyntaxError in a module doesn't crash the whole app.

    NOTE: legacy predictor is hard-blocked above. If any UI module still tries to import it,
    it will raise a RuntimeError with a clear message (preventing silent leaks to UI/PDF).
    """
    try:
        return importer()
    except Exception as e:
        st.error(f"Failed to load: {name}")
        st.exception(e)
        return None


def save_to_fittings(answers: Dict[str, Any], all_data: Dict[str, pd.DataFrame]) -> None:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = get_google_creds(scopes)
    gc = gspread.authorize(creds)

    sh = gc.open_by_url(
        "https://docs.google.com/spreadsheets/d/1D3MGF3BxboxYdWHz8TpEEU5Z-FV7qs3jtnLAqXcEetY/edit"
    )
    ws_fit = sh.worksheet("Fittings")

    fit_headers = ws_fit.row_values(1)
    fit_headers = [h for h in fit_headers if str(h).strip()]

    now_ts = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    row_out: List[Any] = []

    for h in fit_headers:
        hn = str(h).strip().lower()
        if hn == "timestamp":
            row_out.append(now_ts)
        else:
            if str(h).strip().upper().startswith("Q"):
                qid = str(h).strip().upper().replace(".", "_")
                row_out.append(answers.get(qid, ""))
            else:
                row_out.append("")

    ws_fit.append_row(row_out, value_input_option="USER_ENTERED")


# ------------------ Load sheet ------------------
all_data = get_data_from_gsheet()
if not all_data:
    st.stop()

report = validate_sheet_data(all_data)
render_report_streamlit(report, title="Sheet Validation", show_info=False)
if report.errors:
    st.error("Sheet has fatal errors. Fix the Google Sheet and reload.")
    st.stop()

# Make Shafts df available globally via session_state for UI helpers
try:
    st.session_state.all_shafts_df = all_data.get("Shafts", pd.DataFrame())
    st.session_state.shafts_df_for_ui = st.session_state.all_shafts_df
except Exception:
    st.session_state.all_shafts_df = pd.DataFrame()
    st.session_state.shafts_df_for_ui = pd.DataFrame()

cfg = all_data.get("Config", pd.DataFrame())
WARN_FACE_TO_PATH_SD = cfg_float(cfg, "WARN_FACE_TO_PATH_SD", 3.0)
WARN_CARRY_SD = cfg_float(cfg, "WARN_CARRY_SD", 10.0)
WARN_SMASH_SD = cfg_float(cfg, "WARN_SMASH_SD", 0.10)
MIN_SHOTS = int(cfg_float(cfg, "MIN_SHOTS", 8))

q_master = all_data.get("Questions", pd.DataFrame())
if q_master is None or q_master.empty or "Category" not in q_master.columns:
    st.error("Questions sheet is missing or invalid.")
    st.stop()

categories = list(dict.fromkeys(q_master["Category"].astype(str).tolist()))


# ------------------ App flow ------------------
st.title("Tour Proven Shaft Fitting")

render_interview = _safe_import(
    "ui.interview.render_interview",
    lambda: __import__("ui.interview", fromlist=["render_interview"]).render_interview,
)
render_trackman_tab = _safe_import(
    "ui.trackman_tab.render_trackman_tab",
    lambda: __import__("ui.trackman_tab", fromlist=["render_trackman_tab"]).render_trackman_tab,
)
render_recommendations_tab = _safe_import(
    "ui.recommendations_tab.render_recommendations_tab",
    lambda: __import__("ui.recommendations_tab", fromlist=["render_recommendations_tab"]).render_recommendations_tab,
)

# ------------------ Interview flow ------------------
if not st.session_state.get("interview_complete", False):
    if render_interview is None:
        st.stop()

    def _save(answers: Dict[str, Any]) -> None:
        save_to_fittings(answers, all_data)

    render_interview(all_data=all_data, q_master=q_master, categories=categories, save_to_fittings_fn=_save)
    st.stop()

# ------------------ Results flow ------------------
ans = st.session_state.answers
p_name = ans.get("Q01", "Player")
p_email = ans.get("Q02", "")

st.session_state.environment = (ans.get("Q22") or st.session_state.environment or "Indoors (Mat)").strip()

st.subheader(f"⛳ Results: {p_name}")

c1, c2, _ = st.columns([1, 1, 4])
if c1.button("✏️ Edit Fitting"):
    st.session_state.interview_complete = False
    st.session_state.email_sent = False
    st.rerun()

if c2.button("🆕 New Fitting"):
    st.session_state.clear()
    st.rerun()

st.divider()
tab_report, tab_lab = st.tabs(["📄 Recommendations", "🧪 Trackman Lab"])

# ------------------ Stage-1 shortlist (interview-driven ONLY) ------------------
shafts_df = all_data.get("Shafts", pd.DataFrame())
try:
    st.session_state.pretest_shortlist_df = build_pretest_shortlist(shafts_df, ans, n=3)
except Exception:
    st.session_state.pretest_shortlist_df = pd.DataFrame(columns=["ID", "Brand", "Model", "Flex", "Weight (g)"])

# ------------------ Legacy outputs removed ------------------
# Keep these placeholders ONLY so ui modules that still expect them won't crash.
# They must remain EMPTY so nothing "legacy" can leak into UI/PDF.
all_winners: Dict[str, pd.DataFrame] = {}
verdicts: Dict[str, str] = {}

with tab_report:
    if render_recommendations_tab is None:
        st.stop()
    render_recommendations_tab(
        p_name=p_name,
        p_email=p_email,
        ans=ans,
        all_winners=all_winners,  # legacy placeholder (kept empty)
        verdicts=verdicts,        # legacy placeholder (kept empty)
        environment=st.session_state.environment,
    )

with tab_lab:
    if render_trackman_tab is None:
        st.stop()
    render_trackman_tab(
        all_data=all_data,
        answers=st.session_state.answers,
        all_winners=all_winners,  # legacy placeholder (kept empty)
        MIN_SHOTS=MIN_SHOTS,
        WARN_FACE_TO_PATH_SD=WARN_FACE_TO_PATH_SD,
        WARN_CARRY_SD=WARN_CARRY_SD,
        WARN_SMASH_SD=WARN_SMASH_SD,
    )
