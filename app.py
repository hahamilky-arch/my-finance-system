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
from strategy import get_data

st.set_page_config(layout="wide")

# 📌 0. 새로고침 및 페이지 이탈 방지 컨펌 팝업 스크립트
components.html(
    """
    <script>
    const preventReload = function (e) {
        e.preventDefault();
        e.returnValue = ''; // 브라우저 표준 경고 팝업 활성화
    };
    
    // 부모 창(Streamlit 메인 window)에 이벤트 등록
    window.parent.addEventListener('beforeunload', preventReload);
    </script>
    """,
    height=0,
)

st.markdown("<div id='top-section'></div>", unsafe_allow_html=True)

# 📌 1. 상단 탭 완벽 고정(Sticky) 및 기본 스타일 적용
st.markdown(
    """
    <style>
    /* 부모 컨테이너 overflow 제약 해제 (Sticky 정상 작동 필수) */
    [data-testid="stMainBlockContainer"], .main, .main .block-container {
        overflow: visible !important;
    }
    .block-container { padding-top: 1.5rem !important; padding-bottom: 2rem !important; }
    html, body, [class*="st-"] { font-size: 14px !important; }
    h5 { font-size: 1.2rem !important; margin-bottom: 0.5rem !important; }
    
    /* 상단 탭 스크롤 고정 (Sticky Tabs) */
    div[data-testid="stTabs"] > div:first-child,
    div[data-baseweb="tab-list"],
    .stTabs [role="tablist"] {
        position: sticky !important;
        top: 0px !important;
        background-color: #ffffff !important;
        z-index: 99999 !important;
        padding-top: 10px !important;
        padding-bottom: 6px !important;
        border-bottom: 2px solid #e0e0e0 !important;
        box-shadow: 0px 4px 10px rgba(0,0,0,0.05);
    }
    
    .floating-btn-left {
        position: fixed; bottom: 25px; left: 25px;
        background: linear-gradient(135deg, #2b5876 0%, #4e4376 100%);
        color: white !important; border-radius: 30px; padding: 10px 18px;
        font-weight: bold; box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        cursor: pointer; z-index: 999999; text-decoration: none;
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
    <a href="#top-section" class="floating-btn-left"><span>⬆</span> <span>위로</span></a>
""",
    unsafe_allow_html=True,
)

# 📌 2. 5분 비밀번호 유지 세션 및 1분 전 연장 알림 로직
LOGIN_TIMEOUT_SECONDS = 300  # 5분 (300초)

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
                if (remSec === 60) {{
                    if (confirm("⚠️ 매매 잠금 해제 만료 1분 전입니다.\\n인증 시간을 5분 연장하시겠습니까?")) {{
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


def switch_to_tab2():
    js_code = """
    <script>
    setTimeout(function() {
        const tabs = window.parent.document.querySelectorAll('button[data-baseweb="tab"], [role="tab"]');
        if (tabs && tabs.length >= 2) {
            tabs[1].click();
            tabs[1].scrollIntoView({behavior: 'smooth', block: 'center'});
        }
    }, 150);
    </script>
    """
    components.html(js_code, height=0)


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
        matched_mask = df["수급"] == "🔥"
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
        f"🚨 {title} (보유: {current_holdings_count}/{top_n_cfg}개 | 필요: {needed_slots}개)",
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
                    f"⚠️ 현재 슬롯 만석입니다 ({current_holdings_count}/{top_n_cfg}개 보유 중). 하단 예비 종목을 참고하세요."
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

            if "매도" in title:
                reason_desc = "지수 2일선 이탈, ATR 손절(-2.5x) 또는 익절 트레일링스탑(+15% 달성 후 -8% 반락)"
                position_info = ""
                tag_html = ""
            else:
                reason_desc = f"진입 조건 충족 (지수 2일 안착 완료) [추천순위: {rec_rank_display}]"
                target_pct = (100.0 / top_n_cfg) if top_n_cfg > 0 else 0.0
                atr_val = float(row.get("atr", 0.0))
                atr_str = (
                    f"{atr_val:,.2f}"
                    if market_type == "US"
                    else f"{atr_val:,.0f}"
                )
                position_info = f"<br><span style='font-size: 0.85em; color: #1b5e20; font-weight: bold;'>📊 분산 금액: {fmt_str} (비중 {target_pct:.1f}%) | ATR: {atr_str}</span>"
                tag_html = f"<span class='primary-tag'>🎯 추천 {p_idx}</span>"

            card_html = (
                f"<div style='line-height: 1.6; margin-top: 4px;'>"
                f"<strong style='font-size: 1.1em; color: #111111;'>{row['종목명']}</strong> "
                f"<span style='font-size: 0.8em; color: #888888; margin-left: 4px;'>({ticker})</span> "
                f"{tag_html} "
                f"<span style='font-size: 0.8em; color: #1565c0; font-weight: bold; margin-left: 6px;'>[순위: {rank_val}위 | 추천: {rec_rank_display}]</span>"
                f"<br><span style='font-size: 0.85em; color: #d62728; font-weight: bold;'>📌 사유: {reason_desc}</span>"
                f"{position_info}"
                f"<br><span style='font-size: 0.85em; color: #444444;'>MOT: {row['MOT']:.2f} | RS(90): {row['RS(90)']:.2f} | 이격도: {row['이격도']:+.2f}%</span>"
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
                                f"💡 자금관리 추천 수량: {atr_qty_str}주"
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
                        update_holdings(
                            ticker,
                            "SELL" if "매도" in title else "BUY",
                            input_price,
                            target_date,
                            input_qty,
                            market_type,
                        )
            else:
                c2.markdown(
                    "<div style='color:#999999; font-size:0.85em; margin-top:8px; text-align:right;'>과거일 불가</div>",
                    unsafe_allow_html=True,
                )

        if not backup_data.empty:
            st.markdown("---")
            st.markdown("###### 💡 예비 목록 (대기/교체용)")
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
                position_info = f"<br><span style='font-size: 0.85em; color: #856404; font-weight: bold;'>📊 예비 분산 금액: {fmt_str} | ATR: {atr_str}</span>"

                backup_html = (
                    f"<div style='line-height: 1.6; margin-top: 4px; background-color: #fffde7; padding: 8px 12px; border-radius: 6px; border-left: 4px solid #fbc02d;'>"
                    f"<strong style='font-size: 1.05em; color: #111111;'>{row['종목명']}</strong> "
                    f"<span style='font-size: 0.8em; color: #888888; margin-left: 4px;'>({ticker})</span> "
                    f"<span class='backup-tag'>💡 예비{backup_idx}</span> "
                    f"<span style='font-size: 0.8em; color: #d7ccc8; font-weight: bold; margin-left: 4px;'>[순위: {rank_val}위 | 추천: {rec_rank_display}]</span>"
                    f"<br><span style='font-size: 0.85em; color: #e65100; font-weight: bold;'>📌 사유: {reason_desc}</span>"
                    f"{position_info}"
                    f"<br><span style='font-size: 0.85em; color: #444444;'>MOT: {row['MOT']:.2f} | RS(90): {row['RS(90)']:.2f} | 이격도: {row['이격도']:+.2f}%</span>"
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
                        "<div style='color:#999999; font-size:0.85em; margin-top:8px; text-align:right;'>과거일 불가</div>",
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
    st.markdown("### ⚙️ 알파 매매전략 설정")

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
        "💡 전략 엔진 선택",
        [
            "🔥 전략 3: Top 7 레жим+익절스탑 (개선)",
            "🚀 단기 타점 모멘텀 (15%+ 랠리)",
            "🌐 Ultimate 듀얼 모멘텀 (추세)",
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

    # 📌 [시장 필터 보완] 지수 2일 연속 안착 체크
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
            "🔥 전략 3 개선 모드: Top 7 / Rank≤15 / ATR 2.5x손절 / +15%달성시 -8%익절스탑"
        )
        top_n_cfg = 7
        sl_cfg = -2.5
        rank_exit_limit = 15
    elif current_engine_key == "short_term":
        st.info(
            "🚀 단기 타점 모드: 상위 200위 / 15% 목표익절 / -5% 손절"
        )
        top_n_cfg = st.session_state.get("bull_top_n", 4)
        sl_cfg = st.session_state.get("bull_sl", -5.0)
        rank_exit_limit = 200
    else:
        if is_bull:
            st.success("🟢 상승장 모드 (Bull Market)")
            top_n_cfg = st.session_state.get("bull_top_n", 5)
            sl_cfg = st.session_state.get("bull_sl", -10.0)
            rank_exit_limit = 60
        else:
            st.error("🔴 하락장 모드 (Bear Market)")
            top_n_cfg = st.session_state.get("bear_top_n", 3)
            sl_cfg = st.session_state.get("bear_sl", -6.0)
            rank_exit_limit = 30

    if stop_new_buy:
        st.warning("⚠ 지수 MA20 하회 감지: 신규 매수 중지")
    elif reduce_holdings:
        st.warning("⚠️ 지수 불안정 감지: 보유 종목 비중 축소")

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

col_title, col_auth_status = st.columns([3, 1])
with col_title:
    st.markdown("##### 📈 Quant Alpha Strategy")

with col_auth_status:
    if is_authenticated:
        elapsed = time.time() - st.session_state.get("last_auth_time", 0)
        remaining_sec = max(0, int(LOGIN_TIMEOUT_SECONDS - elapsed))
        rem_min, rem_sec = remaining_sec // 60, remaining_sec % 60
        st.caption(f"🔓 인증됨 (남은 시간: {rem_min}분 {rem_sec}초)")

        c_ext, c_lock = st.columns(2)
        with c_ext:
            if st.button(
                "🔄 5분 연장",
                key="btn_extend_auth",
                use_container_width=True,
            ):
                st.session_state["last_auth_time"] = time.time()
                st.rerun()
        with c_lock:
            if st.button(
                "🔒 잠금", key="btn_global_lock", use_container_width=True
            ):
                st.session_state["trade_authenticated"] = False
                st.session_state["last_auth_time"] = 0
                st.rerun()
    else:
        with st.popover("🔑 잠금 해제", use_container_width=True):
            input_pwd_global = st.text_input(
                "매매 비밀번호", type="password", key="global_pwd_input"
            )
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
                    st.error("비밀번호 불일치")

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

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 시장 & 수급 종합",
        "🚀 알파 시그널",
        "💼 시스템 매매 지시서",
        "📈 성과 분석",
    ])

    # ----------------------------------------------------
    # TAB 1: 📊 시장 & 수급 종합 (Market Overview & 수급 동향)
    # ----------------------------------------------------
    with tab1:
        st.markdown("###### 📊 시장 방향성 & 스마트머니 수급 종합")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "전략 엔진",
            "🔥 전략 3 (개선)"
            if current_engine_key == "strat3_top7"
            else (
                "🚀 단기 타점"
                if current_engine_key == "short_term"
                else ("🟢 강세장" if is_bull else "🔴 약세장")
            ),
        )

        regime_status_str = (
            "🟢 상승장 (2일 안착)" if is_bull else "🔴 하락장 (MA20 이탈)"
        )
        c2.metric(
            "Market Regime",
            regime_status_str,
            delta="🛑 신규중지"
            if stop_new_buy
            else ("⚠️ 비중축소" if reduce_holdings else "✅ 매수허용"),
            delta_color="off",
        )

        buy_cnt = len(df_display[df_display["매매상태"] == "추천"])
        buy_cnt_display = min(buy_cnt, needed_slots)
        c3.metric(
            "오늘의 추천 종목",
            f"{buy_cnt_display}개",
            delta=f"슬롯 잔여: {needed_slots}/{top_n_cfg}",
        )

        sell_cnt = len(df_display[df_display["매매상태"] == "매도"])
        c4.metric("오늘의 매도 종목", f"{sell_cnt}개")

        st.divider()

        if not is_authenticated:
            st.info(
                "🔒 상세 투자자별/프로그램 매매동향 및 수급 지표는 우측 상단 **[🔑 잠금 해제]** 후 확인하실 수 있습니다."
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
                df_inv_all[df_inv_all["trade_date"] == target_date_str]
                if not df_inv_all.empty
                else pd.DataFrame()
            )
            df_prog = (
                df_prog_all[df_prog_all["trade_date"] == target_date_str]
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
            p_non_5d = (
                int(df_p_sorted.head(5)["non_arbitrage_net"].sum())
                if not df_p_sorted.empty
                else 0
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
            kq_f_days = (
                int((df_kq_all.head(5)["foreign_net"] > 0).sum())
                if not df_kq_all.empty
                else 0
            )
            kq_inst_days = (
                int((df_kq_all.head(5)["institution_net"] > 0).sum())
                if not df_kq_all.empty
                else 0
            )
            p_non_days = (
                int((df_p_sorted.head(5)["non_arbitrage_net"] > 0).sum())
                if not df_p_sorted.empty
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
                z_tag = "🔥 강한 수급 유입 (Z ≥ +1.5)"
            elif p_zscore <= -1.5:
                z_tag = "❄️ 강한 수급 이탈 (Z ≤ -1.5)"
            else:
                z_tag = "⚖ 정상 수급 범위"

            col_t1_left, col_t1_right = st.columns([1.1, 0.9])

            with col_t1_left:
                st.markdown("###### 🏛 수급 강도 & 연속성 지표 (20일 기준)")
                r1_1, r1_2, r1_3 = st.columns(3)
                r1_1.metric(
                    "비차익 Z-Score",
                    f"{p_zscore:+.2f}",
                    delta=z_tag,
                    delta_color="off",
                )
                r1_2.metric(
                    "비차익 5일 누적",
                    f"{p_non_5d:+,d} 백만원",
                    delta=f"5일 중 {p_non_days}일 순매수",
                )
                r1_3.metric(
                    "KOSPI 외인 5일",
                    f"{k_f_5d:+,d} 백만원",
                    delta=f"5일 중 {k_f_days}일 순매수",
                )

                st.write("")
                r2_1, r2_2, r2_3 = st.columns(3)
                r2_1.metric(
                    "KOSPI 기관 5일",
                    f"{k_inst_5d:+,d} 백만원",
                    delta=f"5일 중 {k_inst_days}일 순매수",
                )
                r2_2.metric(
                    "KOSDAQ 외인 5일",
                    f"{kq_f_5d:+,d} 백만원",
                    delta=f"5일 중 {kq_f_days}일 순매수",
                )
                r2_3.metric(
                    "KOSDAQ 기관 5일",
                    f"{kq_inst_5d:+,d} 백만원",
                    delta=f"5일 중 {kq_inst_days}일 순매수",
                )

            with col_t1_right:
                st.markdown("###### 🏆 당일 외국인 / 기관 순매수 TOP 5")
                try:
                    res_stock_liq = (
                        supabase.table("daily_top_liquidity")
                        .select("*")
                        .eq("trade_date", target_date_str)
                        .order("rank")
                        .execute()
                    )
                    df_stock_liq = (
                        pd.DataFrame(res_stock_liq.data)
                        if res_stock_liq.data
                        else pd.DataFrame()
                    )
                except Exception:
                    df_stock_liq = pd.DataFrame()

                if not df_stock_liq.empty:
                    tab_foreign, tab_inst = st.tabs(
                        ["🔥 외국인 TOP 5", "🏛 기관 TOP 5"]
                    )
                    with tab_foreign:
                        df_f_top = df_stock_liq.sort_values(
                            "foreign_net", ascending=False
                        ).head(5)[
                            [
                                "rank",
                                "name",
                                "close_price",
                                "change_rate",
                                "foreign_net",
                                "inst_net",
                            ]
                        ]
                        st.dataframe(
                            df_f_top.style.format({
                                "close_price": "{:,.0f}",
                                "change_rate": "{:+.2f}%",
                                "foreign_net": "{:+,.0f}",
                                "inst_net": "{:+,.0f}",
                            }),
                            hide_index=True,
                            use_container_width=True,
                        )
                    with tab_inst:
                        df_i_top = df_stock_liq.sort_values(
                            "inst_net", ascending=False
                        ).head(5)[
                            [
                                "rank",
                                "name",
                                "close_price",
                                "change_rate",
                                "foreign_net",
                                "inst_net",
                            ]
                        ]
                        st.dataframe(
                            df_i_top.style.format({
                                "close_price": "{:,.0f}",
                                "change_rate": "{:+.2f}%",
                                "foreign_net": "{:+,.0f}",
                                "inst_net": "{:+,.0f}",
                            }),
                            hide_index=True,
                            use_container_width=True,
                        )

    # ----------------------------------------------------
    # TAB 2: 🚀 알파 시그널 (전체 스크리닝 & 심층 분석)
    # ----------------------------------------------------
    with tab2:
        st.markdown("###### 📋 알파 시그널 스크리닝 (모멘텀 순위 상위 200위)")
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
        df_target = df_target[col_order].rename(
            columns={"매매상태": "상태", "이격도": "이격(%)", "atr": "ATR"}
        )

        st.dataframe(
            df_target.style.apply(apply_styles, axis=None).format({
                "이격(%)": "{:+.2f}%",
                "MOT": "{:.2f}",
                "RS(90)": "{:.2f}",
                "종가": "{:,.0f}",
            }),
            hide_index=True,
            use_container_width=True,
        )

    # ----------------------------------------------------
    # TAB 3: 💼 시스템 매매 지시서 (실질 매매 & 보유 계좌)
    # ----------------------------------------------------
    with tab3:
        st.markdown(
            f"##### 🚀 시스템 매매 지시서 [보유 현황: {current_holdings_count} / {top_n_cfg}개]"
        )

        if not is_authenticated:
            st.info(
                "🔒 실제 매매 신호 확인 및 주문 실행을 위해 우측 상단 **[🔑 잠금 해제]** 버튼을 클릭해 주십시오."
            )
        else:
            with st.expander(
                f"💼 현재 보유 종목 및 익절/손절 스탑 현황", expanded=True
            ):
                if not holdings_db.empty:
                    holdings_list = []
                    target_date_dt = pd.to_datetime(target_date_str)

                    for _, h_row in holdings_db.iterrows():
                        ticker = h_row["ticker"]
                        buy_price = float(h_row.get("buy_price", 0.0))
                        qty = float(h_row.get("quantity", 1.0))

                        curr_row = df_display[
                            df_display["ticker"].str.strip().str.upper()
                            == str(ticker).strip().upper()
                        ]
                        if not curr_row.empty:
                            curr_price = float(curr_row["종가"].values[0])
                            atr_val = (
                                float(curr_row.get("atr", 0.0).values[0])
                                if "atr" in curr_row.columns
                                else 0.0
                            )
                        else:
                            curr_price, atr_val = buy_price, 0.0

                        highest_price = max(
                            float(
                                h_row.get("highest_price", buy_price)
                                or buy_price
                            ),
                            curr_price,
                        )
                        eval_val = curr_price * qty
                        profit_amt = (curr_price - buy_price) * qty
                        profit_rate = (
                            ((curr_price / buy_price) - 1) * 100
                            if buy_price > 0
                            else 0.0
                        )

                        # 📌 [신규] 익절 전용 트레일링 스탑 계산 (+15% 달성 후 고점 대비 -8% 반락)
                        max_return = (
                            (highest_price / buy_price) - 1.0
                            if buy_price > 0
                            else 0.0
                        )
                        tp_stop_price = highest_price * 0.92

                        # 손절 ATR 스탑 계산
                        if atr_val > 0 and current_engine_key == "strat3_top7":
                            atr_stop_price = max(
                                buy_price - (2.5 * atr_val),
                                highest_price - (2.5 * atr_val),
                            )
                        else:
                            atr_stop_price = buy_price * (1 + (sl_cfg / 100.0))

                        status = "보유"
                        if max_return >= 0.15 and curr_price <= tp_stop_price:
                            status = "🎯 익절 스탑 (+15% 달성 후 -8% 반락)"
                        elif curr_price <= atr_stop_price:
                            status = "🚨 손절 ATR 스탑"

                        holdings_list.append({
                            "종목코드": ticker,
                            "수량": qty,
                            "평단가": buy_price,
                            "최고가": highest_price,
                            "현재가": curr_price,
                            "평가금액": eval_val,
                            "손익금액": profit_amt,
                            "수익률(%)": profit_rate,
                            "익절스탑가": tp_stop_price
                            if max_return >= 0.15
                            else "-",
                            "손절스탑가": atr_stop_price,
                            "상태": status,
                        })

                    df_h = pd.DataFrame(holdings_list)
                    st.dataframe(
                        df_h.style.format({
                            "평단가": "{:,.0f}",
                            "최고가": "{:,.0f}",
                            "현재가": "{:,.0f}",
                            "평가금액": "{:,.0f}",
                            "손익금액": "{:+,.0f}",
                            "수익률(%)": "{:+.2f}%",
                            "손절스탑가": "{:,.0f}",
                        }).map(
                            lambda x: "color: green; font-weight: bold;"
                            if "익절" in str(x)
                            else (
                                "color: red; font-weight: bold;"
                                if "손절" in str(x)
                                else ""
                            ),
                            subset=["상태"],
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

    # ----------------------------------------------------
    # TAB 4: 📈 성과 분석
    # ----------------------------------------------------
    with tab4:
        st.markdown(f"##### 📊 {market_type} 시장 성과 분석 리포트")
        if is_authenticated:
            current_table_name = get_holdings_table(market_type)
            try:
                history_res = (
                    supabase.table(current_table_name)
                    .select("*")
                    .not_.is_("sell_date", "null")
                    .execute()
                )
                df_hist_raw = (
                    pd.DataFrame(history_res.data)
                    if history_res.data
                    else pd.DataFrame()
                )
            except Exception:
                df_hist_raw = pd.DataFrame()

            if not df_hist_raw.empty:
                st.dataframe(df_hist_raw, use_container_width=True)
            else:
                st.info("청산 완료된 매매 내역이 없습니다.")
else:
    st.warning("데이터를 불러오는 중입니다.")
