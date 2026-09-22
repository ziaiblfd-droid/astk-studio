from __future__ import annotations

import os
import re
from html import escape
from urllib.parse import quote

import streamlit as st


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

target_url = escape(backend_url, quote=True)

st.markdown(
    f"""
    <meta http-equiv="refresh" content="0; url={target_url}">
    <style>
      html, body, [data-testid="stAppViewContainer"], .stApp {{
        min-height: 100%;
        background: #f4f7f9;
      }}
      header[data-testid="stHeader"],
      [data-testid="stSidebar"],
      [data-testid="stToolbar"],
      [data-testid="stDecoration"],
      #MainMenu,
      footer {{
        display: none !important;
      }}
      .block-container {{
        width: min(100% - 40px, 760px);
        max-width: 760px;
        min-height: 100vh;
        padding: 0 !important;
        display: flex;
        align-items: center;
      }}
      .redirect-shell {{
        width: 100%;
        padding: 52px 0;
        color: #15232d;
      }}
      .brand {{
        margin: 0 0 20px;
        font: 700 30px/1.2 system-ui, sans-serif;
        letter-spacing: 0;
      }}
      .status {{
        margin: 0 0 22px;
        color: #52616b;
        font: 400 16px/1.6 system-ui, sans-serif;
      }}
      .progress {{
        width: min(100%, 420px);
        height: 3px;
        margin-bottom: 30px;
        overflow: hidden;
        background: #dce4e8;
      }}
      .progress::after {{
        display: block;
        width: 38%;
        height: 100%;
        content: "";
        background: #0b7a75;
        animation: loading 1.1s ease-in-out infinite alternate;
      }}
      .continue-link {{
        display: inline-flex;
        min-height: 42px;
        padding: 0 18px;
        align-items: center;
        justify-content: center;
        border: 1px solid #0b7a75;
        border-radius: 6px;
        color: #075f5b !important;
        font: 600 14px/1 system-ui, sans-serif;
        text-decoration: none !important;
      }}
      .continue-link:hover {{
        background: #e5f3f2;
      }}
      @keyframes loading {{
        from {{ transform: translateX(-10%); }}
        to {{ transform: translateX(165%); }}
      }}
      @media (prefers-reduced-motion: reduce) {{
        .progress::after {{ animation: none; }}
      }}
    </style>
    <main class="redirect-shell">
      <div class="brand">ASTK Studio</div>
      <p class="status">正在进入分析工作台...</p>
      <div class="progress" aria-hidden="true"></div>
      <a class="continue-link" href="{target_url}">立即进入</a>
    </main>
    """,
    unsafe_allow_html=True,
)
