import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from plotly.subplots import make_subplots

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# --- 1. 데이터 처리 함수 ---
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
    
    df_curr = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date_str).eq("market", market_type).execute().data)
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", all_dates[min(target_idx + 1, len(all_dates)-1)]).eq("market", market_type).execute().data)
    df_days5 = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, close_price").eq("price_date", all_dates[min(target_idx + 5, len(all_dates)-1)]).eq("market", market_type).execute().data)
    
    if df_curr.empty: return None
    df_curr = df_curr.rename(columns={'momentum_rank': '순위', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가'})
    df_prev = df_prev.rename(columns={'momentum_rank': '순위_prev'})
    df_days5 = df_days5.rename(columns={'close_price': '종가_5일전'})
    
    df_final = pd.merge(pd.merge(df_curr, df_prev, on="ticker", how="left"), df_days5, on="ticker", how="left")
    df_final['변동'] = df_final['순위_prev'].fillna(999) - df_final['순위']
    df_final['주가변동률'] = (df_final['종가'] - df_final['종가_5일전']) / df_final['종가_5일전']
    df_final['is_new_top30'] = (df_final['순위'] <= 30) & (df_final['순위_prev'] > 30)
    
    # [전략 로직 적용] 1. 하락폭(-5%~0%), 2. 모멘텀 개선(변동 > 0)
    #df_final['is_pullback'] = (df_final['주가변동률'] < 0) & (df_final['주가변동률'] > -0.05) & (df_final['변동'] > 0)
    # 수정된 강력 필터 로직:
    df_final['is_pullback'] = (
        (df_final['주가변동률'] < 0) & 
        (df_final['주가변동률'] > -0.05) & 
        (df_final['변동'] > 0) &
        (df_final['순위'] <= 100) &    # 1. 순위 100위 이내만
        (df_final['RS'] > 0)           # 2. RS가 0보다 큰(상대적 강세) 종목만
    )
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    return pd.merge(df_final, df_stocks, on="ticker", how="left").rename(columns={'name': '종목명'}).sort_values('순위')

# --- 2. 팝업(Dialog) 함수 ---
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

# --- 3. UI 구성 ---
st.set_page_config(layout="wide")

with st.sidebar:
    market_type = st.radio("Market", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.date_input("Date", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    if st.button("Refresh"): st.rerun()
    st.caption("App Version: 1.1.7")

col1, col2 = st.columns([4, 1])
with col1: st.markdown('<p style="font-size:20px; font-weight:bold;">Momentum Analysis</p>', unsafe_allow_html=True)
with col2: st.caption(f"Date: {selected_date}")

df_display = get_data(selected_date, all_dates, market_type)

if df_display is not None:
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS', '종가']
    tab1, tab2, tab3 = st.tabs(["Overview (TOP 50)", "New Entries (TOP 30)", "🎯 Pullback/Trend"])
    
    # 탭별 데이터셋 정의
    tab_dfs = [df_display.head(50), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']]]
    
    for i, tab in enumerate([tab1, tab2, tab3]):
        with tab:
            # 선택된 행 정보를 session_state에 저장
            event = st.dataframe(tab_dfs[i][col_order].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', '변동': '{:+.0f}'}), 
                                hide_index=True, use_container_width=True, selection_mode="single-row", on_select="rerun")
            
            # 차트 보기 버튼
            if st.button(f"📊 View Analysis", key=f"btn_{i}"):
                if event.selection and event.selection['rows']:
                    row = tab_dfs[i].iloc[event.selection['rows'][0]]
                    show_chart(row['ticker'], row['종목명'], market_type)
                else:
                    st.warning("Please select a row first.")
else:
    st.warning("No data found.")
