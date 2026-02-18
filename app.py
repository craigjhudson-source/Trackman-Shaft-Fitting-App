# app.py  (or streamlit_app.py / main.py)
from __future__ import annotations

import streamlit as st

# --- Centralized session_state init (NEW) ---
from core.session_state import init_session_state


def _safe_import_renderers():
    """
    Import tab renderers safely so the whole app doesn't hard-crash
    if a module path changes during development.

    Adjust these imports to match your project if needed.
    """
    renderers = {}

    # Trackman tab renderer
    try:
        # Option A (what we used in the patch)
        from ui.trackman_tab import render_trackman_tab  # type: ignore
        renderers["trackman"] = render_trackman_tab
    except Exception as e:
        renderers["trackman"] = ("ui.trackman_tab.render_trackman_tab", e)

    # Recommendations tab renderer
    try:
        # Common naming patterns — change if your file/function differs
        from ui.recommendations_tab import render_recommendations_tab  # type: ignore
        renderers["recommendations"] = render_recommendations_tab
    except Exception as e:
        renderers["recommendations"] = ("ui.recommendations_tab.render_recommendations_tab", e)

    # Interview tab renderer
    try:
        from ui.interview_tab import render_interview_tab  # type: ignore
        renderers["interview"] = render_interview_tab
    except Exception as e:
        renderers["interview"] = ("ui.interview_tab.render_interview_tab", e)

    # Fittings tab renderer
    try:
        from ui.fittings_tab import render_fittings_tab  # type: ignore
        renderers["fittings"] = render_fittings_tab
    except Exception as e:
        renderers["fittings"] = ("ui.fittings_tab.render_fittings_tab", e)

    # PDF tab renderer (optional)
    try:
        from ui.pdf_tab import render_pdf_tab  # type: ignore
        renderers["pdf"] = render_pdf_tab
    except Exception as e:
        renderers["pdf"] = ("ui.pdf_tab.render_pdf_tab", e)

    return renderers


def _render_missing(name: str, expected: str, err: Exception) -> None:
    st.error(f"Tab '{name}' failed to load.")
    st.caption("Fix the import path in your entry file (app.py) to match your project.")
    st.code(f"Expected import: {expected}", language="python")
    st.code(f"{type(err).__name__}: {err}", language="text")


def main() -> None:
    st.set_page_config(
        page_title="Tour Proven Shaft Fitting",
        layout="wide",
    )

    # ✅ MUST HAPPEN BEFORE ANY TAB LOGIC
    init_session_state(st)

    st.title("Tour Proven Shaft Fitting")

    renderers = _safe_import_renderers()

    tabs = st.tabs(
        [
            "Interview",
            "Recommendations",
            "Trackman Lab",
            "Fittings",
            "PDF",
        ]
    )

    # Interview
    with tabs[0]:
        r = renderers.get("interview")
        if callable(r):
            r()
        else:
            expected, err = r  # type: ignore
            _render_missing("Interview", expected, err)

    # Recommendations
    with tabs[1]:
        r = renderers.get("recommendations")
        if callable(r):
            r()
        else:
            expected, err = r  # type: ignore
            _render_missing("Recommendations", expected, err)

    # Trackman Lab
    with tabs[2]:
        r = renderers.get("trackman")
        if callable(r):
            r()
        else:
            expected, err = r  # type: ignore
            _render_missing("Trackman Lab", expected, err)

    # Fittings
    with tabs[3]:
        r = renderers.get("fittings")
        if callable(r):
            r()
        else:
            expected, err = r  # type: ignore
            _render_missing("Fittings", expected, err)

    # PDF
    with tabs[4]:
        r = renderers.get("pdf")
        if callable(r):
            r()
        else:
            expected, err = r  # type: ignore
            _render_missing("PDF", expected, err)


if __name__ == "__main__":
    main()
