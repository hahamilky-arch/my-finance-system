import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from plotly.subplots import make_subplots

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
    target_date_str = str(target_date)
    if target_date_str not in all_dates: return None
    
    # 1. 메인 데이터 로드 (ma20 제거, 직접 계산)
    res_curr = supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date_str).eq("market", market_type).execute()
    df_curr = pd.DataFrame(res_curr.data)
    
    # 2. 이동평균 계산을 위한 과거 데이터 로드
    res_hist = supabase.table("daily_analysis").select("ticker, price_date, close_price").eq("market", market_type).order("price_date", desc=True).limit(5000).execute()
    df_hist = pd.DataFrame(res_hist.data)
    df_hist['price_date'] = pd.to_datetime(df_hist['price_date'])
    df_hist = df_hist.sort_values(['ticker', 'price_date'])
    df_hist['MA20'] = df_hist.groupby('ticker')['close_price'].transform(lambda x: x.rolling(window=20).mean())
    
    # 3. 데이터 병합
    ma20_today = df_hist[df_hist['price_date'] == pd.to_datetime(target_date_str)][['ticker', 'MA20']]
    df_curr = pd.merge(df_curr, ma20_today, on='ticker', how='left')
    
    # 4. 이전 날짜 순위 데이터
    target_idx = all_dates.index(target_date_str)
    prev_date = all_dates[min(target_idx + 1, len(all_dates)-1)]
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", prev_date).eq("market", market_type).execute().data)
    
    if df_curr.empty: return None
    df_curr = df_curr.rename(columns={'momentum_rank': '순위', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가'})
    df_prev = df_prev.rename(columns={'momentum_rank': '순위_prev'})
    
    df_final = pd.merge(df_curr, df_prev, on="ticker", how="left")
    df_final['변동'] = df_final['순위_prev'].fillna(999) - df_final['순위']
    df_final['is_new_top30'] = (df_final['순위'] <= 30) & (df_final['순위_prev'] > 30)
    df_final['is_pullback'] = (df_final['순위'] <= 100) & (df_final['RS'] > 0) & (df_final['변동'] > 0)
    
    # No.6 최적화 로직 (30위 이내 + RS 양수 + 순위 개선 + 주가 > MA20)
    df_final['is_no6_opt'] = (df_final['순위'] <= 30) & (df_final['RS'] > 0) & (df_final['변동'] > 0) & (df_final['종가'] > df_final['MA20'])
    
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    return pd.merge(df_final, df_stocks, on="ticker", how="left").rename(columns={'name': '종목명'}).sort_values('순위')

# --- 2. 차트 팝업 ---
@st.dialog("Chart Analysis", width="large")
def show_chart(ticker, name, market_type):
    history = pd.DataFrame(supabase.table("daily_analysis").select("price_date, momentum_rank, rs_score").eq("ticker", ticker).eq("market", market_type).order("price_date", desc=True).limit(20).execute().data).sort_values("price_date")
    price = pd.DataFrame(supabase.table("stock_prices").select("price_date, close_price").eq("ticker", ticker).order("price_date", desc=True).limit(20).execute().data).sort_values("price_date")
    
    if not history.empty and not price.empty:
        combined = pd.merge(history, price, on="price_date")
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, subplot_titles=("Price", "Momentum Rank"), row_heights=[0.6, 0.4])
        fig.add_trace(px.line(combined, x='price_date', y='close_price').data[0], row=1, col=1)
        fig.add_trace(px.line(combined, x='price_date', y='momentum_rank').data[0], row=2, col=1)
        fig.update_yaxes(autorange="reversed", row=2, col=1)
        st.plotly_chart(fig, use_container_width=True)

# --- 3. UI 및 메인 로직 ---
st.set_page_config(layout="wide")
st.markdown("##### 📈 Momentum Dashboard v1.3.0") 

with st.sidebar:
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.date_input("Date", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    if st.button("Refresh"): st.rerun()

df_display = get_data(selected_date, all_dates, market_type)

if df_display is not None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "New Entries", "🎯 Pullback", "🚀 No.6 최적화", "🔄 Rebalancing"])
    
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS', '종가']
    tab_dfs = [df_display.head(100), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']], df_display[df_display['is_no6_opt']]]
    
    for i, tab in enumerate([tab1, tab2, tab3, tab4]):
        with tab:
            st.dataframe(tab_dfs[i][col_order].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', '변동': '{:+.0f}'}), 
                        hide_index=True, use_container_width=True)
    
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
    st.warning("No data found for selected date.")
