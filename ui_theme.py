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
    background: linear-gradient(135deg, #4c5fe0 0%, #6a7bf0 60%, #8b9bff 100%);
    border-radius: 18px;
    padding: 14px 14px 12px 14px;
    margin-bottom: 10px;
    box-shadow: 0 8px 22px rgba(76,95,224,.25);
    color: #fff;
}
.action-card-header { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
.action-card-subtitle { font-size: 0.72rem; font-weight: 700; color: rgba(255,255,255,.8); letter-spacing: .2px; }
.action-card-right { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.action-card-title { font-size: 1.35rem; font-weight: 900; color: #fff; margin: 0 0 4px 0; letter-spacing: -0.5px; line-height: 1.2; }
.action-card-desc { font-size: 0.76rem; color: rgba(255,255,255,.88); margin-bottom: 12px; line-height: 1.4; word-break: keep-all; }
/* 모바일에서도 항상 3열 유지 */
.action-stats-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }

.index-summary-badge {
    background: rgba(255,255,255,.95);
    color: #151826;
    font-size: 0.7rem;
    font-weight: 800;
    padding: 3px 9px;
    border-radius: 14px;
    display: inline-block;
    white-space: nowrap;
}
.regime-badge {
    background: rgba(255,255,255,.2);
    border: 1px solid rgba(255,255,255,.4);
    color: #fff;
    font-size: 0.68rem;
    font-weight: 800;
    padding: 2px 9px;
    border-radius: 14px;
    display: inline-block;
    white-space: nowrap;
}

.stat-box {
    background: rgba(255,255,255,.96);
    border-radius: 11px;
    padding: 8px 9px;
    text-align: left;
    min-width: 0;
}
.stat-box-label { font-size: 0.64rem; color: var(--sub); font-weight: 700; margin-bottom: 2px; white-space: nowrap; }
.stat-box-value { font-size: 1.02rem; font-weight: 900; color: var(--text); white-space: nowrap; }
.stat-box-value span { font-size: 0.62rem !important; }
.slot-bar { height: 4px; border-radius: 4px; background: #e3e7f0; margin-top: 6px; overflow: hidden; }
.slot-bar > div { height: 100%; background: var(--accent); border-radius: 4px; }

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
/* ---------- 헤더 컨트롤 바 ---------- */
.hdr-marker, .hdr-auth { height: 0; margin: 0; padding: 0; }
@media (min-width: 641px) {
    div[data-testid="stHorizontalBlock"]:has(.hdr-marker) > div { min-width: 0 !important; }
}
/* 안쪽 묶음(타이머·연장·설정 / 비밀번호·해제)은 폭이 좁아도 한 줄 유지 */
div[data-testid="stHorizontalBlock"]:has(.hdr-marker) div[data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    gap: 6px !important;
    align-items: center;
}
div[data-testid="stHorizontalBlock"]:has(.hdr-marker) div[data-testid="stHorizontalBlock"] > div { min-width: 0 !important; }
/* 로그인 상태: 내용 폭만큼만 차지 */
div[data-testid="stHorizontalBlock"]:has(.hdr-marker) div[data-testid="stHorizontalBlock"]:has(.hdr-auth) { justify-content: flex-end; }
div[data-testid="stHorizontalBlock"]:has(.hdr-marker) div[data-testid="stHorizontalBlock"]:has(.hdr-auth) > div {
    flex: 0 0 auto !important; width: auto !important;
}
/* 로그아웃 상태: 비밀번호창은 남은 폭, 해제 버튼은 고정 폭 */
div[data-testid="stHorizontalBlock"]:has(.hdr-marker) div[data-testid="stHorizontalBlock"]:has(.st-key-btn_global_unlock) > div:first-child {
    flex: 1 1 0 !important; width: auto !important;
}
div[data-testid="stHorizontalBlock"]:has(.hdr-marker) div[data-testid="stHorizontalBlock"]:has(.st-key-btn_global_unlock) > div:last-child {
    flex: 0 0 auto !important; width: auto !important;
}
div[data-testid="stHorizontalBlock"]:has(.hdr-marker) div[data-testid="stHorizontalBlock"] button {
    white-space: nowrap !important;
    overflow: visible !important;
    text-overflow: clip !important;
    padding: 0 12px !important;
    min-width: 44px;
}
div[data-testid="stHorizontalBlock"]:has(.hdr-marker) div[data-testid="stHorizontalBlock"] button p {
    overflow: visible !important;
    text-overflow: clip !important;
}
div[data-testid="stHorizontalBlock"]:has(.hdr-marker) div[data-testid="stHorizontalBlock"] div[data-testid="stMarkdownContainer"] div { white-space: nowrap; }
/* 팝오버 화살표 아이콘 자리 제거 */
div[data-testid="stPopover"] > button [data-testid="stIconMaterial"] { display: none !important; }

/* ---------- 중간 영역: 전략 태그(스와이프) + ⓘ ---------- */
div[data-testid="stHorizontalBlock"]:has(.mid-marker) {
    flex-wrap: nowrap !important; gap: 8px !important; align-items: center;
}
div[data-testid="stHorizontalBlock"]:has(.mid-marker) > div:first-child {
    flex: 1 1 0 !important; min-width: 0 !important; width: auto !important;
}
div[data-testid="stHorizontalBlock"]:has(.mid-marker) > div:last-child {
    flex: 0 0 auto !important; min-width: 0 !important; width: auto !important;
}
.tag-scroll {
    flex-wrap: nowrap !important; overflow-x: auto; margin-top: 0 !important;
    scrollbar-width: none; -webkit-overflow-scrolling: touch;
    -webkit-mask-image: linear-gradient(90deg, #000 88%, transparent);
    mask-image: linear-gradient(90deg, #000 88%, transparent);
}
.tag-scroll::-webkit-scrollbar { display: none; }
.tag-scroll .tag-badge { white-space: nowrap; flex: none; }
div[data-testid="stHorizontalBlock"]:has(.mid-marker) div[data-testid="stPopover"] { width: auto; }
div[data-testid="stHorizontalBlock"]:has(.mid-marker) div[data-testid="stPopover"] > button {
    width: 30px !important; min-width: 30px !important; padding: 0 !important;
    border-radius: 50% !important; justify-content: center;
    color: var(--accent) !important; font-weight: 800 !important; font-size: 0.9rem !important;
}

/* ---------- AI 진단 카드 (인디고 포인트) ---------- */
div[data-testid="stExpander"]:has(.st-key-btn_run_smart_money_ai_tab1) {
    border: 1px solid #c9d0fb !important;
    border-left: 4px solid var(--accent) !important;
}
div[data-testid="stExpander"]:has(.st-key-btn_run_smart_money_ai_tab1) details summary { color: var(--text); }

</style>

<a href="#top-section" class="floating-top-btn">▲ 맨위로</a>
"""


def inject_theme():
    st.markdown(THEME_CSS, unsafe_allow_html=True)
