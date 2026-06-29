import streamlit as st
import pandas as pd
from supabase import create_client

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1. 공통 데이터 처리 로직
def get_dashboard_data(target_date, market_type):
    target_date_str = str(target_date)
    
    # 1. Daily Analysis 로드
    df = pd.DataFrame(supabase.table("daily_analysis")
                      .select("ticker, momentum_rank, rs_score, close_price")
                      .eq("price_date", target_date_str).eq("market", market_type).execute().data)
    
    if df.empty: return None
    
    df['momentum_rank'] = pd.to_numeric(df['momentum_rank'], errors='coerce').fillna(999)
    df['rs_score'] = pd.to_numeric(df['rs_score'], errors='coerce').fillna(0)
    df['close_price'] = pd.to_numeric(df['close_price'], errors='coerce').fillna(0)
    
    # 2. 거래량 데이터 및 vol_ratio 계산
    ticker_list = tuple(df['ticker'].tolist())
    df_vol = pd.DataFrame(supabase.table("stock_prices")
                          .select("ticker, volume, price_date")
                          .in_("ticker", ticker_list).order("price_date", desc=True).limit(400).execute().data)
    
    if not df_vol.empty:
        df_vol['volume'] = pd.to_numeric(df_vol['volume'])
        df_vol['avg_vol_20'] = df_vol.groupby('ticker')['volume'].transform(lambda x: x.rolling(window=20).mean())
        df_today = df_vol[df_vol['price_date'] == target_date_str][['ticker', 'volume', 'avg_vol_20']]
        df = pd.merge(df, df_today, on='ticker', how='left')
        df['vol_ratio'] = df['volume'] / df['avg_vol_20']
    else:
        df['vol_ratio'] = 0.0
        
    return df

# 2. 메인 UI 구성
st.set_page_config(layout="wide")
st.markdown('<p style="font-size:24px; font-weight:bold;">📊 모멘텀 & No4 High-Octane 전략 대시보드</p>', unsafe_allow_html=True)

with st.sidebar:
    market_type = st.radio("시장 선택", ["KR", "US"], horizontal=True)
    selected_date = st.date_input("분석 기준일 선택")
    if st.button("데이터 새로고침"): st.rerun()

df = get_dashboard_data(selected_date, market_type)

if df is not None:
    tab1, tab2, tab3, tab4 = st.tabs(["전체 보기", "신규 진입", "매수 시그널", "🚀 No4: High-Octane"])

    with tab1:
        st.write("### 시장 전체 모멘텀 현황")
        st.dataframe(df.sort_values('momentum_rank'), use_container_width=True)
    
    with tab2:
        st.write("### 신규 진입주 (상위 30위 내)")
        st.dataframe(df[df['momentum_rank'] <= 30], use_container_width=True)
        
    with tab3:
        st.write("### 모멘텀 매수 시그널 (70~100위권 급등주)")
        st.dataframe(df[(df['momentum_rank'] >= 70) & (df['momentum_rank'] <= 100)], use_container_width=True)

    with tab4:
        st.subheader("🚀 High-Octane Momentum No4 전략")
        # 필터: 순위 100위 내 + RS 0.4 이상 + 거래량 2배 이상
        no4 = df[(df['momentum_rank'] <= 100) & (df['rs_score'] >= 0.4) & (df['vol_ratio'] >= 2.0)]
        
        if not no4.empty:
            st.success(f"{len(no4)}개의 강력한 주도주 신호가 포착되었습니다.")
            st.dataframe(no4, use_container_width=True)
            st.info("💡 매매 지침: 자산 40% 집중, 7% 트레일링 스탑, 60일선 이탈 시 전량 매도")
        else:
            st.warning("현재 No4 전략 조건에 부합하는 종목이 없습니다.")
else:
    st.error("선택하신 날짜에 데이터가 없습니다.")
