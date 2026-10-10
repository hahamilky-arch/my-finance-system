import time
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as gg
from plotly.subplots import make_subplots
import streamlit as st
import streamlit.components.v1 as components

# 내부 모듈 연동
from charts import draw_attribution_charts, draw_integrated_chart
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

st.set_page_config(layout="wide")

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

# 1. 모바일 초밀착 수평 핏(Fit) CSS 설정
st.markdown(
    """
    <style>
    [data-testid="stMainBlockContainer"], .main, .main .block-container {
        overflow: visible !important;
    }
    .block-container { 
        padding-top: 0.2rem !important; 
        padding-bottom: 0.5rem !important; 
        padding-left: 0.3rem !important;
        padding-right: 0.3rem !important;
    }
    html, body, [class*="st-"] { font-size: 12px !important; }
    h5 { font-size: 0.95rem !important; margin-bottom: 0.2rem !important; }
    
    /* Sticky 탭 반응형 최적화 */
    div[data-testid="stTabs"] > div:first-child,
    div[data-baseweb="tab-list"],
    .stTabs [role="tablist"] {
        position: sticky !important;
        top: 0px !important;
        background-color: #ffffff !important;
        z-index: 99999 !important;
        padding-top: 2px !important;
        padding-bottom: 2px !important;
        border-bottom: 2px solid #e0e0e0 !important;
        box-shadow: 0px 2px 6px rgba(0,0,0,0.05);
    }

    /* 📌 모바일 초밀착 강제 수평 핏 (Flex-Wrap 차단) */
    div[data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap !important;
        gap: 0.3rem !important;
    }
    div[data-testid="column"] {
        min-width: 0 !important;
        flex: 1 1 0% !important;
        padding: 0px !important;
    }
    
    /* 메트릭 박스 글자 및 여백 초밀착 축소 */
    [data-testid="stMetric"] {
        padding: 2px 4px !important;
        background-color: #f8f9fa !important;
        border-radius: 4px !important;
        border: 1px solid #e9ecef !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 0.85rem !important;
        line-height: 1.1 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.7rem !important;
        line-height: 1.0 !important;
        white-space: nowrap !important;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.65rem !important;
        line-height: 1.0 !important;
    }
    
    /* 상단 버튼 높이 및 글자 축소 */
    .stButton button {
        padding: 1px 4px !important;
        font-size: 0.72rem !important;
        height: 28px !important;
        min-height: 28px !important;
    }
    
    .backup-tag {
        background-color: #fff3cd; color: #856404; font-size: 0.75em; font-weight: bold;
        padding: 1px 4px; border-radius: 3px; border: 1px solid #ffeeba; margin-left: 2px;
        display: inline-block;
    }
    .primary-tag {
        background-color: #e3f2fd; color: #0d47a1; font-size: 0.75em; font-weight: bold;
        padding: 1px 4px; border-radius: 3px; border: 1px solid #bbdefb; margin-left: 2px;
        display: inline-block;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 2. 30분 인증 타이머 세션
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
    df_s = pd.DataFrame("", index=df.index, columns=df.columns)
    for col in ["변동", "상승금액", "상승률"]:
        if col in df.columns:
            df_s.loc[df[col] > 0, col] += "color: red;"
            df_s.loc[df[col] < 0, col] += "color: blue;"
    if "상태" in df.columns:
        df_s.loc[df["상태"] == "추천", "상태"] += (
            "color: #d62728; font-weight: bold;"
        )
        df_s.loc[df["상태"] == "매도", "상태"] += (
            "color: #1f77b4; font-weight: bold;"
        )
        df_s.loc[df["상태"] == "보유", "상태"] += (
            "color: #2ca02c; font-weight: bold;"
        )
    if "제외사유" in df.columns:
        df_s.loc[df["제외사유"] != "", "제외사유"] += (
            "color: #888888; font-size: 0.9em;"
        )
        df_s.loc[df["제외사유"] == "조건충족", "제외사유"] += (
            "color: #d62728; font-weight: bold;"
        )
    for col in ["RS(90)", "RS(10)"]:
        if col in df.columns:
            df_s.loc[df[col] > 0, col] += "color: #d62728; font-weight: bold;"
            df_s.loc[df[col] <= 0, col] += "color: #bbbbbb;"

    if "순위" in df.columns:
        for idx, rank in df["순위"].items():
            if pd.notna(rank):
                if rank <= 10:
                    df_s.loc[idx, :] += (
                        "background-color: rgba(255, 235, 156, 0.4);"
                    )
                elif rank <= 20:
                    df_s.loc[idx, :] += (
                        "background-color: rgba(198, 239, 206, 0.4);"
                    )
                elif rank <= 30:
                    df_s.loc[idx, :] += (
                        "background-color: rgba(189, 215, 238, 0.4);"
                    )

    if "수급" in df.columns:
        matched_mask = df["수급"] == "포착"
        df_s.loc[matched_mask, :] += (
            "background-color: rgba(200, 230, 201, 0.7); font-weight: bold;"
        )
        df_s.loc[matched_mask, "수급"] += "color: #2e7d32; font-weight: bold;"

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

            rank_val = (
                int(row.get("순위", 0)) if pd.notna(row.get("순위")) else "-"
            )
            rec_rank_val = row.get("추천순위", row.get("매수추천순위", ""))
            rec_rank_display = (
                f"{rec_rank_val}위" if rec_rank_val != "" else "-"
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
                tag_html = f"<span class='primary-tag'>추천 {p_idx}</span>"

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

                        atr_v = float(row.get("atr", 0.0))
                        if atr_v > 0 and input_price > 0:
                            atr_suggest_qty = max(
                                1.0,
                                float(
                                    int(
                                        (account_total * 0.02) / (2 * atr_v)
                                    )
                                ),
                            )
                            atr_qty_str = (
                                f"{atr_suggest_qty:,.2f}"
                                if market_type == "US"
                                else f"{atr_suggest_qty:,.0f}"
                            )
                            st.caption(
                                f"자금관리 추천 수량: {atr_qty_str}주"
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
            else:
                c2.markdown(
                    "<div style='color:#999999; font-size:0.8em; margin-top:4px; text-align:right;'>과거불가</div>",
                    unsafe_allow_html=True,
                )

        if not backup_data.empty:
            st.markdown("---")
            st.markdown("###### 예비 목록 (대기/교체용)")
            for backup_idx, (_, row) in enumerate(backup_data.iterrows(), 1):
                ticker = row["ticker"]
                c1, c2 = st.columns([4, 1])

                rank_val = (
                    int(row.get("순위", 0)) if pd.notna(row.get("순위")) else "-"
                )
                rec_rank_val = row.get("추천순위", row.get("매수추천순위", ""))
                rec_rank_display = (
                    f"{rec_rank_val}위" if rec_rank_val != "" else "-"
                )
                reason_desc = (
                    f"후순위 대체 종목 [추천순위: {rec_rank_display}]"
                )

                atr_val = float(row.get("atr", 0.0))
                atr_str = (
                    f"{atr_val:,.2f}"
                    if market_type == "US"
                    else f"{atr_val:,.0f}"
                )
                position_info = f"<br><span style='font-size: 0.85em; color: #856404; font-weight: bold;'>예비 분산 금액: {fmt_str} | ATR: {atr_str}</span>"

                backup_html = (
                    f"<div style='line-height: 1.5; margin-top: 2px; background-color: #fffde7; padding: 6px 8px; border-radius: 4px; border-left: 3px solid #fbc02d;'>"
                    f"<strong style='font-size: 1.0em; color: #111111;'>{row['종목명']}</strong> "
                    f"<span style='font-size: 0.8em; color: #888888;'>({ticker})</span> "
                    f"<span class='backup-tag'>예비{backup_idx}</span> "
                    f"<span style='font-size: 0.8em; color: #d7ccc8; font-weight: bold;'>[순위: {rank_val}위 | 추천: {rec_rank_display}]</span>"
                    f"<br><span style='font-size: 0.85em; color: #e65100; font-weight: bold;'>사유: {reason_desc}</span>"
                    f"{position_info}"
                    f"<br><span style='font-size: 0.8em; color: #444444;'>MOT: {row['MOT']:.2f} | RS(90): {row['RS(90)']:.2f} | 이격: {row['이격도']:+.2f}%</span>"
                    f"</div>"
                )
                c1.markdown(backup_html, unsafe_allow_html=True)

                if is_latest_date:
                    with c2.popover(f"예비매수"):
                        st.write(f"**[예비{backup_idx}] {row['종목명']}**")
                        p_key, q_key, acc_key = (
                            f"p_bk_{key_prefix}_{ticker}",
                            f"q_bk_{key_prefix}_{ticker}",
                            f"acc_bk_{key_prefix}_{ticker}",
                        )
                        input_price = st.number_input(
                            f"매수가", value=float(row["종가"]), key=p_key
                        )
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

                        if st.button(
                            "예비 매수 실행",
                            key=f"btn_bk_{key_prefix}_{ticker}",
                        ):
                            update_holdings(
                                ticker,
                                "BUY",
                                input_price,
                                target_date,
                                input_qty,
                                market_type,
                            )
                else:
                    c2.markdown(
                        "<div style='color:#999999; font-size:0.8em; margin-top:4px; text-align:right;'>과거불가</div>",
                        unsafe_allow_html=True,
                    )


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

with st.sidebar:
    st.markdown("### 알파 매매전략 설정")

    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    selected_date = st.date_input("Date", value=latest_date_default)
    target_date_str = (
        pd.to_datetime(selected_date).strftime("%Y-%m-%d")
        if selected_date
        else ""
    )

    st.divider()

    default_engine_idx = 1 if market_type == "US" else 0

    strategy_engine_mode = st.radio(
        "전략 엔진 선택",
        [
            "전략 3: Top 7 Regime",
            "단기 타점 모멘텀",
            "Ultimate 듀얼 모멘텀",
        ],
        index=default_engine_idx,
    )

    if "전략 3" in strategy_engine_mode:
        current_engine_key = "strat3_top7"
    elif "단기" in strategy_engine_mode:
        current_engine_key = "short_term"
    else:
        current_engine_key = "ultimate_dual"

    st.session_state["strategy_engine_mode"] = current_engine_key

    market_safe, stop_new_buy, reduce_holdings = get_market_regime(
        market_type, target_date_str
    )
    strategy_mode = st.radio(
        "운용 모드 선택",
        ["자동 감지 모드", "상승장 세팅 (Bull)", "하락장 세팅 (Bear)"],
        index=0,
    )
    is_bull = (
        True
        if strategy_mode == "상승장 세팅 (Bull)"
        else (
            False
            if strategy_mode == "하락장 세팅 (Bear)"
            else market_safe
        )
    )
    rebalance_cycle = st.selectbox(
        "리밸런싱 주기", ["상시 (빈자리 즉시 채우기)", "주기 (매주 수요일)"]
    )

    if current_engine_key == "strat3_top7":
        st.success(
            "전략 3 모드: Top 7 / Rank≤15 / ATR 2.5x손절 / +8%달성시 본절·익절스탑"
        )
        top_n_cfg = 7
        sl_cfg = -2.5
        rank_exit_limit = 15
    elif current_engine_key == "short_term":
        st.info(
            "단기 타점 모드(미국장 기본): 상위 200위 / 목표익절 +15% / 손절 -5%"
        )
        top_n_cfg = st.session_state.get("bull_top_n", 4)
        sl_cfg = st.session_state.get("bull_sl", -5.0)
        rank_exit_limit = 200
    else:
        if is_bull:
            st.success("상승장 모드 (Bull Market)")
            top_n_cfg = st.session_state.get("bull_top_n", 5)
            sl_cfg = st.session_state.get("bull_sl", -10.0)
            rank_exit_limit = 60
        else:
            st.error("하락장 모드 (Bear Market)")
            top_n_cfg = st.session_state.get("bear_top_n", 3)
            sl_cfg = st.session_state.get("bear_sl", -6.0)
            rank_exit_limit = 30

    if stop_new_buy:
        st.warning("MA20 3일 연속 하회 감지: 신규 매수 중지")
    elif reduce_holdings:
        st.warning("MA20 하회 감지: 보유 종목 비중 축소")

    st.divider()

    try:
        df_kr_chk = get_data(
            selected_date,
            all_dates,
            "KR",
            top_n_cfg,
            sl_cfg,
            rebalance_cycle,
            is_bull,
            stop_new_buy,
            reduce_holdings,
            strategy_engine_mode=current_engine_key,
        )
        kr_buy_count = (
            len(df_kr_chk[df_kr_chk["매매상태"] == "매수추천"])
            if df_kr_chk is not None
            else 0
        )
    except Exception:
        kr_buy_count = 0

    try:
        df_us_chk = get_data(
            selected_date,
            all_dates,
            "US",
            top_n_cfg,
            sl_cfg,
            rebalance_cycle,
            is_bull,
            stop_new_buy,
            reduce_holdings,
            strategy_engine_mode=current_engine_key,
        )
        us_buy_count = (
            len(df_us_chk[df_us_chk["매매상태"] == "매수추천"])
            if df_us_chk is not None
            else 0
        )
    except Exception:
        us_buy_count = 0

    col_side_kr, col_side_us = st.columns(2)
    col_side_kr.metric("KR추천", f"{kr_buy_count}개")
    col_side_us.metric("US추천", f"{us_buy_count}개")

# 📌 헤더 & 인증 영역 초밀착 수평 처리
col_title, col_auth_status = st.columns([1.8, 2.2])
with col_title:
    st.markdown("<h5 style='margin:0; padding:0;'>Quant Alpha</h5>", unsafe_allow_html=True)

with col_auth_status:
    if is_authenticated:
        elapsed = time.time() - st.session_state.get("last_auth_time", 0)
        remaining_sec = max(0, int(LOGIN_TIMEOUT_SECONDS - elapsed))
        rem_min, rem_sec = remaining_sec // 60, remaining_sec % 60

        c_time, c_ext, c_lock = st.columns([1.4, 1, 1])
        c_time.markdown(
            f"<div style='font-size:0.78em; color:#2e7d32; font-weight:bold; padding-top:4px;'>인증({rem_min}:{rem_sec:02d})</div>",
            unsafe_allow_html=True,
        )
        with c_ext:
            if st.button("연장", key="btn_extend_auth", use_container_width=True):
                st.session_state["last_auth_time"] = time.time()
                st.rerun()
        with c_lock:
            if st.button("잠금", key="btn_global_lock", use_container_width=True):
                st.session_state["trade_authenticated"] = False
                st.session_state["last_auth_time"] = 0
                st.rerun()
    else:
        c_p1, c_p2 = st.columns([2, 1])
        with c_p1:
            input_pwd_global = st.text_input(
                "PW",
                type="password",
                key="global_pwd_input",
                label_visibility="collapsed",
                placeholder="비밀번호",
            )
        with c_p2:
            if st.button(
                "해제",
                key="btn_global_unlock",
                type="primary",
                use_container_width=True,
            ):
                if input_pwd_global == st.secrets.get("TRADE_PASSWORD", "1234"):
                    st.session_state["trade_authenticated"] = True
                    st.session_state["last_auth_time"] = time.time()
                    st.rerun()
                else:
                    st.error("불일치")

cap_key = "us_capital" if market_type == "US" else "kr_capital"
default_cap = st.session_state.get(
    cap_key, 6000.0 if market_type == "US" else 20000000.0
)
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

    is_latest_date = (
        (target_date_str == max(all_dates)) if all_dates and target_date_str else False
    )

    current_table_name = get_holdings_table(market_type)
    try:
        holdings_res = (
            supabase.table(current_table_name)
            .select("*")
            .is_("sell_date", "null")
            .execute()
        )
        holdings_db = (
            pd.DataFrame(holdings_res.data)
            if holdings_res.data
            else pd.DataFrame()
        )
    except Exception:
        holdings_db = pd.DataFrame()

    current_holdings_count = len(holdings_db) if not holdings_db.empty else 0
    needed_slots = max(0, top_n_cfg - current_holdings_count)

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "시장 & 수급 종합",
        "알파 시그널",
        "시스템 매매 지시서",
        "성과 분석",
        "백테스트 리포트",
    ])

    # TAB 1: 시장 & 수급 종합
    with tab1:
        st.markdown("###### 시장 방향성 & 수급 종합")

        p_zscore = 0.0
        z_tag = "초기상태"
        k_f_5d = 0
        k_inst_5d = 0
        k_f_days = 0
        k_inst_days = 0
        divergence_msg = ""

        # 📌 모바일 초밀착 수평 지표 배치 (Flex-wrap 차단 적용)
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])

        c1.metric(
            "전략 엔진",
            "Top 7" if current_engine_key == "strat3_top7" else ("단기타점" if current_engine_key == "short_term" else "듀얼"),
        )

        regime_status_str = "상승(Bull)" if is_bull else "하락(Bear)"
        c2.metric(
            "Regime",
            regime_status_str,
            delta="중지" if stop_new_buy else ("축소" if reduce_holdings else "허용"),
            delta_color="off",
        )

        buy_cnt = len(df_display[df_display["매매상태"] == "추천"])
        buy_cnt_display = min(buy_cnt, needed_slots)
        c3.metric(
            "추천 종목",
            f"{buy_cnt_display}개",
            delta=f"잔여 {needed_slots}/{top_n_cfg}",
        )

        sell_cnt = len(df_display[df_display["매매상태"] == "매도"])
        c4.metric("매도 종목", f"{sell_cnt}개")

        st.divider()

        if market_type == "US":
            st.info(
                "미국 시장 안내: 현재 한국장(KR) 수급 데이터를 수집 중입니다. 미국장(US)은 지수 추세 및 종목별 모멘텀 지표(Rank, RS)를 기준으로 전략이 동작합니다."
            )
        else:
            if not is_authenticated:
                st.info(
                    "상세 수급 지표는 우측 상단 [비밀번호 해제] 후 확인하실 수 있습니다."
                )
            else:
                try:
                    res_inv_all = (
                        supabase.table("market_investor_trends")
                        .select("*")
                        .lte("trade_date", target_date_str)
                        .order("trade_date", desc=True)
                        .limit(60)
                        .execute()
                    )
                    df_inv_all = (
                        pd.DataFrame(res_inv_all.data)
                        if res_inv_all.data
                        else pd.DataFrame()
                    )
                except Exception:
                    df_inv_all = pd.DataFrame()

                try:
                    res_prog_all = (
                        supabase.table("market_program_trends")
                        .select("*")
                        .lte("trade_date", target_date_str)
                        .order("trade_date", desc=True)
                        .limit(60)
                        .execute()
                    )
                    df_prog_all = (
                        pd.DataFrame(res_prog_all.data)
                        if res_prog_all.data
                        else pd.DataFrame()
                    )
                except Exception:
                    df_prog_all = pd.DataFrame()

                df_inv = (
                    df_inv_all[
                        df_inv_all["trade_date"] == target_date_str
                    ]
                    if not df_inv_all.empty
                    else pd.DataFrame()
                )
                df_prog = (
                    df_prog_all[
                        df_prog_all["trade_date"] == target_date_str
                    ]
                    if not df_prog_all.empty
                    else pd.DataFrame()
                )

                k_row = (
                    df_inv[df_inv["market_type"] == "KOSPI"].iloc[0]
                    if not df_inv.empty
                    and not df_inv[df_inv["market_type"] == "KOSPI"].empty
                    else {}
                )
                kq_row = (
                    df_inv[df_inv["market_type"] == "KOSDAQ"].iloc[0]
                    if not df_inv.empty
                    and not df_inv[df_inv["market_type"] == "KOSDAQ"].empty
                    else {}
                )
                p_row = df_prog.iloc[0] if not df_prog.empty else {}

                p_non_val = (
                    float(p_row.get("non_arbitrage_net", 0))
                    if not df_prog.empty and not p_row.empty
                    else 0.0
                )

                df_k_all = (
                    df_inv_all[df_inv_all["market_type"] == "KOSPI"].sort_values(
                        "trade_date", ascending=False
                    )
                    if not df_inv_all.empty
                    else pd.DataFrame()
                )
                df_kq_all = (
                    df_inv_all[df_inv_all["market_type"] == "KOSDAQ"].sort_values(
                        "trade_date", ascending=False
                    )
                    if not df_inv_all.empty
                    else pd.DataFrame()
                )
                df_p_sorted = (
                    df_prog_all.sort_values("trade_date", ascending=False)
                    if not df_prog_all.empty
                    else pd.DataFrame()
                )

                k_f_days = (
                    int((df_k_all.head(5)["foreign_net"] > 0).sum())
                    if not df_k_all.empty
                    else 0
                )
                k_inst_days = (
                    int((df_k_all.head(5)["institution_net"] > 0).sum())
                    if not df_k_all.empty
                    else 0
                )

                k_f_10d_cnt = (
                    int((df_k_all.head(10)["foreign_net"] > 0).sum())
                    if not df_k_all.empty
                    else 0
                )
                k_i_10d_cnt = (
                    int((df_k_all.head(10)["institution_net"] > 0).sum())
                    if not df_k_all.empty
                    else 0
                )
                kq_f_10d_cnt = (
                    int((df_kq_all.head(10)["foreign_net"] > 0).sum())
                    if not df_kq_all.empty
                    else 0
                )
                kq_i_10d_cnt = (
                    int((df_kq_all.head(10)["institution_net"] > 0).sum())
                    if not df_kq_all.empty
                    else 0
                )
                p_non_10d_cnt = (
                    int((df_p_sorted.head(10)["non_arbitrage_net"] > 0).sum())
                    if not df_p_sorted.empty
                    else 0
                )

                p_non_5d = (
                    int(df_p_sorted.head(5)["non_arbitrage_net"].sum())
                    if not df_p_sorted.empty
                    else 0
                )
                k_f_5d = (
                    int(df_k_all.head(5)["foreign_net"].sum())
                    if not df_k_all.empty
                    else 0
                )
                k_inst_5d = (
                    int(df_k_all.head(5)["institution_net"].sum())
                    if not df_k_all.empty
                    else 0
                )
                kq_f_5d = (
                    int(df_kq_all.head(5)["foreign_net"].sum())
                    if not df_kq_all.empty
                    else 0
                )
                kq_inst_5d = (
                    int(df_kq_all.head(5)["institution_net"].sum())
                    if not df_kq_all.empty
                    else 0
                )

                if not df_p_sorted.empty and len(df_p_sorted) >= 5:
                    p_non_20_series = df_p_sorted.head(20)[
                        "non_arbitrage_net"
                    ].astype(float)
                    mean_20 = p_non_20_series.mean()
                    std_20 = p_non_20_series.std()
                    p_zscore = (
                        ((p_non_val - mean_20) / std_20) if std_20 > 0 else 0.0
                    )
                else:
                    p_zscore = 0.0

                if p_zscore >= 1.5:
                    z_tag = "강한 유입"
                elif p_zscore <= -1.5:
                    z_tag = "강한 이탈"
                else:
                    z_tag = "정상 범위"

                if market_safe and p_non_5d < 0 and k_f_5d < 0:
                    divergence_msg = "[약세 다이버전스] 지수 MA20 상회 중이나, 최근 5일 비차익/외인 수급 지속 이탈"
                elif not market_safe and p_non_5d > 0 and k_f_5d > 0:
                    divergence_msg = "[강세 다이버전스] 지수 MA20 하회 중이나, 최근 5일 스마트머니 지속 매수 중"

                if divergence_msg:
                    st.warning(divergence_msg)

                st.markdown("###### 수급 강도 & 연속성 지표 (백만원)")
                
                r1_1, r1_2, r1_3 = st.columns(3)
                r1_1.metric("비차익 Z", f"{p_zscore:+.2f}", delta=z_tag, delta_color="off")
                r1_2.metric("비차익 5일", f"{p_non_5d:+,d}", delta=f"10일중 {p_non_10d_cnt}일")
                r1_3.metric("KOSPI 외인", f"{k_f_5d:+,d}", delta=f"10일중 {k_f_10d_cnt}일")

                st.write("")
                r2_1, r2_2, r2_3 = st.columns(3)
                r2_1.metric("KOSPI 기관", f"{k_inst_5d:+,d}", delta=f"10일중 {k_i_10d_cnt}일")
                r2_2.metric("KOSDAQ 외인", f"{kq_f_5d:+,d}", delta=f"10일중 {kq_f_10d_cnt}일")
                r2_3.metric("KOSDAQ 기관", f"{kq_inst_5d:+,d}", delta=f"10일중 {kq_i_10d_cnt}일")

                st.divider()

                st.markdown(f"###### 주체별 매매 동향 ({target_date_str} 기준 / 백만원)")
                disp_inv_summary = pd.DataFrame([
                    {
                        "시장": "KOSPI",
                        "외국인": int(k_row.get("foreign_net", 0)),
                        "개인": int(k_row.get("individual_net", 0)),
                        "기관계": int(k_row.get("institution_net", 0)),
                    },
                    {
                        "시장": "KOSDAQ",
                        "외국인": int(kq_row.get("foreign_net", 0)),
                        "개인": int(kq_row.get("individual_net", 0)),
                        "기관계": int(kq_row.get("institution_net", 0)),
                    },
                ])
                st.dataframe(
                    disp_inv_summary.style.format({
                        "외국인": "{:+,d}",
                        "개인": "{:+,d}",
                        "기관계": "{:+,d}",
                    }).map(
                        lambda v: "color: red;"
                        if v > 0
                        else ("color: blue;" if v < 0 else ""),
                        subset=["외국인", "개인", "기관계"],
                    ),
                    hide_index=True,
                    use_container_width=True,
                )

                st.divider()

                st.markdown("###### 당일 TOP 5 & 최근 10일 수급 빈도 상위")
                
                try:
                    res_liq_10d = (
                        supabase.table("daily_top_liquidity")
                        .select("*")
                        .lte("trade_date", target_date_str)
                        .order("trade_date", desc=True)
                        .limit(200)
                        .execute()
                    )
                    df_liq_10d = pd.DataFrame(res_liq_10d.data) if res_liq_10d.data else pd.DataFrame()
                except Exception:
                    df_liq_10d = pd.DataFrame()

                df_stock_liq = df_liq_10d[df_liq_10d["trade_date"] == target_date_str] if not df_liq_10d.empty else pd.DataFrame()

                tab_f_day, tab_i_day, tab_f_10d, tab_i_10d = st.tabs(
                    ["외인 당일", "기관 당일", "외인 10일", "기관 10일"]
                )

                with tab_f_day:
                    if not df_stock_liq.empty:
                        df_f_top = df_stock_liq.sort_values("foreign_net", ascending=False).head(5)[["rank", "name", "close_price", "change_rate", "foreign_net", "inst_net"]]
                        df_f_top = df_f_top.rename(columns={"rank": "순위", "name": "종목명", "close_price": "종가", "change_rate": "등락률", "foreign_net": "외국인순매수", "inst_net": "기관순매수"})
                        st.dataframe(
                            df_f_top.style.format({"종가": "{:,.0f}원", "등락률": "{:+.2f}%", "외국인순매수": "{:+,.0f}", "기관순매수": "{:+,.0f}"})
                            .map(lambda v: "color: red;" if float(v) > 0 else ("color: blue;" if float(v) < 0 else ""), subset=["등락률", "외국인순매수", "기관순매수"]),
                            hide_index=True, use_container_width=True
                        )
                    else:
                        st.caption("당일 데이터가 없습니다.")

                with tab_i_day:
                    if not df_stock_liq.empty:
                        df_i_top = df_stock_liq.sort_values("inst_net", ascending=False).head(5)[["rank", "name", "close_price", "change_rate", "foreign_net", "inst_net"]]
                        df_i_top = df_i_top.rename(columns={"rank": "순위", "name": "종목명", "close_price": "종가", "change_rate": "등락률", "foreign_net": "외국인순매수", "inst_net": "기관순매수"})
                        st.dataframe(
                            df_i_top.style.format({"종가": "{:,.0f}원", "등락률": "{:+.2f}%", "외국인순매수": "{:+,.0f}", "기관순매수": "{:+,.0f}"})
                            .map(lambda v: "color: red;" if float(v) > 0 else ("color: blue;" if float(v) < 0 else ""), subset=["등락률", "외국인순매수", "기관순매수"]),
                            hide_index=True, use_container_width=True
                        )
                    else:
                        st.caption("당일 데이터가 없습니다.")

                with tab_f_10d:
                    if not df_liq_10d.empty:
                        df_f_pos = df_liq_10d[df_liq_10d["foreign_net"] > 0]
                        freq_f = df_f_pos.groupby(["ticker", "name"]).agg(
                            빈도수=("trade_date", "nunique"),
                            누적순매수=("foreign_net", "sum"),
                            평균등락률=("change_rate", "mean")
                        ).reset_index().sort_values(["빈도수", "누적순매수"], ascending=[False, False]).head(10)
                        
                        freq_f = freq_f.rename(columns={"ticker": "티커", "name": "종목명", "평균등락률": "평균등락률"})
                        st.dataframe(
                            freq_f.style.format({"빈도수": "{:.0f}일", "누적순매수": "{:+,.0f}", "평균등락률": "{:+.2f}%"})
                            .map(lambda v: "color: red;" if float(v) > 0 else ("color: blue;" if float(v) < 0 else ""), subset=["누적순매수", "평균등락률"]),
                            hide_index=True, use_container_width=True
                        )
                    else:
                        st.caption("최근 10일 수급 데이터가 없습니다.")

                with tab_i_10d:
                    if not df_liq_10d.empty:
                        df_i_pos = df_liq_10d[df_liq_10d["inst_net"] > 0]
                        freq_i = df_i_pos.groupby(["ticker", "name"]).agg(
                            빈도수=("trade_date", "nunique"),
                            누적순매수=("inst_net", "sum"),
                            평균등락률=("change_rate", "mean")
                        ).reset_index().sort_values(["빈도수", "누적순매수"], ascending=[False, False]).head(10)
                        
                        freq_i = freq_i.rename(columns={"ticker": "티커", "name": "종목명", "평균등락률": "평균등락률"})
                        st.dataframe(
                            freq_i.style.format({"빈도수": "{:.0f}일", "누적순매수": "{:+,.0f}", "평균등락률": "{:+.2f}%"})
                            .map(lambda v: "color: red;" if float(v) > 0 else ("color: blue;" if float(v) < 0 else ""), subset=["누적순매수", "평균등락률"]),
                            hide_index=True, use_container_width=True
                        )
                    else:
                        st.caption("최근 10일 수급 데이터가 없습니다.")

        st.divider()
        index_name_str = "코스피 (^KS11)" if market_type == "KR" else "S&P 500 (^GSPC)"
        st.markdown(f"###### {index_name_str} 지수 추이 (최근 120영업일)")

        target_index_symbol = "^KS11" if market_type == "KR" else "^GSPC"
        try:
            res_idx_chart = (
                supabase.table("daily_analysis")
                .select("price_date, close_price, ma20, ma50, ma200")
                .eq("ticker", target_index_symbol)
                .order("price_date", desc=True)
                .limit(120)
                .execute()
            )
            if res_idx_chart.data:
                df_idx_c = pd.DataFrame(res_idx_chart.data)
                
                if not df_idx_c.empty:
                    df_idx_c["price_date_dt"] = pd.to_datetime(df_idx_c["price_date"])
                    df_idx_c = df_idx_c.sort_values("price_date_dt").reset_index(drop=True)
                    df_idx_c["date_str"] = df_idx_c["price_date_dt"].dt.strftime("%Y-%m-%d")
                    
                    df_idx_c["close_val"] = pd.to_numeric(df_idx_c["close_price"], errors="coerce")
                    df_idx_c["ma20_val"] = pd.to_numeric(df_idx_c.get("ma20"), errors="coerce")
                    df_idx_c["ma50_val"] = pd.to_numeric(df_idx_c.get("ma50"), errors="coerce")
                    df_idx_c["ma200_val"] = pd.to_numeric(df_idx_c.get("ma200"), errors="coerce")

                    fig_market_idx = gg.Figure()
                    
                    fig_market_idx.add_trace(gg.Scatter(
                        x=df_idx_c["date_str"],
                        y=df_idx_c["close_val"],
                        mode="lines",
                        name=f"{index_name_str} 종가",
                        line=dict(color="#9467bd", width=2.5)
                    ))
                    
                    if df_idx_c["ma20_val"].notna().any():
                        fig_market_idx.add_trace(gg.Scatter(
                            x=df_idx_c["date_str"],
                            y=df_idx_c["ma20_val"],
                            mode="lines",
                            name="MA20 (20일선)",
                            line=dict(color="#ff7f0e", width=1.5, dash="dash")
                        ))

                    if df_idx_c["ma50_val"].notna().any():
                        fig_market_idx.add_trace(gg.Scatter(
                            x=df_idx_c["date_str"],
                            y=df_idx_c["ma50_val"],
                            mode="lines",
                            name="MA50 (50일선)",
                            line=dict(color="#2ca02c", width=1.5, dash="dot")
                        ))

                    if df_idx_c["ma200_val"].notna().any():
                        fig_market_idx.add_trace(gg.Scatter(
                            x=df_idx_c["date_str"],
                            y=df_idx_c["ma200_val"],
                            mode="lines",
                            name="MA200 (200일선)",
                            line=dict(color="#d62728", width=1.5, dash="dashdot")
                        ))

                    fig_market_idx.update_layout(
                        height=280,
                        margin=dict(l=10, r=10, t=20, b=20),
                        xaxis=dict(type="category", tickangle=-45),
                        yaxis=dict(autorange=True, fixedrange=False),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    st.plotly_chart(fig_market_idx, use_container_width=True)
                else:
                    st.info(f"[{target_index_symbol}] 지수 시계열 데이터가 존재하지 않습니다.")
            else:
                st.info("지수 데이터를 불러올 수 없습니다.")
        except Exception as e:
            st.error(f"지수 차트 불러오기 실패: {e}")

    # TAB 2: 알파 시그널
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

                if st.session_state.get("tab2_integrated_chart_selector") != clicked_ticker:
                    st.session_state["tab2_integrated_chart_selector"] = clicked_ticker
                    st.rerun()

        st.divider()

        col_center_title, col_top_btn = st.columns([3.5, 1])
        with col_center_title:
            st.markdown("###### 선택 종목 통합 분석 센터")
        with col_top_btn:
            st.markdown("<a href='#top-section' style='float:right; text-decoration:none; background-color:#333; color:white; padding:2px 8px; border-radius:10px; font-size:0.75em;'>맨 위로</a>", unsafe_allow_html=True)

        top200_tickers = [
            str(t).strip().upper()
            for t in df_display.head(200)["ticker"].tolist()
        ]

        ticker_name_map = dict(
            zip(
                df_display["ticker"].astype(str).str.strip().str.upper(),
                df_display["종목명"],
            )
        )

        current_selected = st.session_state.get("tab2_integrated_chart_selector")
        if current_selected and current_selected not in top200_tickers:
            top200_tickers.insert(0, current_selected)

        default_idx = (
            top200_tickers.index(current_selected)
            if current_selected in top200_tickers
            else 0
        )

        with st.expander("통합 분석 센터 열기 / 접기", expanded=True):
            sel_chart_ticker = st.selectbox(
                "분석 대상 종목 선택",
                options=top200_tickers,
                index=default_idx,
                format_func=lambda x: f"[{x}] {ticker_name_map.get(x, x)}",
                key="tab2_integrated_chart_selector",
            )

            if sel_chart_ticker:
                supply_dates = []
                try:
                    res_supp = (
                        supabase.table("daily_top_liquidity")
                        .select("trade_date")
                        .eq("ticker", sel_chart_ticker)
                        .or_("foreign_net.gt.0,inst_net.gt.0")
                        .execute()
                    )
                    if res_supp.data:
                        supply_dates = [r["trade_date"] for r in res_supp.data]
                except Exception:
                    pass

                st.markdown("###### 개별 종목 기술적 차트")
                draw_integrated_chart(
                    sel_chart_ticker,
                    market_type,
                    ticker_name_map,
                    supply_dates=supply_dates
                )

                st.write("")
                st.divider()

                st.markdown("###### 외국인/기관 수급 동향")

                if market_type == "US":
                    st.info(
                        "미국 주식은 외국인/기관 수급 데이터를 별도 수집하지 않습니다."
                    )
                else:
                    try:
                        res_supply = (
                            supabase.table("daily_top_liquidity")
                            .select("*")
                            .eq("ticker", sel_chart_ticker)
                            .order("trade_date", desc=True)
                            .limit(15)
                            .execute()
                        )
                        df_supply = (
                            pd.DataFrame(res_supply.data)
                            if res_supply.data
                            else pd.DataFrame()
                        )
                    except Exception:
                        df_supply = pd.DataFrame()

                    if not df_supply.empty:
                        df_supply = df_supply.sort_values("trade_date").copy()
                        df_supply["foreign_cum"] = (
                            df_supply["foreign_net"].cumsum()
                        )
                        df_supply["inst_cum"] = df_supply["inst_net"].cumsum()
                        df_supply["date_fmt"] = pd.to_datetime(df_supply["trade_date"]).dt.strftime("%Y%m%d")

                        col_s_chart, col_s_table = st.columns([1.2, 1])

                        with col_s_chart:
                            fig_supply = gg.Figure()
                            fig_supply.add_trace(
                                gg.Scatter(
                                    x=df_supply["date_fmt"],
                                    y=df_supply["foreign_cum"],
                                    mode="lines+markers",
                                    name="외국인 누적",
                                    line=dict(color="#d62728", width=2),
                                )
                            )
                            fig_supply.add_trace(
                                gg.Scatter(
                                    x=df_supply["date_fmt"],
                                    y=df_supply["inst_cum"],
                                    mode="lines+markers",
                                    name="기관 누적",
                                    line=dict(color="#2ca02c", width=2),
                                )
                            )
                            fig_supply.update_layout(
                                title=f"[{sel_chart_ticker}] 외국인 vs 기관 누적 수급 (백만원)",
                                height=260,
                                margin=dict(l=10, r=10, t=30, b=10),
                                xaxis=dict(type="category"),
                                legend=dict(
                                    orientation="h",
                                    yanchor="bottom",
                                    y=1.02,
                                    xanchor="right",
                                    x=1,
                                ),
                            )
                            st.plotly_chart(
                                fig_supply, use_container_width=True
                            )

                        with col_s_table:
                            disp_supply_table = (
                                df_supply[
                                    [
                                        "trade_date",
                                        "close_price",
                                        "foreign_net",
                                        "inst_net",
                                    ]
                                ]
                                .sort_values("trade_date", ascending=False)
                                .rename(columns={
                                    "trade_date": "일자",
                                    "close_price": "종가",
                                    "foreign_net": "외국인",
                                    "inst_net": "기관",
                                })
                            )

                            st.dataframe(
                                disp_supply_table.style.format({
                                    "종가": "{:,.0f}원",
                                    "외국인": "{:+,.0f}",
                                    "기관": "{:+,.0f}",
                                }).map(
                                    lambda v: "color: red;"
                                    if float(v) > 0
                                    else ("color: blue;" if float(v) < 0 else ""),
                                    subset=["외국인", "기관"],
                                ),
                                hide_index=True,
                                use_container_width=True,
                            )
                    else:
                        st.info(
                            f"[{sel_chart_ticker}] 종목의 최근 수급 내역이 없습니다."
                        )

                st.write("")
                st.divider()

                st.markdown("###### Gemini AI 개별 종목 분석")
                used_cnt, remain_cnt = get_remaining_quota()
                st.caption(
                    f"Gemini 잔여 사용량: **{remain_cnt}/{MAX_DAILY_QUOTA}회**"
                )

                col_opt, col_btn = st.columns([2.5, 1.5])
                with col_opt:
                    analysis_option = st.selectbox(
                        "분석 항목 선택",
                        [
                            "종합 기본적 분석",
                            "ROE 듀퐁 분석",
                            "사업 구조",
                            "퀀트 밸류에이션",
                            "단/중기 시나리오",
                        ],
                        key="tab2_gemini_analysis_option_selector",
                    )
                with col_btn:
                    st.write("")
                    run_ai_btn = st.button(
                        "AI 분석 실행",
                        type="primary",
                        use_container_width=True,
                        key="btn_run_gemini_stock_analysis",
                    )

                if run_ai_btn:
                    target_row = df_display[
                        df_display["ticker"] == sel_chart_ticker
                    ].iloc[0]
                    stock_nm = target_row["종목명"]

                    with st.spinner(f"'{stock_nm}' 분석을 진행 중입니다..."):
                        analysis_result = analyze_stock_with_gemini(
                            sel_chart_ticker,
                            stock_nm,
                            target_row,
                            analysis_option,
                        )
                    st.success("분석 완료")
                    st.markdown(analysis_result)

    # TAB 3: 시스템 매매 지시서
    with tab3:
        st.markdown(
            f"##### 시스템 매매 지시서 [보유: {current_holdings_count} / {top_n_cfg}개]"
        )

        if not is_authenticated:
            st.info(
                "매매 신호 확인 및 주문 실행을 위해 우측 상단 [비밀번호 해제] 버튼을 클릭해 주십시오."
            )
        else:
            with st.expander(
                f"현재 보유 종목 ({current_holdings_count}/{top_n_cfg}개 슬롯)",
                expanded=True,
            ):
                if not holdings_db.empty:
                    df_stocks = pd.DataFrame(
                        supabase.table("stocks")
                        .select("ticker, name")
                        .execute()
                        .data
                    )
                    if not df_stocks.empty:
                        df_stocks["ticker"] = (
                            df_stocks["ticker"].astype(str).str.strip()
                        )
                        holdings_merged = pd.merge(
                            holdings_db, df_stocks, on="ticker", how="left"
                        )
                    else:
                        holdings_merged = holdings_db
                        holdings_merged["name"] = holdings_merged["ticker"]

                    holdings_list, total_risk_pct, risk_violations = (
                        calculate_holdings_risk(
                            holdings_merged,
                            df_display,
                            market_type,
                            account_total_input,
                            current_engine_key,
                            sl_cfg,
                            target_date_str,
                        )
                    )

                    st.markdown("###### 포트폴리오 리스크")
                    risk_col1, risk_col2 = st.columns([2.5, 1.5])
                    with risk_col1:
                        st.progress(min(total_risk_pct / 100.0, 1.0))
                    with risk_col2:
                        st.markdown(f"**총 리스크: {total_risk_pct:.2f}%**")

                    if risk_violations:
                        st.warning(
                            f"단일 종목 손실 한도(2.0%) 초과: {', '.join(risk_violations)}"
                        )

                    df_h = pd.DataFrame(holdings_list)
                    calc_base_total = (
                        account_total_input
                        if account_total_input > 0
                        else df_h["평가금액"].sum()
                    )
                    df_h["비중(%)"] = (df_h["평가금액"] / calc_base_total) * 100
                    df_h = df_h[[
                        "종목명",
                        "종목코드",
                        "수량",
                        "평단가",
                        "최고가",
                        "현재가",
                        "평가금액",
                        "손익금액",
                        "수익률(%)",
                        "비중(%)",
                        "ATR",
                        "스톱기준",
                        "손절/스톱가",
                        "보유일수",
                        "상태",
                    ]]

                    price_fmt_str = (
                        "{:,.2f}" if market_type == "US" else "{:,.0f}"
                    )
                    profit_amt_fmt = (
                        "{:+,.2f}" if market_type == "US" else "{:+,.0f}"
                    )

                    st.dataframe(
                        df_h.style.format({
                            "수량": "{:,.2f}"
                            if market_type == "US"
                            else "{:,.0f}",
                            "평단가": price_fmt_str,
                            "최고가": price_fmt_str,
                            "현재가": price_fmt_str,
                            "평가금액": price_fmt_str,
                            "손익금액": profit_amt_fmt,
                            "수익률(%)": "{:+.2f}%",
                            "비중(%)": "{:.1f}%",
                            "ATR": price_fmt_str,
                            "손절/스톱가": price_fmt_str,
                            "보유일수": "{:,.0f}일",
                        })
                        .map(
                            lambda x: "color: #1976d2; font-weight: bold;"
                            if "1번" in str(x)
                            else (
                                "color: #e65100; font-weight: bold;"
                                if "2번" in str(x)
                                else ""
                            ),
                            subset=["스톱기준"],
                        )
                        .map(
                            lambda x: "color: red; font-weight: bold;"
                            if "손절" in str(x)
                            else (
                                "color: green; font-weight: bold;"
                                if "익절" in str(x)
                                else ""
                            ),
                            subset=["상태"],
                        )
                        .map(
                            lambda x: "color: red;"
                            if float(x) > 0
                            else ("color: blue;" if float(x) < 0 else ""),
                            subset=["손익금액", "수익률(%)"],
                        ),
                        hide_index=True,
                        use_container_width=True,
                    )

            df_rebal = df_display[df_display["매매상태"].isin(["매도", "추천"])]
            display_trade_list(
                df_rebal[df_rebal["매매상태"] == "매도"],
                "시스템 매도 필요 종목",
                "매도",
                "sys_s",
                target_date_str,
                is_latest_date,
                market_type,
                holdings_db,
                top_n_cfg,
                account_total_input,
                current_engine_key,
            )
            display_trade_list(
                df_rebal[df_rebal["매매상태"] == "추천"],
                "시스템 매수 추천 종목",
                "매수",
                "sys_b",
                target_date_str,
                is_latest_date,
                market_type,
                holdings_db,
                top_n_cfg,
                account_total_input,
                current_engine_key,
            )

            st.write("")
            with st.expander("보유 종목 수동 매수/매도 입력 센터", expanded=False):
                col_m_left, col_m_right = st.columns(2)
                
                with col_m_left:
                    st.markdown("###### 수동 매수")
                    with st.container(border=True):
                        m_ticker = (
                            st.text_input("종목코드 (Ticker)", key="m_ticker")
                            .strip()
                            .upper()
                        )
                        c1, c2 = st.columns(2)
                        m_price = c1.number_input(
                            "매수가", min_value=0.0, value=0.0, key="m_price"
                        )
                        m_qty = c2.number_input(
                            "수량", min_value=0.0, value=1.0, key="m_qty"
                        )
                        m_date = st.date_input(
                            "매수일", value=selected_date, key="m_date"
                        )

                        if st.button(
                            "수동 매수 실행",
                            use_container_width=True,
                            type="primary",
                            key="btn_manual_buy_exec"
                        ):
                            if m_ticker and m_price > 0 and m_qty > 0:
                                update_holdings(
                                    m_ticker,
                                    "BUY",
                                    m_price,
                                    m_date,
                                    m_qty,
                                    market_type,
                                )
                                st.success(f"[{m_ticker}] 수동 매수 등록 완료")

                with col_m_right:
                    st.markdown("###### 수동 매도")
                    with st.container(border=True):
                        ms_ticker = (
                            st.text_input("매도 종목코드", key="ms_ticker")
                            .strip()
                            .upper()
                        )
                        c1, c2 = st.columns(2)
                        ms_price = c1.number_input(
                            "매도가", min_value=0.0, value=0.0, key="ms_price"
                        )
                        ms_qty = c2.number_input(
                            "수량", min_value=0.0, value=1.0, key="ms_qty"
                        )
                        ms_date = st.date_input(
                            "매도일", value=selected_date, key="ms_date"
                        )

                        exit_reason_preset = st.selectbox(
                            "청산 사유",
                            [
                                "수기 매도 (사용자 임의 청산)",
                                "목표가 도달 (수동 익절)",
                                "리스크 관리 (수동 손절)",
                                "재료 소멸 / 뉴스 악재",
                                "직접 입력",
                            ],
                            key="sb_exit_reason_preset"
                        )

                        final_exit_reason = exit_reason_preset

                        if st.button(
                            "수동 매도 실행",
                            use_container_width=True,
                            type="secondary",
                            key="btn_manual_sell_exec"
                        ):
                            if ms_ticker and ms_price > 0 and ms_qty > 0:
                                update_holdings(
                                    ms_ticker,
                                    "SELL",
                                    ms_price,
                                    ms_date,
                                    ms_qty,
                                    market_type,
                                    exit_reason=final_exit_reason
                                )
                                st.success(f"[{ms_ticker}] 매도 완료")

            st.markdown("---")

            with st.expander(
                f"[{market_type}] 운용 자금 설정 및 리스크 관리",
                expanded=False,
            ):
                col_cap1, col_cap2 = st.columns([2.5, 1.5])
                with col_cap1:
                    new_capital_input = st.number_input(
                        f"[{market_type}] 총 운용 자금 설정",
                        value=account_total_input,
                        step=100.0 if market_type == "US" else 1000000.0,
                        format="%.2f" if market_type == "US" else "%.0f",
                        key=f"tab3_cap_input_{market_type}",
                    )
                with col_cap2:
                    st.write("")
                    if st.button(
                        "자금 저장",
                        key=f"btn_save_cap_{market_type}",
                        use_container_width=True,
                        type="primary",
                    ):
                        st.session_state[cap_key] = new_capital_input
                        try:
                            res_existing = (
                                supabase.table("strategy_settings")
                                .select("*")
                                .eq("id", 1)
                                .execute()
                            )
                            existing_data = (
                                res_existing.data[0]
                                if res_existing.data
                                else {}
                            )
                            existing_data["id"] = 1
                            existing_data[cap_key] = float(new_capital_input)
                            existing_data["strategy_engine_mode"] = (
                                current_engine_key
                            )
                            supabase.table("strategy_settings").upsert(
                                existing_data
                            ).execute()
                            st.success("운용 자금 저장 완료")
                            st.rerun()
                        except Exception as e:
                            st.error(f"DB 저장 실패: {e}")

                max_risk_per_stock = new_capital_input * 0.02
                risk_fmt = (
                    f"${max_risk_per_stock:,.2f}"
                    if market_type == "US"
                    else f"{max_risk_per_stock:,.0f}원"
                )
                st.caption(
                    f"**단일 종목 최대 허용 손실 (2% Rule)**: {risk_fmt}"
                )
                account_total_input = new_capital_input

    # TAB 4: 성과 분석
    with tab4:
        st.markdown(f"##### {market_type} 시장 성과 분석 리포트")

        if not is_authenticated:
            st.info(
                "성과 내역 확인을 위해 우측 상단 [비밀번호 해제] 버튼을 클릭해 주십시오."
            )
        else:
            current_table_name = get_holdings_table(market_type)
            try:
                history_res = (
                    supabase.table(current_table_name)
                    .select("*")
                    .execute()
                )
                df_all_h = pd.DataFrame(history_res.data) if history_res.data else pd.DataFrame()
                if not df_all_h.empty and "sell_date" in df_all_h.columns:
                    df_hist_raw = df_all_h[df_all_h["sell_date"].notna() & (df_all_h["sell_date"] != "")].copy()
                else:
                    df_hist_raw = pd.DataFrame()
            except Exception as e:
                st.error(f"분석 데이터 조회 실패: {e}")
                df_hist_raw = pd.DataFrame()

            if df_hist_raw.empty:
                st.info("청산 완료된 매매 이력이 존재하지 않습니다.")
            else:
                df_hist_raw["sell_date_dt"] = pd.to_datetime(
                    df_hist_raw["sell_date"]
                )

                min_sell_date = df_hist_raw["sell_date_dt"].min().date()
                max_sell_date = df_hist_raw["sell_date_dt"].max().date()

                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    start_date_perf = st.date_input(
                        "조회 시작일",
                        value=min_sell_date,
                        key="perf_start_date",
                    )
                with col_d2:
                    end_date_perf = st.date_input(
                        "조회 종료일",
                        value=max_sell_date,
                        key="perf_end_date",
                    )

                mask_period = (
                    df_hist_raw["sell_date_dt"].dt.date >= start_date_perf
                ) & (df_hist_raw["sell_date_dt"].dt.date <= end_date_perf)
                df_hist = df_hist_raw[mask_period].copy()

                if df_hist.empty:
                    st.warning(
                        "선택하신 기간 내에 매도 완료된 거래 내역이 없습니다."
                    )
                else:
                    df_stocks_info = pd.DataFrame(
                        supabase.table("stocks")
                        .select("ticker, name")
                        .execute()
                        .data
                    )
                    if not df_stocks_info.empty:
                        df_stocks_info["ticker"] = (
                            df_stocks_info["ticker"].astype(str).str.strip()
                        )
                        df_hist = pd.merge(
                            df_hist, df_stocks_info, on="ticker", how="left"
                        )
                        df_hist["종목명"] = df_hist["name"].fillna(
                            df_hist["ticker"]
                        )
                    else:
                        df_hist["종목명"] = df_hist["ticker"]

                    if market_type == "US":
                        df_hist["종목명"] = df_hist.apply(
                            lambda r: f"[{r['ticker']}] {r['종목명']}", axis=1
                        )

                    df_hist["profit_amount"] = (
                        pd.to_numeric(
                            df_hist["profit_amount"], errors="coerce"
                        ).fillna(0.0)
                    )
                    df_hist["profit_rate"] = (
                        pd.to_numeric(
                            df_hist["profit_rate"], errors="coerce"
                        ).fillna(0.0)
                    )
                    df_hist["holding_days"] = (
                        df_hist["sell_date_dt"]
                        - pd.to_datetime(
                            df_hist["buy_date"], errors="coerce"
                        )
                    ).dt.days

                    df_hist = df_hist.sort_values("sell_date_dt")
                    total_profit = df_hist["profit_amount"].sum()
                    total_trades = len(df_hist)
                    win_df, loss_df = (
                        df_hist[df_hist["profit_amount"] > 0],
                        df_hist[df_hist["profit_amount"] < 0],
                    )
                    win_rate = (
                        (len(win_df) / total_trades * 100)
                        if total_trades > 0
                        else 0.0
                    )
                    loss_rate = (
                        (len(loss_df) / total_trades * 100)
                        if total_trades > 0
                        else 0.0
                    )

                    avg_win_amt = (
                        win_df["profit_amount"].mean()
                        if len(win_df) > 0
                        else 0.0
                    )
                    avg_loss_amt = (
                        abs(loss_df["profit_amount"].mean())
                        if len(loss_df) > 0
                        else 0.0
                    )
                    profit_factor = (
                        (avg_win_amt / avg_loss_amt)
                        if avg_loss_amt > 0
                        else 999.0
                    )
                    expectancy = ((win_rate / 100) * avg_win_amt) - (
                        (loss_rate / 100) * avg_loss_amt
                    )

                    profit_fmt = (
                        lambda x: f"${x:,.2f}"
                        if market_type == "US"
                        else f"{x:,.0f}원"
                    )
                    price_fmt = (
                        "{:,.2f}" if market_type == "US" else "{:,.0f}"
                    )

                    st.markdown("###### 핵심 성과 지표 (KPI)")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("총 실현 손익", profit_fmt(total_profit))
                    m2.metric(
                        "누적 수익률",
                        f"{(total_profit / account_total_input * 100):+.2f}%",
                    )
                    m3.metric(
                        "승률 / 패율", f"{win_rate:.1f}% / {loss_rate:.1f}%"
                    )
                    m4.metric("기대 수익", profit_fmt(expectancy))

                    st.write("")
                    st.markdown("###### 수익 기여도 시각화 차트")
                    draw_attribution_charts(df_hist, market_type)

                    st.write("")
                    st.markdown("###### 상세 청산 매매 내역")

                    df_hist_sorted = df_hist.sort_values("sell_date", ascending=False).reset_index(drop=True)
                    disp_cols = [
                        "sell_date",
                        "ticker",
                        "종목명",
                        "buy_date",
                        "buy_price",
                        "sell_price",
                        "quantity",
                        "profit_amount",
                        "profit_rate",
                        "holding_days",
                    ]
                    df_hist_disp = df_hist_sorted.rename(columns={"holding_days": "보유일수"}).copy()
                    disp_cols[-1] = "보유일수"

                    st.dataframe(
                        df_hist_disp[disp_cols].style.format({
                            "buy_price": price_fmt,
                            "sell_price": price_fmt,
                            "quantity": "{:,.2f}" if market_type == "US" else "{:,.0f}",
                            "profit_amount": profit_fmt,
                            "profit_rate": "{:+.2f}%",
                            "보유일수": "{:.0f}일",
                        }),
                        hide_index=True,
                        use_container_width=True,
                    )

    # TAB 5: 백테스트 리포트
    with tab5:
        st.markdown("##### [Top 7 Regime] 자동 백테스트 리포트")

        try:
            res_bt = (
                supabase.table("backtest_trades")
                .select("*")
                .order("sell_date", desc=True)
                .execute()
            )
            bt_data = res_bt.data if res_bt.data else []
        except Exception as e:
            bt_data = []

        if not bt_data:
            st.info("저장된 백테스트 내역이 없습니다.")
        else:
            df_bt = pd.DataFrame(bt_data)
            df_bt["profit_amount"] = pd.to_numeric(
                df_bt["profit_amount"], errors="coerce"
            ).fillna(0.0)
            df_bt["profit_rate"] = pd.to_numeric(
                df_bt["profit_rate"], errors="coerce"
            ).fillna(0.0)

            total_bt_trades = len(df_bt)
            win_bt = df_bt[df_bt["profit_amount"] > 0]
            loss_bt = df_bt[df_bt["profit_amount"] < 0]

            tot_bt_profit = df_bt["profit_amount"].sum()
            win_bt_rate = (
                (len(win_bt) / total_bt_trades * 100)
                if total_bt_trades > 0
                else 0.0
            )

            st.markdown("###### 백테스트 요약")
            b1, b2, b3 = st.columns(3)
            b1.metric("총 거래", f"{total_bt_trades}건")
            b2.metric("총 손익", f"{tot_bt_profit:+,.0f}원")
            b3.metric("승률", f"{win_bt_rate:.1f}%")

            st.divider()

            df_bt_disp = df_bt[[
                "sell_date",
                "buy_date",
                "ticker",
                "name",
                "buy_price",
                "sell_price",
                "quantity",
                "profit_amount",
                "profit_rate",
                "exit_reason",
            ]].copy()

            df_bt_disp = df_bt_disp.rename(columns={
                "sell_date": "매도일",
                "buy_date": "매수일",
                "ticker": "티커",
                "name": "종목명",
                "buy_price": "매수가",
                "sell_price": "매도가",
                "quantity": "수량",
                "profit_amount": "손익금액",
                "profit_rate": "수익률(%)",
                "exit_reason": "청산사유",
            })

            st.dataframe(
                df_bt_disp.style.format({
                    "매수가": "{:,.0f}원",
                    "매도가": "{:,.0f}원",
                    "수량": "{:,.0f}주",
                    "손익금액": "{:+,.0f}원",
                    "수익률(%)": "{:+.2f}%",
                }).map(
                    lambda v: "color: red;"
                    if float(v) > 0
                    else ("color: blue;" if float(v) < 0 else ""),
                    subset=["손익금액", "수익률(%)"],
                ),
                hide_index=True,
                use_container_width=True,
            )

else:
    st.warning("데이터를 불러오는 중입니다.")
