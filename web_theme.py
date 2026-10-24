"""Shared website theme; the background is a user-supplied local image."""
import base64
from pathlib import Path
import streamlit as st

BACKGROUND = Path(__file__).parent / 'assets' / 'background.png'
DEFAULT_BACKGROUND = Path(__file__).parent / 'b7f377c5a1d17ff223ced7da692aee4c.jpg'


def apply_theme(map_only=False):
    image = ''
    background = BACKGROUND if BACKGROUND.exists() else DEFAULT_BACKGROUND
    if background.exists():
        encoded = base64.b64encode(background.read_bytes()).decode('ascii')
        mime = 'image/png' if background.suffix=='.png' else 'image/jpeg'
        image = f'background-image:linear-gradient(#ffffff18,#ffffff18),url("data:{mime};base64,{encoded}");'
    st.markdown('''<style>
    .stApp{background-color:#cceae0;BACKGROUND background-size:cover;background-position:center;
      background-attachment:fixed;color:#25483f;}
    [data-testid="stHeader"]{background:transparent;}
    [data-testid="stSidebar"]{background:rgba(246,255,248,.94);border-right:1px solid #ffffffb3;}
    .block-container{max-width:1450px;margin-top:24px;margin-bottom:24px;padding:28px 32px;
      background:rgba(252,255,249,.89);border:1px solid #ffffffc9;border-radius:28px;box-shadow:0 12px 45px #183c3420;}
    h1,h2,h3{color:#2e5d4e!important;letter-spacing:-.04em;}
    [data-testid="stMetric"]{background:#ffffffbd;border:1px solid #d4e6d9;border-radius:20px;padding:14px;}
    [data-testid="stExpander"]{background:#fffffff0;border:1px solid #d7e8de;border-radius:18px;overflow:hidden;}
    .stButton>button,.stDownloadButton>button{border:1px solid #9dc8ac;border-radius:14px;background:#e8f5d9;color:#294f3d;}
    .stButton>button:hover,.stDownloadButton>button:hover{background:#d5ecc0;border-color:#518668;color:#203e2d;}
    [data-testid="stAlert"]{border-radius:16px;}
    iframe{border-radius:20px;}
    .hero-tag{font-size:12px;letter-spacing:2px;font-weight:700;color:#55826c;}
    @media(max-width:700px){.block-container{padding:20px 16px;margin-top:12px;border-radius:20px}}
    </style>'''.replace('BACKGROUND',image), unsafe_allow_html=True)
    if map_only:
        st.markdown('''<style>
        [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stSidebar"],
        [data-testid="stDecoration"], #MainMenu, footer {display:none!important}
        .block-container{max-width:100%!important;margin:0!important;padding:10px 12px!important;
          border:0;border-radius:0;box-shadow:none;background:transparent;}
        [data-testid="stVerticalBlock"]{gap:5px}
        [data-testid="stCaptionContainer"]{background:rgba(248,255,248,.94);border-radius:10px;
          padding:4px 10px;margin:0;font-size:12px}
        [data-testid="stCaptionContainer"] p{margin:0}
        iframe{border:1px solid #d8e8dc;border-radius:16px;background:#f9fcf7}
        @media(max-width:700px){.block-container{padding:6px!important}}
        </style>''',unsafe_allow_html=True)


def background_settings():
    with st.sidebar.expander('배경 사진 설정'):
        st.caption('보내주신 연못 사진을 선택하면 사이트 전체 배경으로 저장됩니다.')
        uploaded=st.file_uploader('공통 배경 사진',type=['png','jpg','jpeg','webp'],key='background_upload')
        if uploaded is not None and st.button('이 사진을 공통 배경으로 적용'):
            from PIL import Image, ImageOps
            try:
                image=ImageOps.exif_transpose(Image.open(uploaded)).convert('RGB')
                image.thumbnail((2560,2560))
                BACKGROUND.parent.mkdir(exist_ok=True)
                image.save(BACKGROUND,format='PNG')
                st.rerun()
            except (OSError,ValueError) as error:
                st.error(f'이미지를 읽을 수 없습니다: {error}')
