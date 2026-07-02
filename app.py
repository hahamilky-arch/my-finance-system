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

def get_available_dates():
    response = supabase.rpc("get_all_dates").execute()
    return [item['price_date'] for item in response.data] if response.data else []

def get_data(target_date, all_dates, market_type):
    target_date_str = pd.to_datetime(target_date).strftime('%Y-%m-%d')
    if target_date_str not in all_dates: return None
    
    # 1. 메인 데이터 로드 및 타입 변환
    res_curr = supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date_str).eq("market", market_type).execute()
    df_curr = pd.DataFrame(res_curr.data)
    df_curr['close_price'] = pd.to_numeric(df_curr['close_price'], errors='coerce')
    
    # 2. 이동평균 계산 (개선된 로직)
    res_hist = supabase.table("daily_analysis").select("ticker, price_date, close_price").eq("market", market_type).execute()
    df_hist = pd.DataFrame(res_hist.data)
    df_hist['price_date'] = pd.to_datetime(df_hist['price_date']).dt.strftime('%Y-%m-%d')
    df_hist['close_price'] = pd.to_numeric(df_hist['close_price'], errors='coerce')
    df_hist['ticker'] = df_hist['ticker'].astype(str).str.strip()
    
    # [핵심] 결측치 보간: 앞선 가격으로 채우기(ffill) + 정렬
    df_hist = df_hist.sort_values(['ticker', 'price_date'])
    df_hist['close_price'] = df_hist.groupby('ticker')['close_price'].ffill()
    
    # [핵심] min_periods=1을 사용하여 데이터가 20개 미만이어도 평균 계산
    df_hist['MA20'] = df_hist.groupby('ticker')['close_price'].transform(lambda x: x.rolling(window=20, min_periods=1).mean())
    # --- [여기에 추가] ---
    if df_hist['MA20'].sum() == 0:
        st.warning("MA20 계산 결과가 전부 0입니다. 데이터의 close_price 값이 모두 0이거나 데이터 타입 문제입니다.")
    else:
        # 데이터가 있다면 마지막 값을 출력해봅니다
        last_val = df_hist['MA20'].dropna().iloc[-1]
        st.write(f"계산된 MA20 샘플값: {last_val}")
    # -------------------
    
    # 3. 데이터 병합
    df_curr['ticker'] = df_curr['ticker'].astype(str).str.strip()
    ma20_today = df_hist[df_hist['price_date'] == target_date_str][['ticker', 'MA20']]
    df_curr = pd.merge(df_curr, ma20_today, on='ticker', how='left')
    
    # 4. 이전 날짜 순위 데이터
    target_idx = all_dates.index(target_date_str)
    prev_date = all_dates[min(target_idx + 1, len(all_dates)-1)]
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", prev_date).eq("market", market_type).execute().data)
    df_prev['ticker'] = df_prev['ticker'].astype(str).str.strip()
    
    # 병합
    df_curr = df_curr.rename(columns={'momentum_rank': '순위', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가'})
    df_prev = df_prev.rename(columns={'momentum_rank': '순위_prev'})
    df_final = pd.merge(df_curr, df_prev, on="ticker", how="left")
    
    # 5. 최적화 지표 계산
    df_final['변동'] = df_final['순위_prev'].fillna(999) - df_final['순위']
    df_final['is_new_top30'] = (df_final['순위'] <= 30) & (df_final['순위_prev'] > 30)
    df_final['is_pullback'] = (df_final['순위'] <= 100) & (df_final['RS'] > 0) & (df_final['변동'] > 0)
    
    # NaN이 발생하지 않도록 0으로 처리
    df_final['MA20'] = df_final['MA20'].fillna(0)
    df_final['is_no6_opt'] = (df_final['순위'] <= 30) & (df_final['RS'] > 0) & (df_final['종가'] > df_final['MA20'])
    
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_stocks['ticker'] = df_stocks['ticker'].astype(str).str.strip()
    return pd.merge(df_final, df_stocks, on="ticker", how="left").rename(columns={'name': '종목명'}).sort_values('순위')

# --- 2. UI 및 메인 로직 ---
st.set_page_config(layout="wide")
st.markdown("##### 📈 Momentum Dashboard v1.3.5") 

with st.sidebar:
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.date_input("Date", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    if st.button("Refresh"): st.rerun()

df_display = get_data(selected_date, all_dates, market_type)

if df_display is not None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "New Entries", "🎯 Pullback", "🚀 No.6 최적화", "🔄 Rebalancing"])
    
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS', '종가', 'MA20']
    tab_dfs = [df_display.head(100), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']], df_display[df_display['is_no6_opt']]]
    
    for i, tab in enumerate([tab1, tab2, tab3, tab4]):
        with tab:
            st.dataframe(tab_dfs[i][col_order].style.apply(apply_styles, axis=None).format({
                    'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'MA20': '{:,.0f}', '변동': '{:+.0f}'
                }), hide_index=True, use_container_width=True)
    
    with tab5:
        st.markdown("###### 📋 오늘의 리밸런싱 지시서")
        c1, c2 = st.columns(2)
        sell_df = df_display[(df_display['순위'] > 30) & (df_display['순위_prev'] <= 30)]
        with c1:
            st.error(f"SELL (30위권 이탈): {len(sell_df)}종목")
            if not sell_df.empty: st.dataframe(sell_df[['종목명', '순위', '순위_prev']], use_container_width=True)
        buy_df = df_display[df_display['is_new_top30']]
        with c2:
            st.success(f"BUY (신규 진입): {len(buy_df)}종목")
            if not buy_df.empty: st.dataframe(buy_df[['종목명', '순위']], use_container_width=True)
else:
    st.warning("데이터를 불러오는 중입니다.")
