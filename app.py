import streamlit as st
import pandas as pd
from datetime import datetime
from strategy import get_data
from db import supabase, get_holdings_table, get_history_table, record_manual_buy, record_manual_sell

st.set_page_config(
    page_title="모멘텀 매매 자동화 시스템",
    page_icon="📈",
    layout="wide"
)

# 1. 사이드바 설정 (전략 및 파라미터 입력)
st.sidebar.header("⚙️ 매매 시스템 설정")

strategy_option = st.sidebar.selectbox(
    "실행 전략 엔진 선택",
    [
        "전략 3: Top 7 레짐+ATR 트레일링 (누적 +98.4%)",
        "전략 2: 15% 단기 랠리 타점 (MDD 방어형)",
        "전략 1: Ultimate 듀얼 모멘텀 (추세추종형)"
    ]
)

# 전략 모드 분기
if "전략 3" in strategy_option:
    engine_mode = "strat3_top7"
    default_slots = 7
elif "전략 2" in strategy_option:
    engine_mode = "strat2_short"
    default_slots = 4
else:
    engine_mode = "strat1_ultimate"
    default_slots = 4

market_type = st.sidebar.radio("대상 시장", ["KR", "US"])
total_capital = st.sidebar.number_input("현재 계좌 총 평가 자산 (원)", value=39682777, step=1000000, format="%d")
top_n_slots = st.sidebar.number_input("최대 보유 슬롯 수", value=default_slots, min_value=1, max_value=15)
target_date = st.sidebar.date_input("분석 기준일자", value=datetime.strptime("2026-09-10", "%Y-%m-%d").date())

# 시뮬레이션 환경 변수
rebalance_cycle = st.sidebar.selectbox("리밸런싱 주기", ["상시 (빈자리 즉시 채우기)", "매주 수요일"])
stop_new_buy = st.sidebar.checkbox("시장 경보 (신규 매수 중지)", value=False)
reduce_holdings = st.sidebar.checkbox("하락장 방어 (보유 슬롯 축소)", value=False)

# 2. 데이터 및 시그널 로드
df_result = get_data(
    target_date=target_date,
    all_dates=None,
    market_type=market_type,
    top_n_cfg=top_n_slots,
    sl_cfg=-5.0,
    rebalance_cycle=rebalance_cycle,
    is_bull_mode=not stop_new_buy,
    stop_new_buy=stop_new_buy,
    reduce_holdings=reduce_holdings,
    strategy_engine_mode=engine_mode
)

# 3. 메인 대시보드 화면 구성
st.title("📈 퀀트 모멘텀 매매 자동화 시스템")
st.markdown(f"**현재 가동 중인 전략**: `{strategy_option}` | **분석 기준일**: `{target_date}` | **총 계좌 자산**: `{total_capital:,.0f}원`")
st.markdown("---")

if df_result is not None and not df_result.empty:
    # 동적 복리 슬롯 배분 예산 (현재 총자산 / 슬롯 수)
    slot_budget = total_capital / top_n_slots
    
    # A. 매매 지시서 영역
    st.subheader("🎯 오늘의 매매 지시서")
    col1, col2 = st.columns(2)
    
    buy_candidates = df_result[df_result['매매상태'] == '매수추천'].sort_values('이격도' if engine_mode == "strat3_top7" else '순위')
    
    with col1:
        st.markdown("### 🟢 주매수 추천 종목 (슬롯 충전)")
        primary_buys = buy_candidates.head(top_n_slots).copy()
        if not primary_buys.empty:
            primary_buys['추천 수량'] = primary_buys['종가'].apply(lambda p: int(slot_budget / p) if p > 0 else 0)
            primary_buys['투입 예정금액'] = primary_buys['추천 수량'] * primary_buys['종가']
            st.dataframe(
                primary_buys[['ticker', '종목명', '순위', '종가', '이격도', '추천 수량', '투입 예정금액']],
                column_config={
                    "종가": st.column_config.NumberFormatColumn(format="%,.0f원"),
                    "이격도": st.column_config.NumberFormatColumn(format="%.2f%%"),
                    "투입 예정금액": st.column_config.NumberFormatColumn(format="%,.0f원")
                },
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("현재 조건에 부합하는 주매수 종목이 없거나 슬롯이 모두 채워져 있습니다.")

    with col2:
        st.markdown("### 🟡 후순위 예비 종목 (상위 대기)")
        reserve_buys = buy_candidates.iloc[top_n_slots:top_n_slots+2].copy()
        if not reserve_buys.empty:
            reserve_buys['추천 수량'] = reserve_buys['종가'].apply(lambda p: int(slot_budget / p) if p > 0 else 0)
            st.dataframe(
                reserve_buys[['ticker', '종목명', '순위', '종가', '이격도', '추천 수량']],
                column_config={
                    "종가": st.column_config.NumberFormatColumn(format="%,.0f원"),
                    "이격도": st.column_config.NumberFormatColumn(format="%.2f%%")
                },
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("현재 대기 중인 예비 종목이 없습니다.")

    st.markdown("---")

    # B. 실시간 보유 및 청산 필요 종목 알림
    st.markdown("### ⚠️ 보유 종목 청산 모니터링")
    sell_needed = df_result[df_result['매매상태'] == '매도필요']
    if not sell_needed.empty:
        st.warning("아래 종목들은 레짐 전환, ATR 손절 또는 트레일링 스탑 조건에 도달하여 **즉시 청산(현금화)**이 필요합니다.")
        st.dataframe(sell_needed[['ticker', '종목명', '종가', '매매상태', '제외사유']], use_container_width=True)
    else:
        st.success("현재 보유 중인 종목 중 긴급 매도(청산) 시그널이 발생한 종목은 없습니다.")

    st.markdown("---")

    # C. 현재 보유 포트폴리오 현황판 및 수동 매매 인터페이스
    st.subheader("💼 현재 보유 포트폴리오 관리")
    holdings_table_name = get_holdings_table(market_type)
    try:
        h_res = supabase.table(holdings_table_name).select("*").is_("sell_date", "null").execute()
        current_holdings = pd.DataFrame(h_res.data) if h_res.data else pd.DataFrame()
    except Exception:
        current_holdings = pd.DataFrame()

    if not current_holdings.empty:
        st.dataframe(current_holdings, use_container_width=True)
        
        # 수동 매도 처리 영역
        st.markdown("#### 🔄 수동 매도(청산) 처리")
        sell_ticker = st.selectbox("청산할 종목 선택", current_holdings['ticker'].tolist(), key="manual_sell_select")
        sell_price_input = st.number_input("실제 청산 가격", value=0.0, step=100.0)
        if st.button("선택 종목 매도 확정"):
            if sell_price_input > 0:
                record_manual_sell(market_type, sell_ticker, target_date.strftime('%Y-%m-%d'), sell_price_input)
                st.success(f"종목 {sell_ticker} 매도 처리가 완료되었습니다.")
                st.rerun()
            else:
                st.error("올바른 청산 가격을 입력해주세요.")
    else:
        st.info("현재 보유 중인 포트폴리오 내역이 없습니다.")

    st.markdown("---")

    # D. 전체 종목 스크리닝 결과 테이블
    st.subheader("📊 전체 유니버스 모멘텀 스크리닝 결과")
    
    tab1, tab2, tab3 = st.tabs(["전체 보기", "매수 추천만", "보유/매도 종목"])
    
    with tab1:
        st.dataframe(
            df_result[['순위', 'ticker', '종목명', '종가', '상승률', 'RS(90)', 'RS(10)', '이격도', '매매상태', '제외사유']],
            hide_index=True,
            use_container_width=True
        )
    with tab2:
        st.dataframe(
            df_result[df_result['매매상태'] == '매수추천'][['순위', 'ticker', '종목명', '종가', '이격도', '제외사유']],
            hide_index=True,
            use_container_width=True
        )
    with tab3:
        st.dataframe(
            df_result[df_result['매매상태'].isin(['보유중', '매도필요'])][['순위', 'ticker', '종목명', '종가', '매매상태', '제외사유']],
            hide_index=True,
            use_container_width=True
        )
else:
    st.error("선택한 날짜에 해당하는 분석 데이터를 Supabase에서 불러오지 못했습니다. 날짜나 시장 설정을 확인해주세요.")
