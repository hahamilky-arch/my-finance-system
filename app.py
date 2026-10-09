import time
import numpy as np
import pandas as pd
import plotly.graph_objects as gg
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

# 페이지 새로고침 방지
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

st.markdown(
    """
    <style>
    [data-testid="stMainBlockContainer"], .main, .main .block-container {
        overflow: visible !important;
    }
    .block-container { padding-top: 1rem !important; padding-bottom: 2rem !important; }
    html, body, [class*="st-"] { font-size: 14px !important; }
    h5 { font-size: 1.2rem !important; margin-bottom: 0.5rem !important; }
    
    div[data-testid="stTabs"] > div:first-child,
    div[data-baseweb="tab-list"],
    .stTabs [role="tablist"] {
        position: sticky !important;
        top: 0px !important;
        background-color: #ffffff !important;
        z-index: 99999 !important;
        padding-top: 8px !important;
        padding-bottom: 4px !important;
        border-bottom: 2px solid #e0e0e0 !important;
        box-shadow: 0px 4px 10px rgba(0,0,0,0.05);
    }
    
    .backup-tag {
        background-color: #fff3cd; color: #856404; font-size: 0.85em; font-weight: bold;
        padding: 2px 8px; border-radius: 6px; border: 1px solid #ffeeba; margin-left: 6px;
        display: inline-block;
    }
    .primary-tag {
        background-color: #e3f2fd; color: #0d47a1; font-size: 0.85em; font-weight: bold;
        padding: 2px 8px; border-radius: 6px; border: 1px solid #bbdefb; margin-left: 6px;
        display: inline-block;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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


def apply_styles(df):
    df_s = pd.DataFrame("", index=df.index, columns=df.columns)
    for col in ["변동", "상승금액", "상승률"]:
        if col in df.columns:
            df_s.loc[df[col] > 0, col] += "color: red;"
            df_s.loc[df[col] < 0, col] += "color: blue;"
    if "상태" in df.columns:
        df_s.loc[df["상태"] == "추천", "상태"] += "color: #d62728; font-weight: bold;"
        df_s.loc[df["상태"] == "매도", "상태"] += "color: #1f77b4; font-weight: bold;"
        df_s.loc[df["상태"] == "보유", "상태"] += "color: #2ca02c; font-weight: bold;"
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
        fmt_str = f"${target_amount:,.2f}" if market_type == "US" else f"{target_amount:,.0f}원"

        if button_label == "매수":
            primary_data = data.iloc[:needed_slots] if needed_slots > 0 else pd.DataFrame()
            backup_data = data.iloc[needed_slots : needed_slots + 2]
        else:
            primary_data = data
            backup_data = pd.DataFrame()

        for p_idx, (_, row) in enumerate(primary_data.iterrows(), 1):
            ticker = row["ticker"]
            c1, c2 = st.columns([4, 1])

            rank_val = int(row.get("순위", 0)) if pd.notna(row.get("순위")) else "-"
            rec_rank_val = row.get("추천순위", row.get("매수추천순위", ""))
            rec_rank_display = f"{rec_rank_val}위" if rec_rank_val != "" else "-"
            raw_reason = str(row.get("제외사유", "")).strip()

            if "매도" in title:
                reason_desc = raw_reason if (raw_reason and raw_reason not in ["조건충족", "nan", "None"]) else "시스템 조건 청산"
                position_info = ""
                tag_html = ""
            else:
                reason_desc = f"진입 조건 충족 [추천순위: {rec_rank_display}]"
                target_pct = (100.0 / top_n_cfg) if top_n_cfg > 0 else 0.0
                atr_val = float(row.get("atr", 0.0))
                atr_str = f"{atr_val:,.2f}" if market_type == "US" else f"{atr_val:,.0f}"
                position_info = f"<br><span style='font-size: 0.85em; color: #1b5e20; font-weight: bold;'>분산 금액: {fmt_str} (비중 {target_pct:.1f}%) | ATR: {atr_str}</span>"
                tag_html = f"<span class='primary-tag'>추천 {p_idx}</span>"

            card_html = (
                f"<div style='line-height: 1.6; margin-top: 4px;'>"
                f"<strong style='font-size: 1.1em;'>{row['종목명']}</strong> ({ticker}) {tag_html} "
                f"<span style='font-size: 0.8e; color: #1565c0; font-weight: bold;'>[순위: {rank_val}위 | 추천: {rec_rank_display}]</span>"
                f"<br><span style='font-size: 0.85em; color: #d62728; font-weight: bold;'>사유: {reason_desc}</span>"
                f"{position_info}"
                f"<br><span style='font-size: 0.85em; color: #444444;'>MOT: {row['MOT']:.2f} | RS(90): {row['RS(90)']:.2f} | 이격도: {row['이격도']:+.2f}%</span>"
                f"</div>"
            )
            c1.markdown(card_html, unsafe_allow_html=True)

            if is_latest_date:
                with c2.popover(button_label):
                    st.write(f"**{row['종목명']}**")
                    input_price = st.number_input(f"{button_label}가", value=float(row["종가"]), key=f"p_{key_prefix}_{ticker}")
                    calc_qty = max(1.0, (target_amount / input_price) if input_price > 0 else 1.0)
                    input_qty = st.number_input("수량", value=calc_qty if market_type == "US" else float(int(calc_qty)), min_value=0.0, key=f"q_{key_prefix}_{ticker}")

                    if st.button("확인", key=f"btn_{key_prefix}_{ticker}"):
                        trade_type = "SELL" if "매도" in title else "BUY"
                        update_holdings(ticker, trade_type, input_price, target_date, input_qty, market_type, exit_reason=reason_desc if trade_type == "SELL" else None)


if "db_settings_loaded" not in st.session_state:
    st.session_state["db_settings_loaded"] = True

all_dates = get_available_dates()
latest_date_default = pd.to_datetime(all_dates[0]) if all_dates else None

with st.sidebar:
    st.markdown("### 알파 매매전략 설정")
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    selected_date = st.date_input("Date", value=latest_date_default)
    target_date_str = pd.to_datetime(selected_date).strftime("%Y-%m-%d") if selected_date else ""

    st.divider()
    strategy_engine_mode = st.radio("전략 엔진 선택", ["전략 3: Top 7 Regime", "단기 타점 모멘텀", "Ultimate 듀얼 모멘텀"], index=0)
    current_engine_key = "strat3_top7" if "전략 3" in strategy_engine_mode else ("short_term" if "단기" in strategy_engine_mode else "ultimate_dual")

    market_safe, stop_new_buy, reduce_holdings = get_market_regime(market_type, target_date_str)
    is_bull = market_safe
    top_n_cfg = 7 if current_engine_key == "strat3_top7" else 5
    sl_cfg = -2.5 if current_engine_key == "strat3_top7" else -5.0
    rebalance_cycle = "상시 (빈자리 즉시 채우기)"

cap_key = "us_capital" if market_type == "US" else "kr_capital"
account_total_input = float(st.session_state.get(cap_key, 20000000.0))

df_display = get_data(selected_date, all_dates, market_type, top_n_cfg, sl_cfg, rebalance_cycle, is_bull, stop_new_buy, reduce_holdings, current_engine_key)

if df_display is not None:
    if "매매상태" in df_display.columns:
        df_display["매매상태"] = df_display["매매상태"].replace({"매수추천": "추천", "매수필요": "매수", "매도필요": "매도", "보유중": "보유"})

    is_latest_date = (target_date_str == max(all_dates)) if all_dates and target_date_str else False
    holdings_db = pd.DataFrame()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["시장 & 수급 종합", "알파 시그널", "시스템 매매 지시서", "성과 분석", "백테스트 리포트"])

    # TAB 1: 시장 & 수급 종합
    with tab1:
        st.markdown("###### 시장 방향성 & 수급 종합")
        st.info("지수 추세 및 시장 분석 데이터를 확인합니다.")

        # 최하단 시장 지수 차트
        st.divider()
        index_name_str = "코스피 (^KS11)" if market_type == "KR" else "S&P 500 (^GSPC)"
        st.markdown(f"###### {index_name_str} 시장 지수 추이 (최근 120영업일)")

        target_index_symbol = "^KS11" if market_type == "KR" else "^GSPC"
        try:
            res_idx_chart = supabase.table("market_regime").select("*").order("trade_date", desc=True).limit(120).execute()
            if res_idx_chart.data:
                df_idx_c = pd.DataFrame(res_idx_chart.data)
                sym_col = "ticker" if "ticker" in df_idx_c.columns else ("index_name" if "index_name" in df_idx_c.columns else None)
                if sym_col:
                    df_idx_c = df_idx_c[df_idx_c[sym_col].astype(str).str.upper() == target_index_symbol]
                
                if not df_idx_c.empty:
                    df_idx_c["trade_date_dt"] = pd.to_datetime(df_idx_c["trade_date"])
                    df_idx_c = df_idx_c.sort_values("trade_date_dt").reset_index(drop=True)
                    df_idx_c["date_str"] = df_idx_c["trade_date_dt"].dt.strftime("%Y-%m-%d")
                    
                    close_col = "index_close" if "index_close" in df_idx_c.columns else "close_price"
                    df_idx_c["close_val"] = pd.to_numeric(df_idx_c[close_col], errors="coerce")
                    df_idx_c["ma20_val"] = pd.to_numeric(df_idx_c["ma20"], errors="coerce") if "ma20" in df_idx_c.columns else None

                    fig_market_idx = gg.Figure()
                    fig_market_idx.add_trace(gg.Scatter(x=df_idx_c["date_str"], y=df_idx_c["close_val"], mode="lines", name=f"{index_name_str} 종가", line=dict(color="#9467bd", width=2.5)))
                    if df_idx_c["ma20_val"].notna().any():
                        fig_market_idx.add_trace(gg.Scatter(x=df_idx_c["date_str"], y=df_idx_c["ma20_val"], mode="lines", name="MA20 (20일선)", line=dict(color="#ff7f0e", width=1.5, dash="dash")))

                    fig_market_idx.update_layout(height=320, margin=dict(l=20, r=20, t=30, b=20), xaxis=dict(type="category", tickangle=-45))
                    st.plotly_chart(fig_market_idx, use_container_width=True)
        except Exception as e:
            st.error(f"지수 차트 불러오기 실패: {e}")

    # TAB 2: 알파 시그널
    with tab2:
        st.markdown("###### 알파 시그널 스크리닝")
        st.dataframe(df_display.head(100), use_container_width=True)

    # TAB 3: 시스템 매매 지시서
    with tab3:
        st.markdown("##### 시스템 매매 지시서")
        display_trade_list(df_display[df_display["매매상태"] == "매도"], "시스템 매도 필요 종목", "매도", "sys_s", target_date_str, is_latest_date, market_type, holdings_db, top_n_cfg, account_total_input, current_engine_key)
        display_trade_list(df_display[df_display["매매상태"] == "추천"], "시스템 매수 추천 종목", "매수", "sys_b", target_date_str, is_latest_date, market_type, holdings_db, top_n_cfg, account_total_input, current_engine_key)

    # TAB 4: 성과 분석
    with tab4:
        st.markdown("##### 성과 분석 리포트")
        st.info("청산 완료 내역 분석을 진행합니다.")

    # TAB 5: 백테스트 리포트
    with tab5:
        st.markdown("##### 백테스트 결과")
        st.info("백테스트 시뮬레이션 결과를 노출합니다.")
