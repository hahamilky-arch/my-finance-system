import time
import textwrap
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as gg
from plotly.subplots import make_subplots
import streamlit as st
import streamlit.components.v1 as components

# 내부 모듈 연동
from charts import (
    draw_attribution_charts,
    draw_integrated_chart,
    draw_market_supply_chart,
)
from db import (
    get_available_dates,
    get_holdings_table,
    get_market_regime,
    supabase,
    update_holdings,
)
from gemini_analyzer import (
    MAX_DAILY_QUOTA,
    analyze_stock_with_gemini,
    get_remaining_quota,
)
from risk_manager import calculate_holdings_risk
from strategy import get_data

st.set_page_config(layout="wide", page_title="Quant Alpha", page_icon="📈")

# 0. 새로고침 및 페이지 이탈 방지 스크립트
components.html(
    """
    <script>
    const preventReload = function (e) {
        e.preventDefault();
        e.returnValue = '';
    };
    window.parent.addEventListener('beforeunload', preventReload);
    </script>
    """,
    height=0,
)

st.markdown("<div id='top-section'></div>", unsafe_allow_html=True)

# 1. 커스텀 CSS (여백 축소, 대체텍스트 차단, 컴팩트 UI 레이아웃)
st.markdown(
    """
    <style>
    /* 스크롤바 및 레이아웃 기본 스타일 */
    html { scroll-behavior: smooth !important; }
    html, body { overflow-y: scroll !important; overflow-x: hidden !important; padding-right: 10px !important; background-color: #f8f9fa; }
    
    ::-webkit-scrollbar { width: 8px !important; height: 8px !important; }
    ::-webkit-scrollbar-track { background: #f1f3f5 !important; }
    ::-webkit-scrollbar-thumb { background: #adb5bd !important; border-radius: 4px; }

    .block-container { padding-top: 0.5rem !important; padding-bottom: 5rem !important; padding-left: 0.8rem !important; padding-right: 12px !important; max-width: 1000px !important; margin: 0 auto; }
    html, body, [class*="st-"] { font-size: 13px !important; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }

    /* 여백 및 구분선 정돈 */
    div[data-testid="stVerticalBlock"] > div { margin-bottom: 0.4rem !important; }
    
    /* 비밀번호 및 컴포넌트 내부 잔여 아이콘 대체 텍스트 완전 은폐 */
    div[data-testid="stTextInput"] label,
    div[data-testid="stTextInput"] [data-testid="stInputHelperText"],
    div[data-testid="stTextInput"] p:not(:has(input)),
    div[data-testid="stTextInput"] small {
        display: none !important; height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: hidden !important;
    }
    div[data-testid="stTextInput"] input { font-size: 0.82rem !important; height: 32px !important; }

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

    /* 상단 헤더 컴팩트 버튼 */
    div[data-testid="stPopover"] > button,
    div[data-testid="stButton"] > button {
        padding: 2px 6px !important;
        font-size: 0.75rem !important;
        height: 30px !important;
        min-height: 30px !important;
    }

    /* 메인 요약 '오늘의 행동' 카드 */
    .action-card {
        background: linear-gradient(180deg, #fff9db 0%, #fff3bf 100%);
        border: 1px solid #ffe066;
        border-radius: 14px;
        padding: 14px 16px;
        margin-bottom: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.02);
    }
    .action-card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px; }
    .action-card-subtitle { font-size: 0.78rem; font-weight: 700; color: #856404; }
    .regime-badge { background-color: #ffffff; color: #856404; font-size: 0.7rem; font-weight: 800; padding: 2px 8px; border-radius: 16px; border: 1px solid #ffe066; }
    .action-card-title { font-size: 1.35rem; font-weight: 900; color: #111111; margin: 2px 0 6px 0; letter-spacing: -0.5px; }
    .action-card-desc { font-size: 0.82rem; color: #495057; margin-bottom: 12px; line-height: 1.35; }

    .action-stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .stat-box { background: #ffffff; border-radius: 10px; padding: 8px 10px; text-align: left; border: 1px solid #f1f3f5; }
    .stat-box-label { font-size: 0.7rem; color: #868e96; font-weight: 600; margin-bottom: 2px; }
    .stat-box-value { font-size: 1.05rem; font-weight: 800; color: #212529; }

    /* 수급 게이지 카드 통일 스타일 */
    .gauge-card { background: #ffffff; border: 1px solid #e9ecef; border-radius: 12px; padding: 10px 14px; margin-bottom: 8px; }
    .gauge-card-header { display: flex; justify-content: space-between; align-items: center; }
    .gauge-title { font-size: 0.78rem; color: #212529; font-weight: 700; }
    .gauge-tag { font-size: 0.68rem; font-weight: 600; padding: 2px 6px; border-radius: 10px; background: #f1f3f5; color: #495057; }
    .gauge-value { font-size: 1.2rem; font-weight: 800; margin: 2px 0 4px 0; }
    .gauge-subtext { font-size: 0.7rem; color: #868e96; margin-bottom: 6px; }
    
    .gauge-bar-bg { background: #e9ecef; height: 6px; border-radius: 3px; overflow: hidden; display: flex; gap: 2px; }
    .gauge-segment { flex: 1; height: 100%; border-radius: 2px; }
    .segment-active { background-color: #e03131; }
    .segment-inactive { background-color: #dee2e6; }

    /* 태그 배지 */
    .tag-container { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
    .tag-badge { background-color: #ffffff; border: 1px solid #e9ecef; color: #495057; font-size: 0.7rem; font-weight: 600; padding: 3px 8px; border-radius: 16px; }

    /* 우측 하단 맨위로 버튼 및 Bottom Spacing */
    .floating-top-btn {
        position: fixed; bottom: 25px; right: 20px; z-index: 999999;
        background-color: #3b5bdb; color: #ffffff !important; padding: 6px 12px;
        border-radius: 50px; font-size: 0.75rem; font-weight: bold; text-decoration: none !important;
        box-shadow: 0 4px 10px rgba(0,0,0,0.15);
    }
    .bottom-spacer { height: 90px !important; display: block; clear: both; }
    </style>

    <a href="#top-section" class="floating-top-btn">▲ 맨위로</a>
    """,
    unsafe_allow_html=True,
)

# 2. 30분 자동 세션 인증 타이머
LOGIN_TIMEOUT_SECONDS = 1800

if st.query_params.get("extend_auth") == "true":
    st.session_state["last_auth_time"] = time.time()
    st.query_params.clear()
    st.rerun()

current_time = time.time()
is_authenticated = st.session_state.get("trade_authenticated", False)

if is_authenticated:
    last_auth = st.session_state.get("last_auth_time", 0)
    elapsed_sec = current_time - last_auth
    remaining_sec = max(0, int(LOGIN_TIMEOUT_SECONDS - elapsed_sec))

    if remaining_sec <= 0:
        st.session_state["trade_authenticated"] = False
        st.session_state["last_auth_time"] = 0
        st.rerun()
    else:
        js_timer_code = f"""
        <script>
        (function() {{
            let remSec = {remaining_sec};
            if (window.authTimer) clearInterval(window.authTimer);
            window.authTimer = setInterval(function() {{
                remSec--;
                if (remSec === 300) {{
                    if (confirm("매매 잠금 해제 만료 5분 전입니다.\\n인증 시간을 연장하시겠습니까?")) {{
                        const url = new URL(window.parent.location.href);
                        url.searchParams.set("extend_auth", "true");
                        window.parent.location.href = url.toString();
                    }}
                }}
            }}, 1000);
        }})();
        </script>
        """
        components.html(js_timer_code, height=0)


def apply_styles(df):
    """표 스타일링 적용 함수"""
    df_s = pd.DataFrame("", index=df.index, columns=df.columns)
    for col in ["변동", "상승금액", "상승률"]:
        if col in df.columns:
            df_s.loc[df[col] > 0, col] += "color: #d62728;"
            df_s.loc[df[col] < 0, col] += "color: #1f77b4;"
    if "상태" in df.columns:
        df_s.loc[df["상태"] == "추천", "상태"] += "color: #d62728; font-weight: bold;"
        df_s.loc[df["상태"] == "매도", "상태"] += "color: #1f77b4; font-weight: bold;"
        df_s.loc[df["상태"] == "보유", "상태"] += "color: #2ca02c; font-weight: bold;"
    if "제외사유" in df.columns:
        df_s.loc[df["제외사유"] != "", "제외사유"] += "color: #888888; font-size: 0.9em;"
        df_s.loc[df["제외사유"] == "조건충족", "제외사유"] += "color: #d62728; font-weight: bold;"
    for col in ["RS(90)", "RS(10)"]:
        if col in df.columns:
            df_s.loc[df[col] > 0, col] += "color: #d62728; font-weight: bold;"
            df_s.loc[df[col] <= 0, col] += "color: #bbbbbb;"

    if "순위" in df.columns:
        for idx, rank in df["순위"].items():
            if pd.notna(rank):
                if rank <= 10:
                    df_s.loc[idx, :] += "background-color: rgba(255, 235, 156, 0.4);"
                elif rank <= 20:
                    df_s.loc[idx, :] += "background-color: rgba(198, 239, 206, 0.4);"
                elif rank <= 30:
                    df_s.loc[idx, :] += "background-color: rgba(189, 215, 238, 0.4);"

    return df_s


def display_trade_list(
    data,
    title,
    button_label,
    key_prefix,
    target_date,
    is_latest_date,
    market_type,
    holdings_df,
    top_n_cfg,
    account_total=0.0,
    strategy_engine_mode="strat3_top7",
):
    """시스템 매수/매도 리스트 렌더링 함수"""
    current_holdings_count = len(holdings_df) if not holdings_df.empty else 0
    needed_slots = max(0, top_n_cfg - current_holdings_count)

    with st.expander(
        f"{title} (보유: {current_holdings_count}/{top_n_cfg}개 | 필요: {needed_slots}개)",
        expanded=True,
    ):
        if data.empty:
            st.write(f"해당되는 {button_label} 종목이 없습니다.")
            return

        target_amount = (
            account_total * ((100.0 / top_n_cfg) / 100.0) if top_n_cfg > 0 else 0.0
        )
        fmt_str = (
            f"${target_amount:,.2f}"
            if market_type == "US"
            else f"{target_amount:,.0f}원"
        )

        if button_label == "매수":
            primary_data = (
                data.iloc[:needed_slots] if needed_slots > 0 else pd.DataFrame()
            )
            backup_data = data.iloc[needed_slots : needed_slots + 2]
            if needed_slots == 0:
                st.warning(
                    f"현재 슬롯 만석입니다 ({current_holdings_count}/{top_n_cfg}개 보유 중). 하단 예비 종목을 참고하세요."
                )
        else:
            primary_data = data
            backup_data = pd.DataFrame()

        for p_idx, (_, row) in enumerate(primary_data.iterrows(), 1):
            ticker = row["ticker"]
            c1, c2 = st.columns([4, 1])

            rank_val = int(row.get("순위", 0)) if pd.notna(row.get("순위")) else "-"
            rec_rank_val = row.get("추천순위", row.get("매수추천순위", ""))
            rec_rank_display = (
                f"{rec_rank_val}위" if (rec_rank_val != "" and pd.notna(rec_rank_val)) else "-"
            )

            raw_reason = str(row.get("제외사유", "")).strip()

            if "매도" in title:
                reason_desc = (
                    f"{raw_reason}"
                    if (raw_reason and raw_reason not in ["조건충족", "nan", "None"])
                    else "시스템 조건 청산"
                )
                position_info = ""
                tag_html = ""
            else:
                if strategy_engine_mode == "short_term":
                    reason_desc = f"단기 모멘텀 타점 포착 [추천순위: {rec_rank_display}]"
                else:
                    reason_desc = f"진입 조건 충족 (지수 2일 안착 완료) [추천순위: {rec_rank_display}]"

                target_pct = (100.0 / top_n_cfg) if top_n_cfg > 0 else 0.0
                atr_val = float(row.get("atr", 0.0))
                atr_str = (
                    f"{atr_val:,.2f}"
                    if market_type == "US"
                    else f"{atr_val:,.0f}"
                )
                position_info = f"<br><span style='font-size: 0.85em; color: #1b5e20; font-weight: bold;'>분산 금액: {fmt_str} ({target_pct:.1f}%) | ATR: {atr_str}</span>"
                tag_html = f"<span style='background-color:#e3f2fd; color:#0d47a1; font-size:0.75em; font-weight:bold; padding:1px 5px; border-radius:3px;'>추천 {p_idx}</span>"

            card_html = (
                f"<div style='line-height: 1.5; margin-top: 2px;'>"
                f"<strong style='font-size: 1.05em; color: #111111;'>{row['종목명']}</strong> "
                f"<span style='font-size: 0.8em; color: #888888;'>({ticker})</span> "
                f"{tag_html} "
                f"<span style='font-size: 0.8em; color: #1565c0; font-weight: bold;'>[순위: {rank_val}위 | 추천: {rec_rank_display}]</span>"
                f"<br><span style='font-size: 0.85em; color: #d62728; font-weight: bold;'>사유: {reason_desc}</span>"
                f"{position_info}"
                f"<br><span style='font-size: 0.8em; color: #444444;'>MOT: {row['MOT']:.2f} | RS(90): {row['RS(90)']:.2f} | 이격: {row['이격도']:+.2f}%</span>"
                f"</div>"
            )
            c1.markdown(card_html, unsafe_allow_html=True)

            if is_latest_date:
                with c2.popover(button_label):
                    st.write(f"**{row['종목명']}**")
                    p_key, q_key, acc_key = (
                        f"p_{key_prefix}_{ticker}",
                        f"q_{key_prefix}_{ticker}",
                        f"acc_{key_prefix}_{ticker}",
                    )
                    input_price = st.number_input(
                        f"{button_label}가",
                        value=float(row["종가"]),
                        key=p_key,
                    )
                    if button_label == "매수":
                        st.number_input(
                            "계좌 총액",
                            value=account_total,
                            step=100.0 if market_type == "US" else 1000000.0,
                            key=acc_key,
                        )
                        calc_qty = max(
                            1.0,
                            (target_amount / input_price)
                            if input_price > 0
                            else 1.0,
                        )
                        input_qty = st.number_input(
                            "수량",
                            value=calc_qty
                            if market_type == "US"
                            else float(int(calc_qty)),
                            min_value=0.0,
                            key=q_key,
                        )
                    else:
                        matched_h = (
                            holdings_df[
                                holdings_df["ticker"]
                                .astype(str)
                                .str.strip()
                                .str.upper()
                                == ticker.strip().upper()
                            ]
                            if not holdings_df.empty
                            else pd.DataFrame()
                        )
                        def_qty = (
                            float(matched_h.iloc[0].get("quantity", 1.0))
                            if not matched_h.empty
                            else 1.0
                        )
                        input_qty = st.number_input(
                            "수량", value=def_qty, min_value=0.0, key=q_key
                        )

                    if st.button("확인", key=f"btn_{key_prefix}_{ticker}"):
                        trade_type = "SELL" if "매도" in title else "BUY"
                        update_holdings(
                            ticker,
                            trade_type,
                            input_price,
                            target_date,
                            input_qty,
                            market_type,
                            exit_reason=reason_desc if trade_type == "SELL" else None
                        )


# DB 설정 로드
if "db_settings_loaded" not in st.session_state:
    try:
        res = (
            supabase.table("strategy_settings")
            .select("*")
            .eq("id", 1)
            .execute()
        )
        if res.data:
            db_cfg = res.data[0]
            st.session_state["kr_capital"] = float(
                db_cfg.get("kr_capital", 20000000.0)
            )
            st.session_state["us_capital"] = float(
                db_cfg.get("us_capital", 6000.0)
            )
            st.session_state["bull_top_n"] = int(db_cfg.get("bull_top_n", 7))
            st.session_state["bull_sl"] = float(db_cfg.get("bull_sl", -2.5))
            st.session_state["bear_top_n"] = int(db_cfg.get("bear_top_n", 4))
            st.session_state["bear_sl"] = float(db_cfg.get("bear_sl", -5.0))
            st.session_state["strategy_engine_mode"] = db_cfg.get(
                "strategy_engine_mode", "strat3_top7"
            )
    except Exception:
        pass
    st.session_state["db_settings_loaded"] = True

all_dates = get_available_dates()
latest_date_default = pd.to_datetime(all_dates[0]) if all_dates else None

# 📌 3. 초슬림 상단 Header & Control 바 (날짜 및 대표 지수 변동 수치 동시 배치)
h_col1, h_col2, h_col3, h_col4 = st.columns([1.2, 0.8, 2.2, 1.2], vertical_alignment="center")

with h_col1:
    st.markdown("<h4 style='margin:0; padding:0; font-weight:900; line-height:1.1;'>Quant Alpha</h4>", unsafe_allow_html=True)

with h_col2:
    market_type = st.segmented_control("Market", options=["KR", "US"], default="KR", label_visibility="collapsed")
    if not market_type:
        market_type = "KR"

target_symbol = "^KS11" if market_type == "KR" else "^GSPC"
target_market_name = "코스피" if market_type == "KR" else "S&P 500"

with h_col3:
    dt_c1, dt_c2 = st.columns([1.1, 1.4], vertical_alignment="center")
    with dt_c1:
        selected_date = st.date_input("Date", value=latest_date_default, label_visibility="collapsed")
    
    target_date_str = (
        pd.to_datetime(selected_date).strftime("%Y-%m-%d") if selected_date else ""
    )

    # 📌 조회일자 기준 해당 시장 지수 정보 & 변동 수치 계산 및 출력
    with dt_c2:
        try:
            res_idx_val = supabase.table("daily_analysis").select("close_price, change_rate").eq("ticker", target_symbol).lte("price_date", target_date_str).order("price_date", desc=True).limit(2).execute()
            if res_idx_val.data and len(res_idx_val.data) > 0:
                cur_close = float(res_idx_val.data[0].get("close_price", 0))
                cur_chg = float(res_idx_val.data[0].get("change_rate", 0))
                
                prev_close = float(res_idx_val.data[1].get("close_price", cur_close)) if len(res_idx_val.data) > 1 else cur_close
                diff_val = cur_close - prev_close

                fmt_close = f"{cur_close:,.2f}"
                diff_color = "#d62728" if cur_chg > 0 else ("#1f77b4" if cur_chg < 0 else "#495057")
                sign_str = "+" if cur_chg > 0 else ""

                idx_info_html = f"""<div style="font-size:0.78rem; font-weight:700; color:#212529; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                    {target_market_name} <span style="font-weight:800;">{fmt_close}</span> 
                    <span style="color:{diff_color}; font-weight:bold;">({sign_str}{diff_val:,.2f} / {sign_str}{cur_chg:.2f}%)</span>
                </div>"""
                st.markdown(idx_info_html, unsafe_allow_html=True)
        except Exception:
            st.markdown(f"<div style='font-size:0.75rem; color:#868e96;'>{target_market_name} 정보 로딩중...</div>", unsafe_allow_html=True)

with h_col4:
    if is_authenticated:
        elapsed = time.time() - st.session_state.get("last_auth_time", 0)
        remaining_sec = max(0, int(LOGIN_TIMEOUT_SECONDS - elapsed))
        rem_min, rem_sec = remaining_sec // 60, remaining_sec % 60

        c_time, c_ext, c_setting = st.columns([1.1, 0.9, 0.8], vertical_alignment="center")
        c_time.markdown(f"<div style='font-size:0.75rem; color:#0b7285; font-weight:bold; text-align:right;'>{rem_min}:{rem_sec:02d}</div>", unsafe_allow_html=True)
        with c_ext:
            if st.button("연장", key="btn_header_extend", use_container_width=True):
                st.session_state["last_auth_time"] = time.time()
                st.rerun()
        with c_setting:
            with st.popover("⚙️", use_container_width=True):
                st.markdown("#### 전략 설정")
                sel_engine_display = st.radio(
                    "전략 엔진 선택",
                    ["전략 3: Top 7 Regime", "단기 타점 모멘텀", "Ultimate 듀얼 모멘텀"],
                    index=0 if st.session_state.get("strategy_engine_mode") == "strat3_top7" else (1 if st.session_state.get("strategy_engine_mode") == "short_term" else 2),
                    key="pop_engine_select"
                )

                pop_engine_key = "strat3_top7" if "전략 3" in sel_engine_display else ("short_term" if "단기" in sel_engine_display else "ultimate_dual")

                pop_strategy_mode = st.radio(
                    "운용 모드 선택",
                    ["자동 감지", "상승장 (Bull)", "하락장 (Bear)"],
                    horizontal=True,
                    key="pop_mode_select"
                )

                pop_rebal_cycle = st.selectbox(
                    "리밸런싱 주기",
                    ["상시 (빈자리 즉시 채우기)", "주기 (매주 수요일)"],
                    key="pop_rebal_select"
                )

                if st.button("적용", type="primary", use_container_width=True, key="pop_btn_apply"):
                    st.session_state["strategy_engine_mode"] = pop_engine_key
                    st.session_state["pop_saved_mode"] = pop_strategy_mode
                    st.session_state["pop_saved_rebal"] = pop_rebal_cycle
                    st.rerun()

                if st.button("화면 잠금", use_container_width=True, key="pop_btn_lock"):
                    st.session_state["trade_authenticated"] = False
                    st.session_state["last_auth_time"] = 0
                    st.rerun()
    else:
        c_p1, c_p2 = st.columns([2.5, 1.2], vertical_alignment="center")
        with c_p1:
            input_pwd_global = st.text_input("PW", type="password", key="global_pwd_input", label_visibility="collapsed", placeholder="비밀번호")
        with c_p2:
            if st.button("해제", key="btn_global_unlock", type="primary", use_container_width=True):
                if input_pwd_global == st.secrets.get("TRADE_PASSWORD", "1234"):
                    st.session_state["trade_authenticated"] = True
                    st.session_state["last_auth_time"] = time.time()
                    st.rerun()
                else:
                    st.error("불일치")

current_engine_key = st.session_state.get("strategy_engine_mode", "strat3_top7")
market_safe, stop_new_buy, reduce_holdings = get_market_regime(market_type, target_date_str)
saved_mode = st.session_state.get("pop_saved_mode", "자동 감지")
is_bull = True if "상승장" in saved_mode else (False if "하락장" in saved_mode else market_safe)
rebalance_cycle = st.session_state.get("pop_saved_rebal", "상시 (빈자리 즉시 채우기)")

if current_engine_key == "strat3_top7":
    top_n_cfg = 7
    sl_cfg = -2.5
    rank_exit_limit = 15
elif current_engine_key == "short_term":
    top_n_cfg = st.session_state.get("bull_top_n", 4)
    sl_cfg = st.session_state.get("bull_sl", -5.0)
    rank_exit_limit = 200
else:
    if is_bull:
        top_n_cfg = st.session_state.get("bull_top_n", 5)
        sl_cfg = st.session_state.get("bull_sl", -10.0)
        rank_exit_limit = 60
    else:
        top_n_cfg = st.session_state.get("bear_top_n", 3)
        sl_cfg = st.session_state.get("bear_sl", -6.0)
        rank_exit_limit = 30

cap_key = "us_capital" if market_type == "US" else "kr_capital"
default_cap = st.session_state.get(cap_key, 6000.0 if market_type == "US" else 20000000.0)
account_total_input = float(default_cap)

df_display = get_data(
    selected_date,
    all_dates,
    market_type,
    top_n_cfg,
    sl_cfg,
    rebalance_cycle,
    is_bull,
    stop_new_buy,
    reduce_holdings,
    strategy_engine_mode=current_engine_key,
)

if df_display is not None:
    if "매수추천순위" in df_display.columns:
        df_display = df_display.rename(columns={"매수추천순위": "추천순위"})

    if "매매상태" in df_display.columns:
        df_display["매매상태"] = df_display["매매상태"].replace({
            "매수추천": "추천",
            "매수필요": "매수",
            "매도필요": "매도",
            "보유중": "보유",
        })

    is_latest_date = (target_date_str == max(all_dates)) if all_dates and target_date_str else False

    current_table_name = get_holdings_table(market_type)
    try:
        holdings_res = supabase.table(current_table_name).select("*").is_("sell_date", "null").execute()
        holdings_db = pd.DataFrame(holdings_res.data) if holdings_res.data else pd.DataFrame()
    except Exception:
        holdings_db = pd.DataFrame()

    current_holdings_count = len(holdings_db) if not holdings_db.empty else 0
    needed_slots = max(0, top_n_cfg - current_holdings_count)

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "오늘",
        "시그널",
        "주문 지시서",
        "성과",
        "백테스트",
    ])

    # TAB 1: 오늘
    with tab1:
        try:
            chk_res = (
                supabase.table("daily_analysis")
                .select("close_price, ma20, ma200")
                .eq("ticker", target_symbol)
                .lte("price_date", target_date_str)
                .order("price_date", desc=True)
                .limit(3)
                .execute()
            )
            if chk_res.data and len(chk_res.data) > 0:
                c_p = float(chk_res.data[0].get("close_price", 0))
                m_20 = float(chk_res.data[0].get("ma20", 0))
                m_200 = float(chk_res.data[0].get("ma200", 0))
                if c_p < m_20:
                    reduce_holdings = True
                    if len(chk_res.data) >= 3:
                        below_cnt = sum(1 for r in chk_res.data if float(r.get("close_price", 0)) < float(r.get("ma20", 0)))
                        if below_cnt >= 3:
                            stop_new_buy = True
        except Exception:
            m_200 = 0

        if stop_new_buy:
            action_title = "신규 매수 중지"
            action_desc = f"{target_market_name} 지수가 MA20 아래에 3일 연속 머물러 신규 매수를 중단합니다."
            regime_label = "Regime · 하락 (Bear)"
            regime_tooltip = f"{target_market_name} 지수가 MA20을 3일 연속 하회하여 신규 매수가 중지된 상태입니다."
        elif reduce_holdings:
            action_title = "보유 비중 축소"
            action_desc = f"{target_market_name} 지수가 MA20 아래에 있어 관망 및 기존 포지션 비중 축소를 권장합니다."
            regime_label = "Regime · 경계 (Caution)"
            regime_tooltip = f"{target_market_name} 지수가 MA20 아래에 위치하여 매수 자제 및 기존 비중 축소가 권장됩니다."
        else:
            action_title = "정상 매수 & 보유"
            action_desc = f"{target_market_name} 지수가 MA20/MA200 위에 안착하여 알파 주도주 중심의 매수가 허용됩니다."
            regime_label = "Regime · 상승 (Bull)"
            regime_tooltip = f"{target_market_name} 지수가 MA20 위에 위치하여 전략에 따라 매수가 허용된 상태입니다."

        buy_cnt = len(df_display[df_display["매매상태"] == "추천"])
        buy_cnt_display = min(buy_cnt, needed_slots)
        sell_cnt = len(df_display[df_display["매매상태"] == "매도"])

        buy_val_color = "#d62728" if buy_cnt_display > 0 else "#212529"

        action_card_html = f"""<div class="action-card">
<div class="action-card-header">
<div class="action-card-subtitle">오늘의 행동 ({market_type})</div>
<div class="regime-badge">{regime_label}</div>
</div>
<div class="action-card-title">{action_title}</div>
<div class="action-card-desc">{action_desc}</div>
<div class="action-stats-grid">
<div class="stat-box">
<div class="stat-box-label">잔여 슬롯</div>
<div class="stat-box-value">{current_holdings_count} / {top_n_cfg}</div>
</div>
<div class="stat-box">
<div class="stat-box-label">추천 종목</div>
<div class="stat-box-value" style="color: {buy_val_color};">{buy_cnt_display}개</div>
</div>
<div class="stat-box">
<div class="stat-box-label">매도 필요</div>
<div class="stat-box-value" style="color: {'#1f77b4' if sell_cnt > 0 else '#2ca02c'};">{sell_cnt}개 <span style="font-size:0.7rem; font-weight:normal;">{'청산' if sell_cnt > 0 else '정상'}</span></div>
</div>
</div>
</div>"""

        st.markdown(action_card_html, unsafe_allow_html=True)

        with st.popover("ⓘ 지수 Regime 및 수급 지표 도움말"):
            st.markdown(f"**📌 Regime 상태 ({regime_label})**")
            st.caption(regime_tooltip)
            st.markdown("---")
            st.markdown("**📌 비차익 Z-Score (KR 전용)**")
            st.caption("최근 20영업일 비차익 순매수 유입 강도입니다. (+1.5 이상: 강한 유입 / -1.5 이하: 강한 이탈)")

        with st.expander("🤖 Gemini 시장 전체 스마트머니 흐름 & 주도 섹터 AI 진단", expanded=False):
            used_cnt, remain_cnt = get_remaining_quota()
            st.caption(f"Gemini AI 잔여 사용량: **{remain_cnt}/{MAX_DAILY_QUOTA}회**")
            
            if st.button("시장 전체 스마트머니 자금 흐름 AI 진단 실행", type="primary", key="btn_run_smart_money_ai_tab1", use_container_width=True):
                with st.spinner(f"[{market_type}] 시장 전체 수급 및 주도 섹터를 Gemini AI로 분석 중입니다..."):
                    top_liq_names = []
                    if market_type == "KR":
                        try:
                            res_top_liq = supabase.table("daily_top_liquidity").select("name, foreign_net, inst_net").lte("trade_date", target_date_str).order("trade_date", desc=True).limit(100).execute()
                            if res_top_liq.data:
                                df_top_agg = pd.DataFrame(res_top_liq.data).groupby("name").sum(numeric_only=True)
                                df_top_agg["total_net"] = df_top_agg["foreign_net"] + df_top_agg["inst_net"]
                                top_liq_names = df_top_agg.sort_values("total_net", ascending=False).head(10).index.tolist()
                        except Exception:
                            pass

                    summary_market_data = {
                        "시장타입": market_type,
                        "조회일자": target_date_str,
                        "시장상태": action_title,
                        "잔여슬롯": f"{current_holdings_count}/{top_n_cfg}",
                        "추천종목수": f"{buy_cnt_display}개",
                        "수급상위주요종목": ", ".join(top_liq_names) if top_liq_names else "해당없음/집계중",
                    }
                    ai_res = analyze_stock_with_gemini(target_symbol, f"{target_market_name} 시장 수급 및 주도 섹터 종합", summary_market_data, "스마트머니 수급 분석")
                    st.success("시장 AI 분석 완료")
                    st.markdown(ai_res)

        st.markdown(
            """<div class="tag-container">
<span class="tag-badge">전략 3</span>
<span class="tag-badge">Top 7</span>
<span class="tag-badge">Rank ≤ 15</span>
<span class="tag-badge">ATR 2.5x 손절</span>
<span class="tag-badge">+8% 본전스탑</span>
</div>""",
            unsafe_allow_html=True
        )

        st.write("")

        if market_type == "US":
            st.info("💡 **미국 시장(US) 안내**: 미국장은 수급 데이터 대신 S&P 500 지수 추세 및 종목별 모멘텀 지표(Rank, RS)를 바탕으로 전략이 동작합니다.")
        else:
            st.markdown(f"<div style='display:flex; justify-content:space-between; align-items:center;'><strong>수급 요약</strong> <span style='font-size:0.75rem; color:#868e96;'>{target_date_str} 기준</span></div>", unsafe_allow_html=True)
            st.write("")

            p_zscore = 0.0
            z_tag = "초기상태"
            k_f_5d_tr, k_i_5d_tr = 0, 0
            k_f_cum_10d, k_i_cum_10d = 0.0, 0.0

            try:
                res_inv_all = supabase.table("market_investor_trends").select("*").lte("trade_date", target_date_str).order("trade_date", desc=True).limit(30).execute()
                df_inv_all = pd.DataFrame(res_inv_all.data) if res_inv_all.data else pd.DataFrame()

                res_prog_all = supabase.table("market_program_trends").select("*").lte("trade_date", target_date_str).order("trade_date", desc=True).limit(30).execute()
                df_prog_all = pd.DataFrame(res_prog_all.data) if res_prog_all.data else pd.DataFrame()
            except Exception:
                df_inv_all, df_prog_all = pd.DataFrame(), pd.DataFrame()

            if not df_prog_all.empty and len(df_prog_all) >= 5:
                p_non_series = df_prog_all.head(20)["non_arbitrage_net"].astype(float)
                m_20_p = p_non_series.mean()
                s_20_p = p_non_series.std()
                cur_p = float(df_prog_all.iloc[0].get("non_arbitrage_net", 0))
                p_zscore = ((cur_p - m_20_p) / s_20_p) if s_20_p > 0 else 0.0

            z_tag = "강한 유입" if p_zscore >= 1.5 else ("강한 이탈" if p_zscore <= -1.5 else "정상 범위")

            if not df_inv_all.empty:
                df_k_inv = df_inv_all[df_inv_all["market_type"] == "KOSPI"]
                k_f_5d_tr = (df_k_inv.head(10)["foreign_net"] > 0).sum() if not df_k_inv.empty else 0
                k_i_5d_tr = (df_k_inv.head(10)["institution_net"] > 0).sum() if not df_k_inv.empty else 0
                
                k_f_val = float(df_k_inv.iloc[0].get("foreign_net", 0)) / 1000000.0 if not df_k_inv.empty else 0.0
                k_i_val = float(df_k_inv.iloc[0].get("institution_net", 0)) / 1000000.0 if not df_k_inv.empty else 0.0

                k_f_cum_10d = float(df_k_inv.head(10)["foreign_net"].sum()) / 1000000.0 if not df_k_inv.empty else 0.0
                k_i_cum_10d = float(df_k_inv.head(10)["institution_net"].sum()) / 1000000.0 if not df_k_inv.empty else 0.0
            else:
                k_f_val, k_i_val = 0.0, 0.0

            st.markdown(
                f"""<div class="gauge-card">
<div class="gauge-card-header">
<span class="gauge-title">비차익 Z</span>
<span class="gauge-tag">{z_tag}</span>
</div>
<div class="gauge-value" style="color: {'#d62728' if p_zscore >= 0 else '#1f77b4'};">{p_zscore:+.2f}</div>
</div>""",
                unsafe_allow_html=True
            )

            f_bars = "".join([f'<div class="gauge-segment segment-active"></div>' if i < k_f_5d_tr else '<div class="gauge-segment segment-inactive"></div>' for i in range(10)])
            st.markdown(
                f"""<div class="gauge-card">
<div class="gauge-card-header">
<span class="gauge-title">코스피 외국인</span>
<span class="gauge-tag">당일 {k_f_val:+.2f}조 · 10일 중 {k_f_5d_tr}일 순매수</span>
</div>
<div class="gauge-value" style="color: {'#d62728' if k_f_val >= 0 else '#1f77b4'};">{k_f_val:+.2f}조원</div>
<div class="gauge-subtext">10일 누적 {k_f_cum_10d:+.2f}조원</div>
<div class="gauge-bar-bg">{f_bars}</div>
</div>""",
                unsafe_allow_html=True
            )

            i_bars = "".join([f'<div class="gauge-segment segment-active"></div>' if i < k_i_5d_tr else '<div class="gauge-segment segment-inactive"></div>' for i in range(10)])
            st.markdown(
                f"""<div class="gauge-card">
<div class="gauge-card-header">
<span class="gauge-title">코스피 기관</span>
<span class="gauge-tag">당일 {k_i_val:+.2f}조 · 10일 중 {k_i_5d_tr}일 순매수</span>
</div>
<div class="gauge-value" style="color: {'#d62728' if k_i_val >= 0 else '#1f77b4'};">{k_i_val:+.2f}조원</div>
<div class="gauge-subtext">10일 누적 {k_i_cum_10d:+.2f}조원</div>
<div class="gauge-bar-bg">{i_bars}</div>
</div>""",
                unsafe_allow_html=True
            )

            st.write("")

            st.markdown(f"<div style='display:flex; justify-content:space-between; align-items:center;'><strong>주체별 매매 동향</strong> <span style='font-size:0.7rem; color:#868e96;'>단위 억원</span></div>", unsafe_allow_html=True)
            st.write("")

            k_row = df_inv_all[df_inv_all["market_type"] == "KOSPI"].iloc[0] if not df_inv_all.empty and not df_inv_all[df_inv_all["market_type"] == "KOSPI"].empty else {}
            kq_row = df_inv_all[df_inv_all["market_type"] == "KOSDAQ"].iloc[0] if not df_inv_all.empty and not df_inv_all[df_inv_all["market_type"] == "KOSDAQ"].empty else {}

            disp_inv_summary = pd.DataFrame([
                {
                    "시장": "KOSPI",
                    "외국인": float(pd.to_numeric(k_row.get("foreign_net", 0), errors="coerce") or 0) / 100.0,
                    "개인": float(pd.to_numeric(k_row.get("individual_net", 0), errors="coerce") or 0) / 100.0,
                    "기관": float(pd.to_numeric(k_row.get("institution_net", 0), errors="coerce") or 0) / 100.0,
                },
                {
                    "시장": "KOSDAQ",
                    "외국인": float(pd.to_numeric(kq_row.get("foreign_net", 0), errors="coerce") or 0) / 100.0,
                    "개인": float(pd.to_numeric(kq_row.get("individual_net", 0), errors="coerce") or 0) / 100.0,
                    "기관": float(pd.to_numeric(kq_row.get("institution_net", 0), errors="coerce") or 0) / 100.0,
                },
            ])

            st.dataframe(
                disp_inv_summary.style.format({
                    "외국인": "{:+,.0f}억",
                    "개인": "{:+,.0f}억",
                    "기관": "{:+,.0f}억",
                }).map(
                    lambda v: "color: #d62728;" if v > 0 else ("color: #1f77b4;" if v < 0 else ""),
                    subset=["외국인", "개인", "기관"],
                ),
                hide_index=True,
                use_container_width=True,
            )

            st.write("")

            st.markdown("<div style='display:flex; justify-content:space-between; align-items:center;'><strong>수급 상위 종목</strong> <span style='font-size:0.75rem; color:#868e96;'>단위 억원</span></div>", unsafe_allow_html=True)
            st.write("")

            try:
                res_liq_10d = supabase.table("daily_top_liquidity").select("*").lte("trade_date", target_date_str).order("trade_date", desc=True).limit(300).execute()
                df_liq_10d = pd.DataFrame(res_liq_10d.data) if res_liq_10d.data else pd.DataFrame()
            except Exception:
                df_liq_10d = pd.DataFrame()

            df_stock_liq = df_liq_10d[df_liq_10d["trade_date"] == target_date_str] if not df_liq_10d.empty else pd.DataFrame()

            sub_tab_selected = st.segmented_control(
                "수급 종목 분류",
                options=["외인 TOP5", "기관 TOP5", "외인 빈도", "기관 빈도"],
                default="외인 TOP5",
                label_visibility="collapsed"
            )

            if sub_tab_selected == "외인 TOP5":
                if not df_stock_liq.empty:
                    df_f_top = df_stock_liq.sort_values("foreign_net", ascending=False).head(5).copy()
                    df_f_top["종목 (티커)"] = df_f_top.apply(lambda r: f"{r['name']} ({r['ticker']})", axis=1)
                    df_f_top["외인/기관 순매수"] = df_f_top.apply(lambda r: f"외: {float(r['foreign_net'])/100:+,.0f}억\n기: {float(r['inst_net'])/100:+,.0f}억", axis=1)
                    df_f_top["등락률_val"] = df_f_top["change_rate"]
                    
                    st.dataframe(
                        df_f_top[["종목 (티커)", "등락률_val", "외인/기관 순매수"]].rename(columns={"등락률_val": "등락률"}).style.format({
                            "등락률": "{:+.2f}%",
                        }).map(lambda v: "color: #d62728;" if float(v) > 0 else ("color: #1f77b4;" if float(v) < 0 else ""), subset=["등락률"]),
                        hide_index=True,
                        use_container_width=True
                    )
                else:
                    st.info("당일 수급 데이터 집계 중입니다.")

            elif sub_tab_selected == "기관 TOP5":
                if not df_stock_liq.empty:
                    df_i_top = df_stock_liq.sort_values("inst_net", ascending=False).head(5).copy()
                    df_i_top["종목 (티커)"] = df_i_top.apply(lambda r: f"{r['name']} ({r['ticker']})", axis=1)
                    df_i_top["외인/기관 순매수"] = df_i_top.apply(lambda r: f"기: {float(r['inst_net'])/100:+,.0f}억\n외: {float(r['foreign_net'])/100:+,.0f}억", axis=1)
                    df_i_top["등락률_val"] = df_i_top["change_rate"]

                    st.dataframe(
                        df_i_top[["종목 (티커)", "등락률_val", "외인/기관 순매수"]].rename(columns={"등락률_val": "등락률"}).style.format({
                            "등락률": "{:+.2f}%",
                        }).map(lambda v: "color: #d62728;" if float(v) > 0 else ("color: #1f77b4;" if float(v) < 0 else ""), subset=["등락률"]),
                        hide_index=True,
                        use_container_width=True
                    )
                else:
                    st.info("당일 수급 데이터 집계 중입니다.")

            elif sub_tab_selected == "외인 빈도":
                if not df_liq_10d.empty:
                    df_f_pos = df_liq_10d[df_liq_10d["foreign_net"] > 0]
                    freq_f = df_f_pos.groupby(["ticker", "name"]).agg(빈도수=("trade_date", "nunique"), 누적순매수=("foreign_net", "sum")).reset_index().sort_values("빈도수", ascending=False).head(5)
                    freq_f["종목 (티커)"] = freq_f.apply(lambda r: f"{r['name']} ({r['ticker']})", axis=1)
                    freq_f["누적순매수(억)"] = freq_f["누적순매수"] / 100.0
                    
                    st.dataframe(
                        freq_f[["종목 (티커)", "빈도수", "누적순매수(억)"]].style.format({
                            "누적순매수(억)": "{:+,.0f}억",
                        }).map(lambda v: "color: #d62728;" if float(v) > 0 else ("color: #1f77b4;" if float(v) < 0 else ""), subset=["누적순매수(억)"]),
                        hide_index=True,
                        use_container_width=True
                    )

            elif sub_tab_selected == "기관 빈도":
                if not df_liq_10d.empty:
                    df_i_pos = df_liq_10d[df_liq_10d["inst_net"] > 0]
                    freq_i = df_i_pos.groupby(["ticker", "name"]).agg(빈도수=("trade_date", "nunique"), 누적순매수=("inst_net", "sum")).reset_index().sort_values("빈도수", ascending=False).head(5)
                    freq_i["종목 (티커)"] = freq_i.apply(lambda r: f"{r['name']} ({r['ticker']})", axis=1)
                    freq_i["누적순매수(억)"] = freq_i["누적순매수"] / 100.0

                    st.dataframe(
                        freq_i[["종목 (티커)", "빈도수", "누적순매수(억)"]].style.format({
                            "누적순매수(억)": "{:+,.0f}억",
                        }).map(lambda v: "color: #d62728;" if float(v) > 0 else ("color: #1f77b4;" if float(v) < 0 else ""), subset=["누적순매수(억)"]),
                        hide_index=True,
                        use_container_width=True
                    )

            with st.expander("당일 수급 포착 전체 종목 목록", expanded=False):
                if not df_stock_liq.empty:
                    disp_all_supp = df_stock_liq[["rank", "name", "ticker", "close_price", "change_rate", "foreign_net", "inst_net"]].copy()
                    disp_all_supp["foreign_net"] = disp_all_supp["foreign_net"] / 100.0
                    disp_all_supp["inst_net"] = disp_all_supp["inst_net"] / 100.0
                    disp_all_supp = disp_all_supp.rename(columns={"rank": "순위", "name": "종목명", "ticker": "티커", "close_price": "종가", "change_rate": "등락률", "foreign_net": "외국인(억)", "inst_net": "기관(억)"})
                    st.dataframe(
                        disp_all_supp.style.format({"종가": "{:,.0f}원", "등락률": "{:+.2f}%", "외국인(억)": "{:+,.0f}억", "기관(억)": "{:+,.0f}억"})
                        .map(lambda v: "color: #d62728;" if float(v) > 0 else ("color: #1f77b4;" if float(v) < 0 else ""), subset=["등락률", "외국인(억)", "기관(억)"]),
                        hide_index=True, use_container_width=True
                    )

        st.write("")

        # 지수 차트
        index_chart_title = f"{target_market_name} 지수 · MA20/50/200"
        with st.expander(index_chart_title, expanded=True):
            try:
                res_idx_chart = supabase.table("daily_analysis").select("price_date, close_price, ma20, ma50, ma200").eq("ticker", target_symbol).lte("price_date", target_date_str).order("price_date", desc=True).limit(120).execute()
                if res_idx_chart.data:
                    df_idx_c = pd.DataFrame(res_idx_chart.data)
                    df_idx_c["price_date_dt"] = pd.to_datetime(df_idx_c["price_date"])
                    df_idx_c = df_idx_c.sort_values("price_date_dt").reset_index(drop=True)

                    df_idx_c["below_ma20"] = df_idx_c["close_price"] < df_idx_c["ma20"]
                    df_idx_c["ma20_breakdown"] = df_idx_c["below_ma20"] & (~df_idx_c["below_ma20"].shift(1, fill_value=False))

                    fig_market_idx = gg.Figure()
                    fig_market_idx.add_trace(gg.Scatter(x=df_idx_c["price_date_dt"], y=df_idx_c["close_price"], mode="lines", name=f"{target_market_name} 종가", line=dict(color="#3b5bdb", width=2)))
                    if "ma20" in df_idx_c.columns:
                        fig_market_idx.add_trace(gg.Scatter(x=df_idx_c["price_date_dt"], y=df_idx_c["ma20"], mode="lines", name="MA20", line=dict(color="#ff922b", width=1.5, dash="dash")))
                    if "ma200" in df_idx_c.columns:
                        fig_market_idx.add_trace(gg.Scatter(x=df_idx_c["price_date_dt"], y=df_idx_c["ma200"], mode="lines", name="MA200", line=dict(color="#e03131", width=1.5, dash="dot")))

                    breakdown_df = df_idx_c[df_idx_c["ma20_breakdown"]]
                    if not breakdown_df.empty:
                        fig_market_idx.add_trace(gg.Scatter(
                            x=breakdown_df["price_date_dt"],
                            y=breakdown_df["close_price"],
                            mode="markers",
                            name="MA20 이탈점",
                            marker=dict(symbol="x", size=9, color="#f59f00", line=dict(width=2, color="#f59f00"))
                        ))

                    fig_market_idx.update_layout(height=260, margin=dict(l=10, r=10, t=20, b=20))
                    st.plotly_chart(fig_market_idx, use_container_width=True, config={'scrollZoom': False})
                else:
                    st.info(f"[{target_market_name}] 지수 시계열 데이터가 존재하지 않습니다.")
            except Exception as e:
                st.error(f"지수 차트 로드 실패: {e}")

        # KR 전용 차트들
        if market_type == "KR":
            with st.expander("코스피 외국인 + 기관 합산 수급 추이 (30일)", expanded=False):
                if not df_inv_all.empty:
                    df_k_chart = df_inv_all[df_inv_all["market_type"] == "KOSPI"].head(30).sort_values("trade_date").copy()
                    if not df_k_chart.empty:
                        df_k_chart["trade_date_dt"] = pd.to_datetime(df_k_chart["trade_date"])
                        df_k_chart["f_val"] = pd.to_numeric(df_k_chart["foreign_net"], errors="coerce").fillna(0)
                        df_k_chart["i_val"] = pd.to_numeric(df_k_chart["institution_net"], errors="coerce").fillna(0)
                        df_k_chart["smart_sum"] = df_k_chart["f_val"] + df_k_chart["i_val"]
                        df_k_chart["smart_cum"] = df_k_chart["smart_sum"].cumsum()

                        fig_smart = gg.Figure()
                        fig_smart.add_trace(gg.Bar(x=df_k_chart["trade_date_dt"], y=df_k_chart["smart_sum"], name="일별 합산", marker_color=np.where(df_k_chart["smart_sum"] >= 0, "#d62728", "#1f77b4")))
                        fig_smart.add_trace(gg.Scatter(x=df_k_chart["trade_date_dt"], y=df_k_chart["smart_cum"], mode="lines+markers", name="30일 누적", line=dict(color="#2ca02c", width=2.5)))
                        fig_smart.update_layout(height=250, margin=dict(l=10, r=10, t=20, b=20))
                        st.plotly_chart(fig_smart, use_container_width=True, config={'scrollZoom': False})

            with st.expander("수급 추이 · 차트 3개", expanded=False):
                draw_market_supply_chart(target_date_str)

    # TAB 2: 시그널
    with tab2:
        st.markdown("###### 알파 시그널 스크리닝 (모멘텀 순위 상위 200위)")
        filter_opt = st.radio(
            "빠른 필터",
            ["전체보기", "추천 종목만", "매도 종목만", "보유 종목만"],
            horizontal=True,
            label_visibility="collapsed",
        )

        df_target = df_display.head(200).copy()
        if "atr" not in df_target.columns:
            df_target["atr"] = 0.0

        col_order = [
            "순위",
            "추천순위",
            "변동",
            "매매상태",
            "종목명",
            "이격도",
            "MOT",
            "RS(90)",
            "RS(10)",
            "MA20",
            "atr",
            "제외사유",
            "종가",
            "상승금액",
            "상승률",
            "ticker",
        ]
        df_target = df_target[col_order].rename(columns={
            "추천순위": "추천순위",
            "매매상태": "상태",
            "이격도": "이격(%)",
            "atr": "ATR",
        })

        if filter_opt == "추천 종목만":
            df_target = df_target[df_target["상태"] == "추천"]
        elif filter_opt == "매도 종목만":
            df_target = df_target[df_target["상태"] == "매도"]
        elif filter_opt == "보유 종목만":
            df_target = df_target[df_target["상태"] == "보유"]

        if df_target.empty:
            st.info("해당되는 종목이 없습니다.")
        else:
            fmt_dict = {
                "이격(%)": lambda x: f"{x:+.2f}%" if x != 0 else "-",
                "MOT": "{:.2f}",
                "RS(90)": "{:.2f}",
                "RS(10)": "{:.2f}",
                "MA20": "{:,.2f}" if market_type == "US" else "{:,.0f}",
                "ATR": "{:,.2f}" if market_type == "US" else "{:,.0f}",
                "종가": "{:,.2f}" if market_type == "US" else "{:,.0f}",
                "상승금액": "{:+,.2f}" if market_type == "US" else "{:+,.0f}",
                "상승률": "{:+.2f}%",
            }

            event = st.dataframe(
                df_target.style.apply(apply_styles, axis=None).format(fmt_dict),
                hide_index=True,
                use_container_width=True,
                on_select="rerun",
                selection_mode="single-row",
                key="overview_table_selection",
            )

            if event and event.get("selection", {}).get("rows"):
                selected_row_idx = event["selection"]["rows"][0]
                selected_row = df_target.iloc[selected_row_idx]
                clicked_ticker = str(selected_row["ticker"]).strip().upper()

                if st.session_state.get("last_selected_row_idx") != selected_row_idx:
                    st.session_state["last_selected_row_idx"] = selected_row_idx
                    st.session_state["tab2_integrated_chart_selector"] = clicked_ticker
                    st.rerun()

        st.write("")

        top200_tickers = [str(t).strip().upper() for t in df_display.head(200)["ticker"].tolist()]
        ticker_name_map = dict(zip(df_display["ticker"].astype(str).str.strip().str.upper(), df_display["종목명"]))

        current_selected = st.session_state.get("tab2_integrated_chart_selector")
        if current_selected and current_selected not in top200_tickers:
            top200_tickers.insert(0, current_selected)

        default_idx = top200_tickers.index(current_selected) if current_selected in top200_tickers else 0

        with st.expander("개별 종목 통합 분석 센터", expanded=True):
            sel_chart_ticker = st.selectbox(
                "분석 대상 종목 선택",
                options=top200_tickers,
                index=default_idx,
                format_func=lambda x: f"[{x}] {ticker_name_map.get(x, x)}",
                key="tab2_integrated_chart_selector",
                label_visibility="collapsed"
            )

            if sel_chart_ticker:
                supply_dates = []
                try:
                    res_supp = supabase.table("daily_top_liquidity").select("trade_date").eq("ticker", sel_chart_ticker).or_("foreign_net.gt.0,inst_net.gt.0").execute()
                    if res_supp.data:
                        supply_dates = [r["trade_date"] for r in res_supp.data]
                except Exception:
                    pass

                matched_row = df_display[df_display["ticker"] == sel_chart_ticker]
                sel_rank_val = matched_row["순위"].values[0] if not matched_row.empty and "순위" in matched_row.columns else None

                st.markdown("###### 기술적 차트")
                draw_integrated_chart(sel_chart_ticker, market_type, ticker_name_map, supply_dates=supply_dates, rank_val=sel_rank_val)

                if market_type == "KR":
                    st.write("")
                    st.markdown("###### 외국인 vs 기관 누적 수급 동향")
                    try:
                        res_s = supabase.table("daily_top_liquidity").select("*").eq("ticker", sel_chart_ticker).order("trade_date", desc=True).limit(15).execute()
                        df_s_stock = pd.DataFrame(res_s.data) if res_s.data else pd.DataFrame()
                    except Exception:
                        df_s_stock = pd.DataFrame()

                    if not df_s_stock.empty:
                        df_s_stock = df_s_stock.sort_values("trade_date").copy()
                        df_s_stock["f_cum"] = df_s_stock["foreign_net"].cumsum()
                        df_s_stock["i_cum"] = df_s_stock["inst_net"].cumsum()
                        df_s_stock["trade_date_dt"] = pd.to_datetime(df_s_stock["trade_date"])

                        c_s1, c_s2 = st.columns([1.2, 1.0])
                        with c_s1:
                            fig_s = gg.Figure()
                            fig_s.add_trace(gg.Scatter(x=df_s_stock["trade_date_dt"], y=df_s_stock["f_cum"], mode="lines+markers", name="외국인 누적", line=dict(color="#d62728", width=2)))
                            fig_s.add_trace(gg.Scatter(x=df_s_stock["trade_date_dt"], y=df_s_stock["i_cum"], mode="lines+markers", name="기관 누적", line=dict(color="#2ca02c", width=2)))
                            fig_s.update_layout(height=240, margin=dict(l=10, r=10, t=20, b=20))
                            st.plotly_chart(fig_s, use_container_width=True, config={'scrollZoom': False})
                        with c_s2:
                            disp_s = df_s_stock[["trade_date", "close_price", "foreign_net", "inst_net"]].sort_values("trade_date", ascending=False).rename(columns={"trade_date": "일자", "close_price": "종가", "foreign_net": "외국인", "inst_net": "기관"})
                            st.dataframe(disp_s.style.format({"종가": "{:,.0f}원", "외국인": "{:+,.0f}", "기관": "{:+,.0f}"}).map(lambda v: "color: #d62728;" if float(v) > 0 else ("color: #1f77b4;" if float(v) < 0 else ""), subset=["외국인", "기관"]), hide_index=True, use_container_width=True)

                st.write("")
                st.markdown("###### Gemini AI 종목 분석")
                col_opt, col_btn = st.columns([2.5, 1.5])
                with col_opt:
                    analysis_option = st.selectbox("분석 항목 선택", ["종합 기본적 분석", "스마트머니 & 섹터 주도주 분석", "ROE 듀퐁 분석", "사업 구조", "퀀트 밸류에이션", "단/중기 시나리오"], key="tab2_gemini_opt")
                with col_btn:
                    st.write("")
                    run_ai_btn = st.button("AI 분석 실행", type="primary", use_container_width=True, key="btn_run_ai_stock")

                if run_ai_btn:
                    target_row = df_display[df_display["ticker"] == sel_chart_ticker].iloc[0]
                    stock_nm = target_row["종목명"]
                    with st.spinner(f"'{stock_nm}' 분석 실행 중..."):
                        analysis_result = analyze_stock_with_gemini(sel_chart_ticker, stock_nm, target_row, analysis_option)
                    st.success("분석 완료")
                    st.markdown(analysis_result)

    # TAB 3: 주문 지시서
    with tab3:
        st.markdown(f"##### 시스템 매매 지시서 [보유: {current_holdings_count} / {top_n_cfg}개]")

        if not is_authenticated:
            st.info("매매 신호 확인 및 주문 실행을 위해 우측 상단 [비밀번호 해제]를 진행해 주세요.")
        else:
            with st.expander(f"현재 보유 종목 ({current_holdings_count}/{top_n_cfg}개 슬롯)", expanded=True):
                if not holdings_db.empty:
                    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
                    if not df_stocks.empty:
                        df_stocks["ticker"] = df_stocks["ticker"].astype(str).str.strip()
                        holdings_merged = pd.merge(holdings_db, df_stocks, on="ticker", how="left")
                    else:
                        holdings_merged = holdings_db
                        holdings_merged["name"] = holdings_merged["ticker"]

                    holdings_list, total_risk_pct, risk_violations = calculate_holdings_risk(
                        holdings_merged, df_display, market_type, account_total_input, current_engine_key, sl_cfg, target_date_str
                    )

                    st.markdown("###### 포트폴리오 리스크")
                    risk_col1, risk_col2 = st.columns([2.5, 1.5])
                    with risk_col1:
                        st.progress(min(total_risk_pct / 100.0, 1.0))
                    with risk_col2:
                        st.markdown(f"**총 리스크: {total_risk_pct:.2f}%**")

                    if risk_violations:
                        st.warning(f"단일 종목 손실 한도(2.0%) 초과: {', '.join(risk_violations)}")

                    df_h = pd.DataFrame(holdings_list)
                    calc_base_total = account_total_input if account_total_input > 0 else df_h["평가금액"].sum()
                    df_h["비중(%)"] = (df_h["평가금액"] / calc_base_total) * 100
                    df_h = df_h[["종목명", "종목코드", "수량", "평단가", "최고가", "현재가", "평가금액", "손익금액", "수익률(%)", "비중(%)", "ATR", "스톱기준", "손절/스톱가", "보유일수", "상태"]]

                    price_fmt_str = "{:,.2f}" if market_type == "US" else "{:,.0f}"
                    profit_amt_fmt = "{:+,.2f}" if market_type == "US" else "{:+,.0f}"

                    st.dataframe(
                        df_h.style.format({
                            "수량": "{:,.2f}" if market_type == "US" else "{:,.0f}",
                            "평단가": price_fmt_str, "최고가": price_fmt_str, "현재가": price_fmt_str,
                            "평가금액": price_fmt_str, "손익금액": profit_amt_fmt, "수익률(%)": "{:+.2f}%",
                            "비중(%)": "{:.1f}%", "ATR": price_fmt_str, "손절/스톱가": price_fmt_str, "보유일수": "{:,.0f}일",
                        })
                        .map(lambda x: "color: #1976d2; font-weight: bold;" if "1번" in str(x) else ("color: #e65100; font-weight: bold;" if "2번" in str(x) else ""), subset=["스톱기준"])
                        .map(lambda x: "color: #d62728; font-weight: bold;" if "손절" in str(x) else ("color: #2ca02c; font-weight: bold;" if "익절" in str(x) else ""), subset=["상태"])
                        .map(lambda x: "color: #d62728;" if float(x) > 0 else ("color: #1f77b4;" if float(x) < 0 else ""), subset=["손익금액", "수익률(%)"]),
                        hide_index=True,
                        use_container_width=True,
                    )

            df_rebal = df_display[df_display["매매상태"].isin(["매도", "추천"])]
            display_trade_list(df_rebal[df_rebal["매매상태"] == "매도"], "시스템 매도 필요 종목", "매도", "sys_s", target_date_str, is_latest_date, market_type, holdings_db, top_n_cfg, account_total_input, current_engine_key)
            display_trade_list(df_rebal[df_rebal["매매상태"] == "추천"], "시스템 매수 추천 종목", "매수", "sys_b", target_date_str, is_latest_date, market_type, holdings_db, top_n_cfg, account_total_input, current_engine_key)

            st.write("")
            with st.expander("보유 종목 수동 매수/매도 입력 센터", expanded=False):
                c_m1, c_m2 = st.columns(2)
                with c_m1:
                    st.markdown("###### 수동 매수")
                    m_ticker = st.text_input("종목코드 (Ticker)", key="m_tk").strip().upper()
                    m_p = st.number_input("매수가", min_value=0.0, value=0.0, key="m_p")
                    m_q = st.number_input("수량", min_value=0.0, value=1.0, key="m_q")
                    m_d = st.date_input("매수일", value=selected_date, key="m_d")
                    if st.button("수동 매수 실행", type="primary", key="btn_m_buy", use_container_width=True):
                        if m_ticker and m_p > 0 and m_q > 0:
                            update_holdings(m_ticker, "BUY", m_p, m_d, m_q, market_type)
                            st.success(f"[{m_ticker}] 수동 매수 등록 완료")
                            st.rerun()

                with c_m2:
                    st.markdown("###### 수동 매도")
                    ms_ticker = st.text_input("매도 종목코드", key="ms_tk").strip().upper()
                    ms_p = st.number_input("매도가", min_value=0.0, value=0.0, key="ms_p")
                    ms_q = st.number_input("수량", min_value=0.0, value=1.0, key="ms_q")
                    ms_d = st.date_input("매도일", value=selected_date, key="ms_d")
                    ms_reason = st.selectbox("청산 사유", ["수기 매도 (사용자 임의 청산)", "목표가 도달 (수동 익절)", "리스크 관리 (수동 손절)", "직접 입력"], key="ms_rs")
                    if st.button("수동 매도 실행", key="btn_m_sell", use_container_width=True):
                        if ms_ticker and ms_p > 0 and ms_q > 0:
                            update_holdings(ms_ticker, "SELL", ms_p, ms_d, ms_q, market_type, exit_reason=ms_reason)
                            st.success(f"[{ms_ticker}] 수동 매도 완료")
                            st.rerun()

            st.write("")
            with st.expander(f"[{market_type}] 운용 자금 설정 및 리스크 관리", expanded=False):
                cap_c1, cap_c2 = st.columns([2.5, 1.5])
                with cap_c1:
                    new_cap = st.number_input(f"[{market_type}] 총 운용 자금 설정", value=account_total_input, step=100.0 if market_type == "US" else 1000000.0, key=f"cap_in_{market_type}")
                with cap_c2:
                    st.write("")
                    if st.button("자금 저장", key=f"btn_cap_save_{market_type}", type="primary", use_container_width=True):
                        st.session_state[cap_key] = new_cap
                        try:
                            res_ex = supabase.table("strategy_settings").select("*").eq("id", 1).execute()
                            ex_data = res_ex.data[0] if res_ex.data else {"id": 1}
                            ex_data[cap_key] = float(new_cap)
                            supabase.table("strategy_settings").upsert(ex_data).execute()
                            st.success("운용 자금 DB 저장 완료")
                            st.rerun()
                        except Exception as e:
                            st.error(f"저장 실패: {e}")

                max_risk_amt = new_cap * 0.02
                st.caption(f"**단일 종목 최대 허용 손실 (2% Rule)**: {max_risk_amt:,.0f}원" if market_type == "KR" else f"**단일 종목 최대 허용 손실 (2% Rule)**: ${max_risk_amt:,.2f}")

    # TAB 4: 성과
    with tab4:
        st.markdown(f"##### {market_type} 시장 성과 분석 리포트")
        if not is_authenticated:
            st.info("성과 내역 확인을 위해 우측 상단 [비밀번호 해제]를 완료해 주세요.")
        else:
            current_table_name = get_holdings_table(market_type)
            try:
                history_res = supabase.table(current_table_name).select("*").execute()
                df_all_h = pd.DataFrame(history_res.data) if history_res.data else pd.DataFrame()
                df_hist_raw = df_all_h[df_all_h["sell_date"].notna() & (df_all_h["sell_date"] != "")].copy() if not df_all_h.empty else pd.DataFrame()
            except Exception:
                df_hist_raw = pd.DataFrame()

            if df_hist_raw.empty:
                st.info("청산 완료된 매매 이력이 존재하지 않습니다.")
            else:
                df_hist_raw["sell_date_dt"] = pd.to_datetime(df_hist_raw["sell_date"])
                start_date_perf = st.date_input("조회 시작일", value=df_hist_raw["sell_date_dt"].min().date(), key="perf_start")
                end_date_perf = st.date_input("조회 종료일", value=df_hist_raw["sell_date_dt"].max().date(), key="perf_end")

                mask_period = (df_hist_raw["sell_date_dt"].dt.date >= start_date_perf) & (df_hist_raw["sell_date_dt"].dt.date <= end_date_perf)
                df_hist = df_hist_raw[mask_period].copy()

                if not df_hist.empty:
                    try:
                        df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
                        if not df_stocks.empty:
                            df_stocks["ticker"] = df_stocks["ticker"].astype(str).str.strip()
                            df_hist["ticker"] = df_hist["ticker"].astype(str).str.strip()
                            df_hist = pd.merge(df_hist, df_stocks, on="ticker", how="left")
                            df_hist["종목명"] = df_hist["name"].fillna(df_hist["ticker"])
                        else:
                            df_hist["종목명"] = df_hist["ticker"]
                    except Exception:
                        if "종목명" not in df_hist.columns:
                            df_hist["종목명"] = df_hist["ticker"]

                    if "holding_days" not in df_hist.columns:
                        df_hist["holding_days"] = (df_hist["sell_date_dt"] - pd.to_datetime(df_hist["buy_date"], errors="coerce")).dt.days.fillna(0)

                    df_hist["profit_amount"] = pd.to_numeric(df_hist["profit_amount"], errors="coerce").fillna(0.0)
                    total_profit = df_hist["profit_amount"].sum()
                    
                    tot_trades = len(df_hist)
                    win_df = df_hist[df_hist["profit_amount"] > 0]
                    win_rate = (len(win_df) / tot_trades * 100) if tot_trades > 0 else 0.0
                    
                    st.markdown("###### 핵심 성과 지표 (KPI)")
                    kpi_c1, kpi_c2, kpi_c3 = st.columns(3)
                    kpi_c1.metric("총 실현 손익", f"{total_profit:+,.0f}원" if market_type == "KR" else f"${total_profit:+,.2f}")
                    kpi_c2.metric("총 청산 거래", f"{tot_trades}건")
                    kpi_c3.metric("승률", f"{win_rate:.1f}%")

                    st.write("")
                    st.markdown("###### 수익 기여도 시각화 차트")
                    draw_attribution_charts(df_hist, market_type)

                    st.write("")
                    st.markdown("###### 청산 완료 거래 내역")
                    disp_perf_df = df_hist[["buy_date", "sell_date", "ticker", "종목명", "buy_price", "sell_price", "quantity", "profit_amount", "profit_rate", "exit_reason"]].copy()
                    disp_perf_df = disp_perf_df.rename(columns={
                        "buy_date": "매수일",
                        "sell_date": "매도일",
                        "ticker": "티커",
                        "buy_price": "매수가",
                        "sell_price": "매도가",
                        "quantity": "수량",
                        "profit_amount": "손익금액",
                        "profit_rate": "수익률(%)",
                        "exit_reason": "청산사유"
                    })

                    price_fmt = "{:,.2f}" if market_type == "US" else "{:,.0f}"
                    profit_fmt = "{:+,.2f}" if market_type == "US" else "{:+,.0f}"

                    st.dataframe(
                        disp_perf_df.style.format({
                            "매수가": price_fmt,
                            "매도가": price_fmt,
                            "수량": "{:,.2f}" if market_type == "US" else "{:,.0f}",
                            "손익금액": profit_fmt,
                            "수익률(%)": "{:+.2f}%",
                        }).map(lambda v: "color: #d62728;" if float(v) > 0 else ("color: #1f77b4;" if float(v) < 0 else ""), subset=["손익금액", "수익률(%)"]),
                        hide_index=True,
                        use_container_width=True
                    )

                    st.write("")
                    st.markdown("###### 매매 타점 복기 센터")
                    df_hist_disp = df_hist.sort_values("sell_date", ascending=False).reset_index(drop=True)
                    trade_opts = df_hist_disp.apply(lambda r: f"[{r['sell_date']}] [{r['ticker']}] {r['종목명']} (손익: {r['profit_amount']:+,.0f}원)", axis=1).tolist()
                    
                    sel_trade_opt = st.selectbox("복기할 매매 건 선택", options=trade_opts, key="sb_review_trade")
                    if sel_trade_opt:
                        sel_idx = trade_opts.index(sel_trade_opt)
                        rev_row = df_hist_disp.iloc[sel_idx]
                        rev_ticker = str(rev_row["ticker"]).strip().upper()
                        
                        rev_supp_dates = []
                        try:
                            res_rev_s = supabase.table("daily_top_liquidity").select("trade_date").eq("ticker", rev_ticker).or_("foreign_net.gt.0,inst_net.gt.0").execute()
                            if res_rev_s.data:
                                rev_supp_dates = [r["trade_date"] for r in res_rev_s.data]
                        except Exception:
                            pass

                        st.markdown(f"📈 **[{rev_row['종목명']}] 타점 및 수급 복기 차트**")
                        draw_integrated_chart(rev_ticker, market_type, {rev_ticker: rev_row["종목명"]}, buy_date=str(rev_row["buy_date"]), sell_date=str(rev_row["sell_date"]), supply_dates=rev_supp_dates)

    # TAB 5: 백테스트
    with tab5:
        st.markdown("##### 자동 백테스트 리포트")
        try:
            res_bt = supabase.table("backtest_trades").select("*").order("sell_date", desc=True).execute()
            bt_data = res_bt.data if res_bt.data else []
        except Exception:
            bt_data = []

        if not bt_data:
            st.info("저장된 백테스트 내역이 없습니다.")
        else:
            df_bt = pd.DataFrame(bt_data)
            st.dataframe(df_bt, hide_index=True, use_container_width=True)

    # 하단 스페이서 공간
    st.markdown("<div class='bottom-spacer'></div>", unsafe_allow_html=True)

else:
    st.warning("데이터를 불러오는 중입니다.")
