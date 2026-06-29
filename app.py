import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from plotly.subplots import make_subplots

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1. 스타일 함수: 순위 변화 색상 및 신규 진입 하이라이트
def apply_styles(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    
    if 'is_new_top30' in df.columns:
        mask = df['is_new_top30']
        df_styles.loc[mask, :] = 'background-color: #ffcccc'
        
    if 'rank_change' in df.columns:
        df_styles.loc[df['rank_change'] > 0, 'rank_change'] = 'color: red'
        df_styles.loc[df['rank_change'] < 0, 'rank_change'] = 'color: blue'
        
    return df_styles

# 2. 데이터 조회 및 계산 함수
def get_available_dates():
    response = supabase.rpc("get_all_dates").execute()
    if not response.data: return []
    return [item['price_date'] for item in response.data]

def get_data(target_date, all_dates, market_type):
    if target_date not in all_dates: return None
        
    target_idx = all_dates.index(target_date)
    previous_date = all_dates[target_idx + 1] if target_idx + 1 < len(all_dates) else target_date
    
    # 기본 분석 데이터 로드
    df_current = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date).eq("market", market_type).order("momentum_rank").execute().data)
    if df_current.empty: return None
    
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", previous_date).eq("market", market_type).execute().data)
    
    df_current['momentum_rank'] = pd.to_numeric(df_current['momentum_rank'])
    df_current['close_price'] = pd.to_numeric(df_current['close_price'])
    
    # 병합 및 로직 계산
    df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
    df_merged['momentum_rank_prev'] = df_merged['momentum_rank_prev'].fillna(999)
    df_merged['rank_change'] = df_merged['momentum_rank_prev'] - df_merged['momentum_rank']
    df_merged['is_new_top30'] = (df_merged['momentum_rank'] <= 30) & (df_merged['momentum_rank_prev'] > 30)
    df_merged['is_buy_signal'] = (df_merged['momentum_rank'] >= 70) & (df_merged['momentum_rank'] <= 100) & (df_merged['rank_change'] >= 20) & (df_merged['rank_change'] <= 25)

    # 거래량 비율(vol_ratio) 계산
    ticker_list = list(df_merged['ticker'].unique())
    df_vol = pd.DataFrame(supabase.table("stock_prices").select("ticker, volume, price_date").in_("ticker", ticker_list).execute().data)
    df_merged['vol_ratio'] = 0.0
    
    if not df_vol.empty:
        df_vol['volume'] = pd.to_numeric(df_vol['volume'], errors='coerce')
        df_vol['dt'] = pd.to_datetime(df_vol['price_date'])
        target_dt = pd.to_datetime(target_date)
        for ticker in ticker_list:
            sub = df_vol[df_vol['ticker'] == ticker].sort_values('dt')
            if len(sub) >= 5:
                ma20 = sub['volume'].rolling(window=20, min_periods=5).mean().iloc[-1]
                today_v = sub[sub['dt'] == target_dt]['volume']
                if not today_v.empty and ma20 > 0:
                    df_merged.loc[df_merged['ticker'] == ticker, 'vol_ratio'] = today_v.values[0] / ma20

    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")
    
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'name': '종목명', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가'})
    df_final['MOT'] = pd.to_numeric(df_final['MOT'], errors='coerce').fillna(0.0)
    df_final['RS'] = pd.to_numeric(df_final['RS'], errors='coerce').fillna(0.0)
    
    return df_final

# 3. 메인 UI
st.set_page_config(layout="wide")
st.markdown('<p style="font-size:24px; font-weight:bold;">📈 모멘텀 분석 대시보드</p>', unsafe_allow_html=True)

with st.sidebar:
    market_type = st.radio("시장 선택", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.selectbox("기준일 선택", options=all_dates)
    if st.button("새로고침"): st.rerun()

df_display = get_data(selected_date, all_dates, market_type)

if df_display is None:
    st.warning("데이터가 존재하지 않습니다.")
else:
    tab1, tab2, tab3, tab4 = st.tabs(["전체 보기", "신규 진입주", "매수 전략 시그널", "🚀 No4: High-Octane"])

    with tab1:
        use_filter = st.checkbox("주도주 필터 (RS > 0.03 & 순위 20위 내)")
        df_to_show = df_display.head(100).copy()
        if use_filter: df_to_show = df_to_show[(df_to_show['RS'] > 0.03) & (df_to_show['순위'] <= 20)]
        event = st.dataframe(df_to_show.style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}'}), hide_index=True, selection_mode="single-row", on_select="rerun", use_container_width=True)

    with tab2:
        df_new = df_display[df_display['is_new_top30'] == True]
        st.dataframe(df_new[['순위', 'rank_change', '종목명', 'MOT', 'RS', '종가']].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}'}), hide_index=True, use_container_width=True)

    with tab3:
        buy_signals = df_display[df_display['is_buy_signal'] == True]
        st.dataframe(buy_signals[['종목명', '순위', 'rank_change', '종가']].style.apply(apply_styles, axis=None).format({'rank_change': '{:+.0f}', '종가': '{:,.0f}'}), hide_index=True, use_container_width=True)

    with tab4:
        st.subheader("🚀 High-Octane No4 전략 (순위 100위/RS 0.4/거래량 2배)")
        no4 = df_display[(df_display['순위'] <= 100) & (df_display['RS'] >= 0.4) & (df_display['vol_ratio'] >= 2.0)]
        if not no4.empty:
            st.dataframe(no4[['순위', '종목명', 'RS', 'vol_ratio', '종가']].style.apply(apply_styles, axis=None).format({'RS': '{:.2f}', 'vol_ratio': '{:.2f}배', '종가': '{:,.0f}'}), hide_index=True, use_container_width=True)
        else:
            st.warning("조건에 부합하는 종목이 없습니다.")

    # 상세 차트
    if 'event' in locals() and event.selection and event.selection["rows"]:
        selected_index = event.selection["rows"][0]
        selected_ticker = df_to_show.iloc[selected_index]['ticker']
        with st.popover(f"📊 상세 분석", use_container_width=True):
            # 차트 로직... (이전 코드 동일 유지)
            st.write(f"{selected_ticker} 상세 차트 영역")
