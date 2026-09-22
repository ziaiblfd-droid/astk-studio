from __future__ import annotations

import os
import re
from urllib.parse import quote

import streamlit as st
from streamlit.components.v1 import iframe


st.set_page_config(
    page_title="ASTK Studio",
    page_icon="A",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DEFAULT_BACKEND_URL = "http://127.0.0.1:4173"


def setting(name: str, default: str | None = None) -> str | None:
    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    return str(value) if value not in (None, "") else os.getenv(name, default)


backend_url = (setting("ASTK_BACKEND_URL", DEFAULT_BACKEND_URL) or DEFAULT_BACKEND_URL).rstrip("/")
job_id = str(st.query_params.get("job", "")).strip()
if re.fullmatch(r"ASTK-[A-Za-z0-9-]+", job_id):
    backend_url = f"{backend_url}/?job={quote(job_id)}"

st.markdown(
    """
    <style>
      html, body, [data-testid="stAppViewContainer"], .stApp {
        height: 100%;
        overflow: hidden;
      }
      header[data-testid="stHeader"],
      [data-testid="stSidebar"],
      [data-testid="stToolbar"],
      [data-testid="stDecoration"],
      #MainMenu,
      footer {
        display: none !important;
      }
      [data-testid="stAppViewContainer"] > .main,
      [data-testid="stMain"] {
        height: 100vh;
      }
      .block-container {
        width: 100%;
        max-width: none;
        height: 100vh;
        padding: 0 !important;
      }
      [data-testid="stElementContainer"],
      [data-testid="stCustomComponentV1"],
      iframe {
        display: block;
        width: 100% !important;
        height: 100vh !important;
        border: 0 !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

iframe(backend_url, height=1200, scrolling=True)
