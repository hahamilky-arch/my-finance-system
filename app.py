import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from plotly.subplots import make_subplots

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1. 데이터 클렌징 및 전략 적용 함수
def get_no4_data(target_date, market_type):
    # Daily Analysis 데이터 로드
    df = pd.DataFrame(supabase.table("daily_analysis")
                      .select("ticker, momentum_rank, rs_score, close_price")
                      .eq("price_date", target_date).eq("market", market_type).execute().data)
    
    if df.empty: return None
    
    df['momentum_rank'] = pd.to_numeric(df['momentum_rank'])
    df['rs_score'] = pd.to_numeric(df['rs_score'])
    
    # 거래량 데이터 로드 및 vol_ratio 계산
    ticker_list = tuple(df['ticker'].tolist())
    df_vol = pd.DataFrame(supabase.table("stock_prices")
                          .select("ticker, volume, price_date")
                          .in_("ticker", ticker_list).order("price_date", desc=True).limit(400).execute().data)
    
    df_vol['volume'] = pd.to_numeric(df_vol['volume'])
    df_vol['avg_vol_20'] = df_vol.groupby('ticker')['volume'].transform(lambda x: x.rolling(window=20).mean())
    
    df_today_vol = df_vol[df_vol['price_date'] == target_date][['ticker', 'volume', 'avg_vol_20']]
    df_merged = pd.merge(df, df_today_vol, on='ticker', how='left')
    df_merged['vol_ratio'] = df_merged['volume'] / df_merged['avg_vol_20']
    
    # No4 전략 필터 적용: 100위 내 + RS 0.4 이상 + 거래량 2배 이상
    no4_df = df_merged[(df_merged['momentum_rank'] <= 100) & 
                       (df_merged['rs_score'] >= 0.4) & 
                       (df_merged['vol_ratio'] >= 2.0)]
    
    return no4_df

# 2. 메인 UI 구성
st.set_page_config(layout="wide")
st.markdown('<p style="font-size:24px; font-weight:bold;">🚀 High-Octane Momentum No4 전략</p>', unsafe_allow_html=True)

with st.sidebar:
    market_type = st.radio("시장 선택", ["KR", "US"], horizontal=True)
    selected_date = st.date_input("기준일 선택")
    if st.button("전략 신호 검색"): st.rerun()

df_no4 = get_no4_data(str(selected_date), market_type)

# 3. 결과 출력
if df_no4 is not None and not df_no4.empty:
    st.success(f"{len(df_no4)}개의 주도주 신호가 포착되었습니다.")
    st.dataframe(
        df_no4[['momentum_rank', 'ticker', 'rs_score', 'vol_ratio', 'close_price']]
        .rename(columns={'momentum_rank': '순위', 'ticker': '티커', 'rs_score': 'RS점수', 'vol_ratio': '거래량배수', 'close_price': '현재가'}),
        use_container_width=True, hide_index=True
    )
    
    st.info("💡 매매 전략: 자산 40% 집중, 7% 트레일링 스탑, 60일선 이탈 시 전량 매도")
else:
    st.warning("현재 조건(순위 100위+RS 0.4+거래량 2배)을 충족하는 종목이 없습니다. 시장 에너지가 응축 중입니다.")
