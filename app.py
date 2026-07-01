import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from plotly.subplots import make_subplots

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# --- 데이터 함수 (기존과 동일) ---
def apply_styles(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    if 'is_new_top30' in df.columns:
        mask = df['is_new_top30']
        df_styles.loc[mask, :] = 'background-color: #ffcccc'
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
    df_final['is_pullback'] = (df_final['주가변동률'] < 0) & (df_final['주가변동률'] > -0.05) & (df_final['변동'] > 0)
    
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    return pd.merge(df_final, df_stocks, on="ticker", how="left").rename(columns={'name': '종목명'}).sort_values('순위')

# --- UI 세션 ---
if 'sel_ticker' not in st.session_state: st.session_state.sel_ticker = None
if 'sel_name' not in st.session_state: st.session_state.sel_name = None

st.set_page_config(layout="wide")

with st.sidebar:
    market_type = st.radio("시장 선택", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.date_input("기준일 선택", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    if st.button("데이터 새로고침"): st.rerun()
    st.caption("App Version: 1.1.6")

col1, col2 = st.columns([4, 1])
with col1: st.markdown('<p style="font-size:20px; font-weight:bold;">Momentum Analysis</p>', unsafe_allow_html=True)
with col2: st.caption(f"Date: {selected_date}")

df_display = get_data(selected_date, all_dates, market_type)

if df_display is not None:
    col_order = ['순위', '변동', '종목명', 'MOT', 'RS', '종가']
    tab1, tab2, tab3 = st.tabs(["전체 보기 (TOP 50)", "신규 진입주 (TOP 30)", "🎯 눌림목/추세추종 포착"])
    
    tabs_dfs = [df_display.head(50), df_display[df_display['is_new_top30']], df_display[df_display['is_pullback']]]
    
    for i, tab in enumerate([tab1, tab2, tab3]):
        with tab:
            # selection_mode만 사용, on_select는 제거 (무한루프 방지)
            event = st.dataframe(tabs_dfs[i][col_order].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', '변동': '{:+.0f}'}), 
                                hide_index=True, use_container_width=True, selection_mode="single-row")
            
            if event.selection and event.selection["rows"]:
                st.session_state.sel_ticker = tabs_dfs[i].iloc[event.selection["rows"][0]]['ticker']
                st.session_state.sel_name = tabs_dfs[i].iloc[event.selection["rows"][0]]['종목명']
                st.rerun() # 여기서 딱 한 번만 재실행

    if st.session_state.sel_ticker:
        with st.expander(f"📊 {st.session_state.sel_name} 상세 분석 (Click to close)", expanded=True):
            # 차트 로직...
            history = pd.DataFrame(supabase.table("daily_analysis").select("price_date, momentum_rank, rs_score").eq("ticker", st.session_state.sel_ticker).eq("market", market_type).order("price_date", desc=True).limit(20).execute().data).sort_values("price_date")
            price = pd.DataFrame(supabase.table("stock_prices").select("price_date, close_price").eq("ticker", st.session_state.sel_ticker).order("price_date", desc=True).limit(20).execute().data).sort_values("price_date")
            combined = pd.merge(history, price, on="price_date")
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, subplot_titles=("주가", "모멘텀 순위"), row_heights=[0.6, 0.4])
            fig.add_trace(px.line(combined, x='price_date', y='close_price').data[0], row=1, col=1)
            fig.add_trace(px.line(combined, x='price_date', y='momentum_rank').data[0], row=2, col=1)
            fig.update_yaxes(autorange="reversed", row=2, col=1)
            st.plotly_chart(fig, use_container_width=True)
