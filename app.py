import streamlit as st
import pandas as pd
from strategy import get_data

st.set_page_config(page_title="모멘텀 매매 시스템", layout="wide")

# 사이드바 설정
st.sidebar.header("⚙️ 전략 선택 및 파라미터")

strategy_option = st.sidebar.selectbox(
    "실행 전략 엔진 선택",
    [
        "전략 3: Top 7 레짐+ATR 트레일링 (+98.4% 누적수익)",
        "전략 2: 15% 단기 랠리 타점 (MDD -11% 우수)",
        "전략 1: Ultimate 듀얼 모멘텀 (추세추종)"
    ]
)

# 전략 모드 매핑
if "전략 3" in strategy_option:
    engine_mode = "strat3_top7"
    default_slots = 7
elif "전략 2" in strategy_option:
    engine_mode = "strat2_short"
    default_slots = 4
else:
    engine_mode = "strat1_ultimate"
    default_slots = 4

market_type = st.sidebar.radio("시장 선택", ["KR", "US"])
total_capital = st.sidebar.number_input("현재 총 평가 자산 (원)", value=20000000, step=1000000)
top_n_slots = st.sidebar.number_input("최대 보유 슬롯 수", value=default_slots, min_value=1, max_value=10)
target_date = st.sidebar.date_input("분석 기준일자")

# 레짐 및 전략 실행 데이터 가져오기
df_result = get_data(
    target_date=target_date,
    all_dates=None,
    market_type=market_type,
    top_n_cfg=top_n_slots,
    sl_cfg=-5.0,
    rebalance_cycle="상시 (빈자리 즉시 채우기)",
    is_bull_mode=True, # 레짐 상태
    stop_new_buy=False,
    reduce_holdings=False,
    strategy_engine_mode=engine_mode
)

st.title(f"📈 모멘텀 매매 시스템 - {strategy_option.split(':')[0]}")

if df_result is not None:
    # 1. 매수 추천 / 후순위 예비 종목 분리
    buy_candidates = df_result[df_result['매매상태'] == '매수추천'].sort_values('이격도' if engine_mode == "strat3_top7" else '순위')
    
    # 동적 복리 자금 계산 (현재 총자산 / 슬롯 수)
    slot_budget = total_capital / top_n_slots
    
    st.subheader("🎯 오늘의 매매 지시서")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🟢 주매수 추천 종목 (슬롯 채우기)")
        primary_buys = buy_candidates.head(top_n_slots).copy()
        if not primary_buys.empty:
            primary_buys['추천 매수수량'] = primary_buys['종가'].apply(lambda price: int(slot_budget / price) if price > 0 else 0)
            primary_buys['투입예정금액'] = primary_buys['추천 매수수량'] * primary_buys['종가']
            st.dataframe(primary_buys[['ticker', '종목명', '순위', '종가', '이격도', '추천 매수수량', '투입예정금액']])
        else:
            st.info("현재 조건에 맞는 주매수 종목이 없거나 슬롯이 가득 찼습니다.")

    with col2:
        st.markdown("### 🟡 후순위 예비 추천 종목 (상위 2개)")
        reserve_buys = buy_candidates.iloc[top_n_slots:top_n_slots+2].copy()
        if not reserve_buys.empty:
            reserve_buys['추천 매수수량'] = reserve_buys['종가'].apply(lambda price: int(slot_budget / price) if price > 0 else 0)
            st.dataframe(reserve_buys[['ticker', '종목명', '순위', '종가', '이격도', '추천 매수수량']])
        else:
            st.info("예비 종목이 없습니다.")

    # 2. 전체 종목 분석 데이터 테이블
    st.subheader("📊 전체 종목 모멘텀 스크리닝")
    st.dataframe(df_result[['순위', 'ticker', '종목명', '종가', '상승률', 'RS(90)', 'RS(10)', '이격도', '매매상태', '제외사유']])
