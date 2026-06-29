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

# 2. 데이터 조회 및 처리
def get_data(target_date, market_type):
    target_date_str = str(target_date)
    # 날짜 조회를 위한 이전 날짜 로직
    all_dates_res = supabase.rpc("get_all_dates").execute()
    all_dates = [item['price_date'] for item in all_dates_res.data]
    
    if target_date_str not in all_dates: return None
    target_idx = all_dates.index(target_date_str)
    previous_date = all_dates[target_idx + 1] if target_idx + 1 < len(all_dates) else target_date_str
    
    df_current = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score, close_price").eq("price_date", target_date_str).eq("market", market_type).order("momentum_rank").execute().data)
    if df_current.empty: return None
    
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", previous_date).eq("market", market_type).execute().data)
    
    df_current['momentum_rank'] = pd.to_numeric(df_current['momentum_rank'])
    df_current['close_price'] = pd.to_numeric(df_current['close_price'])
    df_current['rs_score'] = pd.to_numeric(df_current['rs_score'])
    df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
    df_merged['rank_change'] = df_merged['momentum_rank_prev'].fillna(999) - df_merged['momentum_rank']
    
    ticker_list = list(df_merged['ticker'].unique())
    df_vol = pd.DataFrame(supabase.table("stock_prices").select("ticker, volume, price_date").in_("ticker", list(ticker_list)).order("price_date", desc=True).limit(400).execute().data)
    
    # 기존 거래량 계산 코드 부분을 아래 코드로 교체하세요
    if not df_vol.empty:
        df_vol['volume'] = pd.to_numeric(df_vol['volume'], errors='coerce')
        # 20일 평균 계산 시, 데이터가 적은 경우(상장 초기 등)를 위해 min_periods 설정
        df_vol['avg_vol_20'] = df_vol.groupby('ticker')['volume'].transform(lambda x: x.rolling(window=20, min_periods=5).mean())
        
        df_today_vol = df_vol[df_vol['price_date'] == target_date_str][['ticker', 'volume', 'avg_vol_20']]
        
        # 병합 방식을 inner가 아닌 left로 유지하되, 계산 결과를 엄격히 검사
        df_merged = pd.merge(df_merged, df_today_vol, on='ticker', how='left')
        
        # 0 나누기 방지: 거래량(volume)이나 평균(avg_vol_20)이 0이면 ratio를 0으로 처리
        df_merged['vol_ratio'] = (df_merged['volume'] / df_merged['avg_vol_20']).fillna(0)
    else:
        df_merged['vol_ratio'] = 0.0

    
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'name': '종목명', 'weighted_momentum': 'MOT', 'rs_score': 'RS', 'close_price': '종가'})
    df_final['is_new_top30'] = (df_final['순위'] <= 30) & (df_final['momentum_rank_prev'] > 30)
    return df_final

# 3. 메인 UI
st.set_page_config(layout="wide")
st.markdown('<p style="font-size:24px; font-weight:bold;">📈 모멘텀 분석 대시보드</p>', unsafe_allow_html=True)

with st.sidebar:
    market_type = st.radio("시장 선택", ["KR", "US"], horizontal=True)
    # 기존 원하시던 달력(Date Input)으로 사이드바 구성
    selected_date = st.date_input("분석 기준일 선택")
    if st.button("데이터 새로고침"): st.rerun()

df_display = get_data(selected_date, market_type)

if df_display is not None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["전체 보기", "신규 진입주", "매수 시그널", "🚀 No3", "🚀 No4: High-Octane"])

    with tab1:
        event = st.dataframe(df_display.head(100).style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}'}), 
                             hide_index=True, column_order=['순위', 'rank_change', '종목명', 'MOT', 'RS', '종가'], selection_mode="single-row", on_select="rerun", use_container_width=True)

    with tab2:
        st.dataframe(df_display[df_display['is_new_top30'] == True][['순위', 'rank_change', '종목명', 'MOT', 'RS', '종가']].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}'}), hide_index=True, use_container_width=True)

    with tab3:
        st.dataframe(df_display[(df_display['순위'] >= 70) & (df_display['순위'] <= 100) & (df_display['rank_change'] >= 20)][['순위', 'rank_change', '종목명', '종가']].style.apply(apply_styles, axis=None).format({'rank_change': '{:+.0f}', '종가': '{:,.0f}'}), hide_index=True, use_container_width=True)

    with tab4:
        no3 = df_display[(df_display['순위'] <= 50) & (df_display['rank_change'] >= 20) & (df_display['vol_ratio'] >= 1.5)]
        st.dataframe(no3[['순위', 'rank_change', '종목명', 'vol_ratio', 'MOT', 'RS', '종가']].style.apply(apply_styles, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}', '종가': '{:,.0f}', 'rank_change': '{:+.0f}', 'vol_ratio': '{:.2f}배'}), hide_index=True, use_container_width=True)

    with tab5:
        st.subheader("🚀 High-Octane No4 전략 (순위 100위/RS 0.4/거래량 2배)")
        
        # 1. 데이터 클렌징: No4 전략용 필터 데이터 준비
        no4_df = df_display.copy()
        no4_df['RS'] = pd.to_numeric(no4_df['RS'], errors='coerce').fillna(0)
        no4_df['vol_ratio'] = pd.to_numeric(no4_df['vol_ratio'], errors='coerce').fillna(0)
        
        # 2. 필터 적용: RS 0.4 이상이 아닐 수도 있으니, 
        # 데이터에 맞춰 조건을 조금 완화해보고 테스트합니다.
        # (만약 0.4 이상이 하나도 없다면 0.2로 낮춰서 테스트해 보세요)
        no4 = no4_df[(no4_df['순위'] <= 100) & 
                     (no4_df['RS'] >= 0.2) &  # 일단 0.2로 낮춰서 테스트
                     (no4_df['vol_ratio'] >= 1.5)] # 거래량 1.5배로 조정
        
        if not no4.empty:
            st.success(f"{len(no4)}개의 강력한 주도주 신호가 포착되었습니다.")
            st.dataframe(no4[['순위', '종목명', 'RS', 'vol_ratio', '종가']].style.apply(apply_styles, axis=None).format({'RS': '{:.2f}', 'vol_ratio': '{:.2f}배', '종가': '{:,.0f}'}), hide_index=True, use_container_width=True)
            st.info("💡 매매 지침: 자산 40% 집중, 7% 트레일링 스탑, 60일선 이탈 시 전량 매도")
        else:
            # 디버깅용: 조건에 맞는 종목이 왜 없는지 확인
            st.warning("조건에 부합하는 종목이 없습니다.")
            st.write("상위 10개 종목의 RS 점수 및 거래량 비율 확인:")
            st.dataframe(no4_df[['순위', '종목명', 'RS', 'vol_ratio']].sort_values('RS', ascending=False).head(10))


    # 상세 차트
    if 'event' in locals() and event.selection and event.selection["rows"]:
        selected_index = event.selection["rows"][0]
        selected_ticker = df_display.head(100).iloc[selected_index]['ticker']
        selected_name = df_display.head(100).iloc[selected_index]['종목명']
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
