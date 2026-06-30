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

# 2. 데이터 조회 및 계산 함수
def get_available_dates():
    response = supabase.rpc("get_all_dates").execute()
    if not response.data: return []
    return [item['price_date'] for item in response.data]

def get_data(target_date, all_dates, market_type):
    target_date_str = str(target_date)
    if target_date_str not in all_dates: return None
        
    target_idx = all_dates.index(target_date_str)
    previous_date = all_dates[target_idx + 1] if target_idx + 1 < len(all_dates) else target_date_str
    
    df_current = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date_str).eq("market", market_type).order("momentum_rank").execute().data)
    if df_current.empty: return None
    
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", previous_date).eq("market", market_type).execute().data)
    
    df_current['momentum_rank'] = pd.to_numeric(df_current['momentum_rank'])
    df_current['close_price'] = pd.to_numeric(df_current['close_price'])
    
    df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
    df_merged['momentum_rank_prev'] = df_merged['momentum_rank_prev'].fillna(999)
    df_merged['rank_change'] = df_merged['momentum_rank_prev'] - df_merged['momentum_rank']
    df_merged['is_new_top30'] = (df_merged['momentum_rank'] <= 30) & (df_merged['momentum_rank_prev'] > 30)
    df_merged['is_buy_signal'] = (df_merged['momentum_rank'] >= 70) & (df_merged['momentum_rank'] <= 100) & (df_merged['rank_change'] >= 20) & (df_merged['rank_change'] <= 25)

    ticker_list = list(df_merged['ticker'].unique())
    df_merged['vol_ratio'] = 0.0
    
    if ticker_list:
        df_vol = pd.DataFrame(supabase.table("stock_prices").select("ticker, volume, price_date").in_("ticker", ticker_list).execute().data)
        if not df_vol.empty:
            df_vol['volume'] = pd.to_numeric(df_vol['volume'], errors='coerce')
            df_vol['dt'] = pd.to_datetime(df_vol['price_date'])
            target_dt = pd.to_datetime(target_date_str)
            for ticker in ticker_list:
                sub = df_vol[df_vol['ticker'] == ticker].sort_values('dt')
                if len(sub) >= 5:
                    ma20 = sub['volume'].rolling(window=20, min_periods=5).mean().iloc[-1]
                    today_v = sub[sub['dt'] == target_dt]['volume']
                    if not today_v.empty and ma20 > 0:
                        df_merged.loc[df_merged['ticker'] == ticker, 'vol_ratio'] = today_v.values[0] / ma20

    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")
    
    df_final = df_final.rename(columns={
        'momentum_rank': '순위', 
        'name': '종목명', 
        'weighted_momentum': 'MOT', 
        'rs_score': 'RS', 
        'close_price': '종가',
        'rank_change': '변동'  # 이 줄을 추가하세요
    })

    df_final['MOT'] = pd.to_numeric(df_final['MOT'], errors='coerce').fillna(0.0)
    df_final['RS'] = pd.to_numeric(df_final['RS'], errors='coerce').fillna(0.0)
    
    return df_final

# 3. 메인 UI
st.set_page_config(layout="wide")
st.markdown('<p style="font-size:24px; font-weight:bold;">📈 모멘텀 분석 대시보드</p>', unsafe_allow_html=True)

with st.sidebar:
    market_type = st.radio("시장 선택", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    # 달력에서 날짜 선택
    selected_date = st.date_input("분석 기준일 선택", value=pd.to_datetime(all_dates[0]) if all_dates else None)
    if st.button("데이터 새로고침"): st.rerun()

df_display = get_data(selected_date, all_dates, market_type)

if df_display is not None:
    col_order = ['순위', 'rank_change', '종목명', 'MOT', 'RS', '종가']
    tab1, tab2, tab3, tab4 = st.tabs(["전체 보기", "신규 진입주", "매수 전략 시그널", "🚀 No4: High-Octane"])

    with tab1:
        use_filter = st.checkbox("주도주 필터 (RS > 0.03 & 순위 20위 내)")
        df_to_show = df_display.head(100).copy()
        if use_filter: df_to_show = df_to_show[(df_to_show['RS'] > 0.03) & (df_to_show['순위'] <= 20)]
        event = st.dataframe(df_to_show.style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}'}), 
                             column_order=col_order, hide_index=True, selection_mode="single-row", on_select="rerun", use_container_width=True)

    with tab2:
        st.dataframe(df_display[df_display['is_new_top30'] == True][col_order].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}'}), hide_index=True, use_container_width=True)

    with tab3:
        st.dataframe(df_display[df_display['is_buy_signal'] == True][col_order].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}'}), hide_index=True, use_container_width=True)

    with tab4:
        no4 = df_display[(df_display['순위'] <= 100) & (df_display['RS'] >= 0.4) & (df_display['vol_ratio'] >= 2.0)]
        st.dataframe(no4[['순위', '종목명', 'RS', 'vol_ratio', '종가']].style.apply(apply_styles, axis=None).format({'RS': '{:.2f}', 'vol_ratio': '{:.2f}배', '종가': '{:,.0f}'}), hide_index=True, use_container_width=True)

    # 4. 상세 차트 (수정된 부분)
    if 'event' in locals() and event.selection and event.selection["rows"]:
        selected_index = event.selection["rows"][0]
        ticker = df_to_show.iloc[selected_index]['ticker']
        selected_name = df_to_show.iloc[selected_index]['종목명'] # 종목명 추가
        
        with st.popover(f"📊 {selected_name} 상세 분석", use_container_width=True):
            history_df = pd.DataFrame(supabase.table("daily_analysis").select("price_date, momentum_rank, rs_score").eq("ticker", ticker).eq("market", market_type).order("price_date", desc=True).limit(20).execute().data).sort_values("price_date")
            price_df = pd.DataFrame(supabase.table("stock_prices").select("price_date, close_price").eq("ticker", ticker).order("price_date", desc=True).limit(20).execute().data).sort_values("price_date")
            combined = pd.merge(history_df, price_df, on="price_date")
            
            # 그래프 제목 표시 및 레이아웃 설정
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                subplot_titles=("주가 추이 (Close Price)", "모멘텀 순위 (Momentum Rank)"),
                                row_heights=[0.6, 0.4])
            
            fig.add_trace(px.line(combined, x='price_date', y='close_price').data[0], row=1, col=1)
            fig.add_trace(px.line(combined, x='price_date', y='momentum_rank').data[0], row=2, col=1)
            
            fig.update_yaxes(autorange="reversed", row=2, col=1) # 모멘텀 순위는 낮을수록 좋으므로 역전
            fig.update_layout(height=500, showlegend=False)
            
            st.plotly_chart(fig, use_container_width=True)
