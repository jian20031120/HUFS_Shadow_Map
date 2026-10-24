"""Map page styling with the original user-provided background."""
import base64

import streamlit as st

from .paths import ROOT

BACKGROUND = ROOT / 'assets/background.jpg'


def apply_theme():
    background = ''
    if BACKGROUND.exists():
        encoded = base64.b64encode(BACKGROUND.read_bytes()).decode('ascii')
        background = f'background-image:linear-gradient(#ffffff18,#ffffff18),url("data:image/jpeg;base64,{encoded}");'
    st.markdown('''<style>
    .stApp{background-color:#cceae0;BACKGROUND background-size:cover;
      background-position:center;background-attachment:fixed;color:#25483f}
    [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stSidebar"],
    [data-testid="stDecoration"], #MainMenu, footer{display:none!important}
    .block-container{max-width:100%!important;margin:0!important;padding:10px 12px!important;
      border:0;border-radius:0;box-shadow:none;background:transparent}
    [data-testid="stVerticalBlock"]{gap:5px}
    [data-testid="stCaptionContainer"]{background:rgba(248,255,248,.94);border-radius:10px;
      padding:4px 10px;margin:0;font-size:12px}
    [data-testid="stCaptionContainer"] p{margin:0}
    iframe{border:1px solid #d8e8dc;border-radius:16px;background:#f9fcf7}
    @media(max-width:700px){.block-container{padding:6px!important}}
    </style>'''.replace('BACKGROUND', background), unsafe_allow_html=True)
