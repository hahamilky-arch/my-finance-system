import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from plotly.subplots import make_subplots

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1. 스타일 함수
def apply_styles(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    if 'is_new_top30' in df.columns:
        mask = df['is_new_top30']
        df_styles.loc[mask, :] = 'background-color: #ffcccc'
    if 'rank_change' in df.columns:
        df_styles.loc[df['rank_change'] > 0, 'rank_change'] = 'color: red'
        df_styles.loc[df['rank_change'] < 0, 'rank_change'] = 'color: blue'
    return df_styles

# 2. 데이터 조회 및 계산
def get_data(target_date, market_type):
    target_date_str = str(target_date) # YYYY-MM-DD
    
    # 기본 분석 데이터 로드
    df_current = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date_str).eq("market", market_type).execute().data)
    if df_current.empty: return None
    
    # 이전 날짜 데이터 가져오기 (가장 최근 데이터 기준)
    all_dates_res = supabase.rpc("get_all_dates").execute()
    all_dates = sorted([d['price_date'] for d in all_dates_res.data], reverse=True)
    try:
        idx = all_dates.index(target_date_str)
        previous_date = all_dates[idx + 1] if idx + 1 < len(all_dates) else target_date_str
    except:
        previous_date = target_date_str

    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", previous_date).eq("market", market_type).execute().data)
    
    # 데이터 정제
    df_current['momentum_rank'] = pd.to_numeric(df_current['momentum_rank'])
    df_current['close_price'] = pd.to_numeric(df_current['close_price'])
    df_current['rs_score'] = pd.to_numeric(df_current['rs_score'])
    df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
    df_merged['rank_change'] = df_merged['momentum_rank_prev'].fillna(999) - df_merged['momentum_rank']
    
    # 거래량 계산 (핵심: 날짜 형식 통일)
    ##ticker_list = list(df_merged['ticker'].unique())
    # 리스트가 비어있지 않을 때만 쿼리 실행
    if ticker_list:
        # ticker_list를 명확하게 리스트로 변환하여 전달
        df_vol = pd.DataFrame(supabase.table("stock_prices")
                              .select("ticker, volume, price_date")
                              .in_("ticker", ticker_list)
                              .execute().data)
    else:
        df_vol = pd.DataFrame()
        
    df_vol = pd.DataFrame(supabase.table("stock_prices").select("ticker, volume, price_date").in("ticker", ticker_list).execute().data)
    
    if not df_vol.empty:
        df_vol['volume'] = pd.to_numeric(df_vol['volume'], errors='coerce')
        # 날짜 문자열 통일
        df_vol['date_str'] = df_vol['price_date'].astype(str).str[:10]
        
        df_merged['vol_ratio'] = 0.0
        for ticker in ticker_list:
            sub = df_vol[df_vol['ticker'] == ticker].sort_values('date_str')
            if len(sub) >= 5:
                ma20 = sub['volume'].rolling(window=20, min_periods=5).mean().iloc[-1]
                today_v = sub[sub['date_str'] == target_date_str]
                if not today_v.empty and ma20 > 0:
                    df_merged.loc[df_merged['ticker'] == ticker, 'vol_ratio'] = today_v['volume'].values[0] / ma20

    # 종목명 병합 및 최종 정리
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'name': '종목명', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가'})
    df_final['is_new_top30'] = (df_final['순위'] <= 30) & (df_final['momentum_rank_prev'] > 30)
    return df_final

# 3. UI 구성
st.set_page_config(layout="wide")
st.markdown(f'<p style="font-size:24px; font-weight:bold;">📈 모멘텀 분석 대시보드</p>', unsafe_allow_html=True)

with st.sidebar:
    market_type = st.radio("시장 선택", ["KR", "US"], horizontal=True)
    selected_date = st.date_input("분석 기준일 선택")
    if st.button("데이터 새로고침"): st.rerun()

st.subheader(f"📅 분석 기준일: {selected_date}")
df_display = get_data(selected_date, market_type)

if df_display is not None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["전체 보기", "신규 진입주", "매수 시그널", "🚀 No3", "🚀 No4: High-Octane"])

    # 탭 구성 (위 코드와 동일하게 유지)
    with tab1:
        st.dataframe(df_display.head(100).style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}'}), hide_index=True, use_container_width=True)
    with tab5:
        st.subheader("🚀 High-Octane No4 전략 (순위 100위/RS 0.4/거래량 2배)")
        no4 = df_display[(df_display['순위'] <= 100) & (df_display['RS'] >= 0.4) & (df_display['vol_ratio'] >= 2.0)]
        if not no4.empty:
            st.success(f"{len(no4)}개의 강력한 주도주 신호가 포착되었습니다.")
            st.dataframe(no4[['순위', '종목명', 'RS', 'vol_ratio', '종가']].style.apply(apply_styles, axis=None).format({'RS': '{:.2f}', 'vol_ratio': '{:.2f}배', '종가': '{:,.0f}'}), hide_index=True, use_container_width=True)
        else:
            st.warning("조건에 부합하는 종목이 없습니다.")
