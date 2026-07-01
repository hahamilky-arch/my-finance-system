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
    target_idx = all_dates.index(target_date_str)
    
    # 데이터 로드
    df_curr = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date_str).eq("market", market_type).execute().data)
    prev_date = all_dates[min(target_idx + 1, len(all_dates)-1)]
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", prev_date).eq("market", market_type).execute().data)
    
    if df_curr.empty: return None
    df_curr = df_curr.rename(columns={'momentum_rank': '순위', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가'})
    df_prev = df_prev.rename(columns={'momentum_rank': '순위_prev'})
    
    df_final = pd.merge(df_curr, df_prev, on="ticker", how="left")
    df_final['변동'] = df_final['순위_prev'].fillna(999) - df_final['순위']
    df_final['is_new_top30'] = (df_final['순위'] <= 30) & (df_final['순위_prev'] > 30)
    # 고도화 필터: 100위 이내 + RS 0 이상 + 모멘텀 개선
    df_final['is_pullback'] = (df_final['순위'] <= 100) & (df_final['RS'] > 0) & (df_final['변동'] > 0)
    
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

# --- 3. UI 및 리밸런싱 시스템 ---
st.set_page_config(layout="wide")
#st.title("📈 Momentum Dashboard v1.2.0")
st.markdown("##### 📈 Momentum Dashboard v1.2.0") 

with st.sidebar:
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.date_input("Date", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    if st.button("Refresh"): st.rerun()

df_display = get_data(selected_date, all_dates, market_type)

if df_display is not None:
    tab1, tab2, tab3, tab4 = st.tabs(["Overview", "New Entries", "🎯 Pullback", "🔄 Rebalancing"])
    
    # 탭별 데이터 구성
    tab_dfs = [df_display.head(50), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']]]
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS', '종가']
    
    for i, tab in enumerate([tab1, tab2, tab3]):
        with tab:
            event = st.dataframe(tab_dfs[i][col_order].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', '변동': '{:+.0f}'}), 
                                hide_index=True, use_container_width=True, selection_mode="single-row", on_select="rerun")
            if st.button(f"📊 View Analysis", key=f"btn_{i}"):
                if event.selection and event.selection['rows']:
                    row = tab_dfs[i].iloc[event.selection['rows'][0]]
                    show_chart(row['ticker'], row['종목명'], market_type)
    
    with tab4:
        #st.subheader("📋 오늘의 리밸런싱 지시서")
        st.markdown("###### 📋 오늘의 리밸런싱 지시서")
        c1, c2 = st.columns(2)
        # SELL: 30위권 이탈
        sell_df = df_display[(df_display['순위'] > 30) & (df_display['순위_prev'] <= 30)]
        with c1:
            st.error(f"SELL (30위권 이탈): {len(sell_df)}종목")
            if not sell_df.empty: st.dataframe(sell_df[['종목명', '순위', '순위_prev']], use_container_width=True)
        # BUY: 신규 진입
        buy_df = df_display[df_display['is_new_top30']]
        with c2:
            st.success(f"BUY (신규 진입): {len(buy_df)}종목")
            if not buy_df.empty: st.dataframe(buy_df[['종목명', '순위']], use_container_width=True)
else:
    st.warning("No data found for selected date.")
