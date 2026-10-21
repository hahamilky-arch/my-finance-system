"""Quant Alpha UI 테마 — app.py의 로직은 건드리지 않고 스타일만 교체합니다.

사용법 (app.py):
    from ui_theme import inject_theme
    inject_theme()   # 기존 "# 1. 커스텀 CSS" st.markdown(...) 블록 전체를 이 한 줄로 교체
"""

import streamlit as st

THEME_CSS = """
<style>
:root {
    --bg: #f4f6fb;
    --card: #ffffff;
    --line: #e8ebf3;
    --text: #151826;
    --sub: #7a8196;
    --accent: #4c5fe0;
    --accent-soft: #eceffd;
    --up: #e5484d;      /* 상승 (한국식 빨강) */
    --down: #3b82f6;    /* 하락 (한국식 파랑) */
    --ok: #12a594;
    --radius: 16px;
    --shadow: 0 1px 2px rgba(20,24,50,.04), 0 6px 18px rgba(20,24,50,.06);
}

/* ---------- 기본 레이아웃 ---------- */
html { scroll-behavior: smooth !important; }
html, body, .stApp { background: var(--bg) !important; }
html, body, [class*="st-"] {
    font-size: 13px !important;
    font-family: "Pretendard", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: var(--text);
}
html, body { overflow-y: scroll !important; overflow-x: hidden !important; }
.block-container {
    padding: 0.6rem 0.9rem 5rem 0.9rem !important;
    max-width: 1000px !important;
    margin: 0 auto;
}
header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; }
div[data-testid="stVerticalBlock"] > div { margin-bottom: 0.35rem !important; }

::-webkit-scrollbar { width: 6px !important; height: 6px !important; }
::-webkit-scrollbar-track { background: transparent !important; }
::-webkit-scrollbar-thumb { background: #c5cbdc !important; border-radius: 6px; }

/* ---------- 탭: 알약(pill) 스타일 ---------- */
div[data-baseweb="tab-list"] {
    gap: 4px !important;
    background: #e9ecf6;
    padding: 4px;
    border-radius: 14px;
    border-bottom: none !important;
}
button[data-baseweb="tab"] {
    flex: 1;
    height: 34px !important;
    border-radius: 10px !important;
    background: transparent !important;
    color: var(--sub) !important;
    font-weight: 700 !important;
    padding: 0 6px !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    background: var(--card) !important;
    color: var(--accent) !important;
    box-shadow: 0 1px 4px rgba(20,24,50,.10);
}
div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"] { display: none !important; }

/* ---------- 버튼 / 팝오버 ---------- */
div[data-testid="stPopover"] > button,
div[data-testid="stButton"] > button {
    padding: 2px 10px !important;
    font-size: 0.75rem !important;
    height: 30px !important;
    min-height: 30px !important;
    border-radius: 10px !important;
    border: 1px solid var(--line) !important;
    background: var(--card) !important;
    color: var(--text) !important;
    font-weight: 700 !important;
    box-shadow: none !important;
    transition: all .15s ease;
}
div[data-testid="stButton"] > button:hover,
div[data-testid="stPopover"] > button:hover {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
}
div[data-testid="stButton"] > button[kind="primary"] {
    background: var(--accent) !important;
    color: #fff !important;
    border: 1px solid var(--accent) !important;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    filter: brightness(1.08);
    color: #fff !important;
}

/* ---------- 입력 컴포넌트 ---------- */
div[data-baseweb="input"], div[data-baseweb="select"] > div, div[data-testid="stDateInput"] > div > div {
    border-radius: 10px !important;
    background: var(--card) !important;
}
div[data-testid="stTextInput"] label,
div[data-testid="stTextInput"] [data-testid="stInputHelperText"],
div[data-testid="stTextInput"] p:not(:has(input)),
div[data-testid="stTextInput"] small {
    display: none !important; height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: hidden !important;
}
div[data-testid="stTextInput"] input { font-size: 0.82rem !important; height: 32px !important; }

/* 아이콘 대체 텍스트 은폐 (기존 동작 유지) */
[data-testid="stIconMaterial"],
[data-testid="stPopover"] span[class*="material-symbols"],
[data-testid="stExpander"] details summary span[class*="material-symbols"],
div[data-testid="stTextInput"] button span {
    font-size: 0px !important;
    color: transparent !important;
    overflow: hidden !important;
    line-height: 0 !important;
    text-indent: -9999px !important;
    display: inline-block !important;
    width: 16px !important;
    height: 16px !important;
}
div[data-testid="stExpander"] details summary,
div[data-testid="stPopover"] > button {
    display: flex !important;
    align-items: center !important;
    gap: 4px !important;
}

/* ---------- 익스팬더 = 카드 ---------- */
div[data-testid="stExpander"] {
    background: var(--card);
    border: 1px solid var(--line) !important;
    border-radius: var(--radius) !important;
    box-shadow: var(--shadow);
    overflow: hidden;
}
div[data-testid="stExpander"] details summary {
    font-weight: 800;
    padding: 10px 14px !important;
}
div[data-testid="stExpander"] details[open] summary { border-bottom: 1px solid var(--line); }

/* ---------- 표 ---------- */
div[data-testid="stDataFrame"] {
    border: 1px solid var(--line);
    border-radius: 12px;
    overflow: hidden;
    background: var(--card);
}

/* ---------- 지표(KPI) ---------- */
div[data-testid="stMetric"] {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 10px 12px;
    box-shadow: var(--shadow);
}
div[data-testid="stMetricLabel"] { color: var(--sub) !important; font-weight: 700 !important; }
div[data-testid="stMetricValue"] { font-weight: 900 !important; }

/* ---------- 라디오 / 세그먼트 ---------- */
div[data-testid="stSegmentedControl"] button { border-radius: 10px !important; font-weight: 700 !important; }

/* ---------- 오늘의 행동 히어로 카드 ---------- */
.action-card {
    background: linear-gradient(135deg, #4c5fe0 0%, #6a7bf0 55%, #8b9bff 100%);
    border-radius: 20px;
    padding: 16px 16px 14px 16px;
    margin-bottom: 12px;
    box-shadow: 0 10px 28px rgba(76,95,224,.28);
    color: #fff;
}
.action-card-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.action-card-subtitle { font-size: 0.74rem; font-weight: 700; color: rgba(255,255,255,.85); }
.action-card-right { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.action-card-title { font-size: 1.45rem; font-weight: 900; color: #fff; margin: 2px 0 6px 0; letter-spacing: -0.5px; }
.action-card-desc { font-size: 0.8rem; color: rgba(255,255,255,.88); margin-bottom: 14px; line-height: 1.4; }
.action-stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }

.index-summary-badge {
    background: rgba(255,255,255,.95);
    color: #151826;
    font-size: 0.72rem;
    font-weight: 800;
    padding: 4px 10px;
    border-radius: 16px;
    display: inline-block;
    white-space: nowrap;
}
.regime-badge {
    background: rgba(255,255,255,.2);
    border: 1px solid rgba(255,255,255,.4);
    color: #fff;
    font-size: 0.7rem;
    font-weight: 800;
    padding: 3px 10px;
    border-radius: 16px;
    display: inline-block;
    white-space: nowrap;
}

.stat-box {
    background: rgba(255,255,255,.96);
    border-radius: 12px;
    padding: 9px 11px;
    text-align: left;
}
.stat-box-label { font-size: 0.68rem; color: var(--sub); font-weight: 700; margin-bottom: 2px; }
.stat-box-value { font-size: 1.1rem; font-weight: 900; color: var(--text); }

/* ---------- 수급 게이지 카드 ---------- */
.gauge-card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 12px 14px;
    margin-bottom: 8px;
    box-shadow: var(--shadow);
}
.gauge-card-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.gauge-title { font-size: 0.78rem; color: var(--text); font-weight: 800; }
.gauge-tag {
    font-size: 0.66rem; color: var(--accent); background: var(--accent-soft);
    padding: 2px 8px; border-radius: 10px; font-weight: 700; white-space: nowrap;
}
.gauge-value { font-size: 1.3rem; font-weight: 900; margin: 4px 0 2px 0; letter-spacing: -.3px; }
.gauge-subtext { font-size: 0.7rem; color: var(--sub); margin-bottom: 8px; }
.gauge-bar-bg { background: transparent; height: 7px; display: flex; gap: 3px; }
.gauge-segment { flex: 1; height: 100%; border-radius: 3px; }
.segment-active { background-color: var(--up); }
.segment-inactive { background-color: #e3e7f0; }

/* ---------- 태그 ---------- */
.tag-container { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.tag-badge {
    background: var(--accent-soft); color: var(--accent);
    font-size: 0.7rem; font-weight: 700; padding: 4px 10px; border-radius: 999px;
}

/* ---------- 플로팅 버튼 ---------- */
.floating-top-btn {
    position: fixed; bottom: 22px; right: 18px; z-index: 999999;
    background: var(--accent); color: #fff !important; padding: 8px 14px;
    border-radius: 999px; font-size: 0.75rem; font-weight: 800; text-decoration: none !important;
    box-shadow: 0 8px 20px rgba(76,95,224,.35);
}
.bottom-spacer { height: 90px !important; display: block; clear: both; }
</style>

<a href="#top-section" class="floating-top-btn">▲ 맨위로</a>
"""


def inject_theme():
    st.markdown(THEME_CSS, unsafe_allow_html=True)
