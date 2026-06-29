import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from plotly.subplots import make_subplots

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1. 데이터 클렌징 함수 (에러 방지용)
def clean_df(df):
    cols_to_num = ['순위', 'rank_change', 'MOT', 'RS', '종가', 'vol_ratio']
    for col in cols_to_num:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df

# 2. 스타일 함수
def apply_styles(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    if 'is_new_top30' in df.columns:
        mask = df['is_new_top30']
        df_styles.loc[mask, :] = 'background-color: #ffcccc'
    if 'rank_change' in df.columns:
        df_styles.loc[df['rank_change'] > 0, 'rank_change'] = 'color: red'
        df_styles.loc[df['rank_change'] < 0, 'rank_change'] = 'color: blue'
    return df_styles

# 3. 데이터 조회 함수
def get_available_dates():
    response = supabase.rpc("get_all_dates").execute()
    return [item['price_date'] for item in response.data] if response.data else []

def get_data(target_date, all_dates, market_type):
    if target_date not in all_dates: return None
    target_idx = all_dates.index(target_date)
    previous_date = all_dates[target_idx + 1] if target_idx + 1 < len(all_dates) else target_date
    
    df_current = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date).eq("market", market_type).order("momentum_rank").execute().data)
    if df_current.empty: return None
    
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", previous_date).eq("market", market_type).execute().data)
    
    df_current['momentum_rank'] = pd.to_numeric(df_current['momentum_rank'])
    df_current['close_price'] = pd.to_numeric(df_current['close_price'])
    df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
    df_merged['rank_change'] = df_merged['momentum_rank_prev'].fillna(999) - df_merged['momentum_rank']
    
    # 거래량 계산
    ticker_list = tuple(df_merged['ticker'].tolist())
    df_vol = pd.DataFrame(supabase.table("stock_prices").select("ticker, volume, price_date").in_("ticker", ticker_list).order("price_date", desc=True).limit(400).execute().data)
    if not df_vol.empty:
        df_vol['volume'] = pd.to_numeric(df_vol['volume'])
        df_vol['avg_vol_20'] = df_vol.groupby('ticker')['volume'].transform(lambda x: x.rolling(window=20).mean())
        df_today_vol = df_vol[df_vol['price_date'] == target_date][['ticker', 'volume', 'avg_vol_20']]
        df_merged = pd.merge(df_merged, df_today_vol, on='ticker', how='left')
        df_merged['vol_ratio'] = df_merged['volume'] / df_merged['avg_vol_20']
    else:
        df_merged['vol_ratio'] = 0.0
    
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'name': '종목명', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가'})
    df_final['is_new_top30'] = (df_final['순위'] <= 30) & (df_final['momentum_rank_prev'] > 30)
    return clean_df(df_final)

# 4. 메인 UI
st.set_page_config(layout="wide")
st.markdown('<p style="font-size:24px; font-weight:bold;">📈 모멘텀 분석 (No3 전략 적용)</p>', unsafe_allow_html=True)

with st.sidebar:
    market_type = st.radio("시장 선택", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.selectbox("기준일 선택", options=all_dates)
    if st.button("새로고침"): st.rerun()

df_display = get_data(selected_date, all_dates, market_type)

if df_display is not None:
    tab1, tab2, tab3, tab4 = st.tabs(["전체 보기 (TOP 100)", "신규 진입주 (TOP 30)", "매수 시그널", "🚀 전략 No3"])

    # 탭별 출력 (clean_df로 데이터 타입 보장)
    with tab1:
        st.dataframe(df_display.head(100).style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}'}), 
                     hide_index=True, column_order=['순위', 'rank_change', '종목명', 'MOT', 'RS', '종가'], use_container_width=True)

    with tab2:
        df_new = df_display[df_display['is_new_top30'] == True].copy()
        st.dataframe(df_new[['순위', 'rank_change', '종목명', 'MOT', 'RS', '종가']].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}'}), 
                     hide_index=True, use_container_width=True)

    with tab3:
        buy_signals = df_display[(df_display['순위'] >= 70) & (df_display['순위'] <= 100) & (df_display['rank_change'] >= 20)]
        st.dataframe(buy_signals[['순위', 'rank_change', '종목명', '종가']].style.apply(apply_styles, axis=None).format({'rank_change': '{:+.0f}', '종가': '{:,.0f}'}), hide_index=True, use_container_width=True)

    with tab4:
        no3 = df_display[(df_display['순위'] <= 50) & (df_display['rank_change'] >= 20) & (df_display['vol_ratio'] >= 1.5)].copy()
        if not no3.empty:
            st.dataframe(no3[['순위', 'rank_change', '종목명', 'vol_ratio', 'MOT', 'RS', '종가']].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}', 'vol_ratio': '{:.2f}배'}), 
                         hide_index=True, use_container_width=True)
        else:
            st.info("현재 No3 전략(상위 50위+순위급등+거래량1.5배)에 부합하는 종목이 없습니다.")
