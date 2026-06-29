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
    
    # 신규 진입 하이라이트
    if 'is_new_top30' in df.columns:
        mask = df['is_new_top30']
        df_styles.loc[mask, :] = 'background-color: #ffcccc'
        
    # 순위 변화 색상 (상승: 빨강, 하락: 파랑)
    if 'rank_change' in df.columns:
        df_styles.loc[df['rank_change'] > 0, 'rank_change'] = 'color: red'
        df_styles.loc[df['rank_change'] < 0, 'rank_change'] = 'color: blue'
        
    return df_styles

# 2. 날짜 리스트 및 데이터 조회 함수
def get_available_dates():
    response = supabase.rpc("get_all_dates").execute()
    if not response.data:
        return []
    return [item['price_date'] for item in response.data]

def get_data(target_date, all_dates, market_type):
    if target_date not in all_dates:
        return None
        
    target_idx = all_dates.index(target_date)
    previous_date = all_dates[target_idx + 1] if target_idx + 1 < len(all_dates) else target_date
    
    # 데이터 로드
    df_current = pd.DataFrame(supabase.table("daily_analysis")
                                .select("ticker, momentum_rank, weighted_momentum, rs_score, close_price")
                                .eq("price_date", target_date)
                                .eq("market", market_type)
                                .order("momentum_rank")
                                .execute().data)
    
    if df_current.empty:
        return None

    df_prev = pd.DataFrame(supabase.table("daily_analysis")
                            .select("ticker, momentum_rank")
                            .eq("price_date", previous_date)
                            .eq("market", market_type)
                            .execute().data)
    
    df_current['momentum_rank'] = pd.to_numeric(df_current['momentum_rank'])
    df_current['close_price'] = pd.to_numeric(df_current['close_price'])
    df_prev['momentum_rank'] = pd.to_numeric(df_prev['momentum_rank'])
    
    # 병합 및 로직 계산
    df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
    df_merged['momentum_rank_prev'] = df_merged['momentum_rank_prev'].fillna(999)
    df_merged['rank_change'] = df_merged['momentum_rank_prev'] - df_merged['momentum_rank']
    df_merged['is_new_top30'] = (df_merged['momentum_rank'] <= 30) & (df_merged['momentum_rank_prev'] > 30)
    df_merged['is_buy_signal'] = (df_merged['momentum_rank'] >= 70) & (df_merged['momentum_rank'] <= 100) & (df_merged['rank_change'] >= 20) & (df_merged['rank_change'] <= 25)

    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")
    
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'name': '종목명', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가'})
    df_final['MOT'] = pd.to_numeric(df_final['MOT'], errors='coerce').fillna(0.0)
    df_final['RS'] = pd.to_numeric(df_final['RS'], errors='coerce').fillna(0.0)
    
    return df_final

# 3. 메인 UI
st.set_page_config(layout="wide")
st.markdown('<p style="font-size:24px; font-weight:bold;">📈 모멘텀 분석</p>', unsafe_allow_html=True)

with st.sidebar:
    market_type = st.radio("시장 선택", ["KR", "US"], horizontal=True)
    all_dates = get_available_dates()
    selected_date = st.selectbox("기준일 선택", options=all_dates)
    if st.button("새로고침"): st.rerun()

# 데이터 로드
df_display = get_data(selected_date, all_dates, market_type)

if df_display is None:
    st.warning(f"선택하신 날짜({selected_date})에 대한 분석 데이터가 존재하지 않습니다.")
else:
    # 4. 탭 구성
    tab1, tab2, tab3 = st.tabs(["전체 보기 (TOP 100)", "신규 진입주 (TOP 30)", "매수 전략 시그널"])

    with tab1:
        use_filter = st.checkbox("주도주 필터 적용 (RS > 0.03 & 순위 20위 내)")
        # 100위까지만 제한
        df_to_show = df_display.head(100).copy()
        if use_filter:
            df_to_show = df_to_show[(df_to_show['RS'] > 0.03) & (df_to_show['순위'] <= 20)]
        
        display_cols = ['순위', 'rank_change', '종목명', 'MOT', 'RS', '종가']
        
        event = st.dataframe(
            df_to_show.style.apply(apply_styles, axis=None).format(
                {'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}'}
            ),
            hide_index=True, 
            column_order=display_cols, 
            selection_mode="single-row", 
            on_select="rerun",
            use_container_width=True
        )

    with tab2:
        df_new = df_display[df_display['is_new_top30'] == True].copy()
        if not df_new.empty:
            st.dataframe(
                df_new[['순위', 'rank_change', '종목명', 'MOT', 'RS', '종가']].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}'}), 
                hide_index=True, use_container_width=True
            )
        else:
            st.info("오늘 신규 진입한 종목이 없습니다.")

    with tab3:
        st.subheader("Backtest No2.")
        buy_signals = df_display[df_display['is_buy_signal'] == True]
        if not buy_signals.empty:
            st.dataframe(buy_signals[['종목명', '순위', 'rank_change', '종가']].style.apply(apply_styles, axis=None).format({'rank_change': '{:+.0f}', '종가': '{:,.0f}'}), hide_index=True, use_container_width=True)
        else:
            st.info("조건에 맞는 종목이 없습니다.")

    # 5. 상세 차트
    if 'event' in locals() and event.selection and event.selection["rows"]:
        selected_index = event.selection["rows"][0]
        selected_ticker = df_to_show.iloc[selected_index]['ticker']
        selected_name = df_to_show.iloc[selected_index]['종목명']

        with st.popover(f"📊 {selected_name} 상세 분석", use_container_width=True):
            history_df = pd.DataFrame(supabase.table("daily_analysis").select("price_date, momentum_rank, rs_score").eq("ticker", selected_ticker).eq("market", market_type).order("price_date", desc=True).limit(20).execute().data).sort_values("price_date")
            price_df = pd.DataFrame(supabase.table("stock_prices").select("price_date, close_price").eq("ticker", selected_ticker).order("price_date", desc=True).limit(20).execute().data).sort_values("price_date")
            
            combined_df = pd.merge(history_df, price_df, on="price_date")
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, subplot_titles=("주가 추이", "모멘텀 순위"), row_heights=[0.6, 0.4])
            fig.add_trace(px.line(combined_df, x='price_date', y='close_price').data[0], row=1, col=1)
            fig.add_trace(px.line(combined_df, x='price_date', y='momentum_rank').data[0], row=2, col=1)
            fig.update_layout(height=500, showlegend=False)
            fig.update_yaxes(autorange="reversed", row=2, col=1)
            st.plotly_chart(fig, use_container_width=True)
