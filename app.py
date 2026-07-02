import streamlit as st
import pandas as pd
from supabase import create_client

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# --- 1. 데이터 처리 및 스타일 ---
def apply_styles(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    if 'is_new_top30' in df.columns:
        df_styles.loc[df['is_new_top30'], :] = 'background-color: #ffcccc'
    if '변동' in df.columns:
        df_styles.loc[df['변동'] > 0, '변동'] = 'color: red'
        df_styles.loc[df['변동'] < 0, '변동'] = 'color: blue'
    return df_styles

def get_market_regime():
    """벤치마크 지수(^GSPC 등)를 확인하여 시장 상태가 안전한지 판단"""
    # 가장 데이터가 많은 벤치마크 지수를 가져옴
    res = supabase.table("daily_analysis").select("close_price, price_date").eq("ticker", "^GSPC").order("price_date", desc=True).limit(25).execute()
    df_idx = pd.DataFrame(res.data)
    if df_idx.empty: return True # 지수 데이터 없으면 기본적으로 안전하다고 가정
    
    df_idx['close_price'] = pd.to_numeric(df_idx['close_price'])
    ma20 = df_idx['close_price'].mean()
    current_price = df_idx.iloc[0]['close_price']
    
    return current_price >= ma20 # 가격이 MA20 이상이면 True(안전)

def get_available_dates():
    response = supabase.rpc("get_all_dates").execute()
    return [item['price_date'] for item in response.data] if response.data else []

def get_data(target_date, all_dates, market_type):
    target_date_ts = pd.Timestamp(target_date).normalize()
    target_date_str = target_date_ts.strftime('%Y-%m-%d')
    if target_date_str not in all_dates: return None

    # 1. 메인 데이터 로드
    res_curr = supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date_str).eq("market", market_type).execute()
    df_curr = pd.DataFrame(res_curr.data)
    df_curr['close_price'] = pd.to_numeric(df_curr['close_price'], errors='coerce').astype('float64')
    df_curr['ticker'] = df_curr['ticker'].astype(str).str.strip()
    
    ticker_list = df_curr['ticker'].unique()
    
    # 2. 개별 티커 루프 조회 (MA20 계산용)
    prices_list = []
    with st.spinner("종목별 데이터 조회 중..."):
        for ticker in ticker_list:
            res = supabase.table("daily_analysis").select("ticker, price_date, close_price").eq("ticker", ticker).order("price_date", desc=True).limit(21).execute()
            if res.data: prices_list.extend(res.data)
                
    df_hist = pd.DataFrame(prices_list)
    df_hist['price_date_ts'] = pd.to_datetime(df_hist['price_date']).dt.normalize()
    df_hist['close_price'] = pd.to_numeric(df_hist['close_price'], errors='coerce').astype('float64')
    df_hist = df_hist.sort_values(['ticker', 'price_date_ts'])
    df_hist['close_price'] = df_hist.groupby('ticker')['close_price'].ffill()
    df_hist['MA20'] = df_hist.groupby('ticker')['close_price'].transform(lambda x: x.rolling(window=20, min_periods=1).mean()).astype('float64')

    ma20_today = df_hist[df_hist['price_date_ts'] == target_date_ts][['ticker', 'MA20']].copy()
    
    df_final = pd.merge(df_curr, ma20_today, on='ticker', how='left')
    
    # 4. 이전 순위 병합
    target_idx = all_dates.index(target_date_str)
    prev_date = all_dates[min(target_idx + 1, len(all_dates)-1)]
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", prev_date).eq("market", market_type).execute().data)
    df_final = pd.merge(df_final, df_prev.rename(columns={'momentum_rank': '순위_prev'}), on="ticker", how='left')
    
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가'})
    
    # 5. 지표 및 매매 필터 적용
    df_final['변동'] = df_final['순위_prev'].fillna(999) - df_final['순위']
    df_final['is_new_top30'] = (df_final['순위'] <= 30) & (df_final['순위_prev'] > 30)
    df_final['MA20'] = df_final['MA20'].fillna(0)
    
    # 최종 매매 전략 컬럼
    df_final['is_no6_opt'] = (df_final['순위'] <= 30) & (df_final['RS'] > 0) & (df_final['종가'] > df_final['MA20']) & (df_final['MA20'] > 0)
    
    return df_final

# --- 2. UI 및 메인 로직 ---
st.set_page_config(layout="wide")
market_safe = get_market_regime()

if not market_safe:
    st.warning("⚠️ **시장 주의보:** 현재 시장 지수가 MA20 아래입니다. 신규 매수를 자제하고 리스크 관리에 집중하세요!")

with st.sidebar:
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.date_input("Date", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    if st.button("Refresh"): st.rerun()

df_display = get_data(selected_date, all_dates, market_type)

if df_display is not None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "New Entries", "🎯 Pullback", "🚀 No.6 최적화", "🔄 Rebalancing"])
    
    with tab5:
        st.markdown("###### 📋 오늘의 실전 리밸런싱 지시서")
        c1, c2 = st.columns(2)
        
        # SELL: 순위 이탈 OR (시장 위험시 전량 매도)
        sell_df = df_display[(df_display['순위'] > 30) | (not market_safe)]
        with c1:
            st.error(f"SELL (매도 필요): {len(sell_df)}종목")
            if not sell_df.empty: st.dataframe(sell_df[['종목명', '순위', '종가']], use_container_width=True)
            
        # BUY: 순위 30위 이내 AND 시장 안전할 때만
        buy_df = df_display[df_display['is_no6_opt'] & market_safe]
        with c2:
            st.success(f"BUY (신규 매수): {len(buy_df)}종목")
            if not buy_df.empty: st.dataframe(buy_df[['종목명', '순위', '종가']], use_container_width=True)
