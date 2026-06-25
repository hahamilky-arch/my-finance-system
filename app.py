import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from plotly.subplots import make_subplots

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1. 스타일 함수
def highlight_new(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    if 'is_new_top30' in df.columns:
        mask = df['is_new_top30']
        df_styles.loc[mask, :] = 'background-color: #ffcccc'
    return df_styles

# 2. 날짜 리스트 및 데이터 조회 함수 (캐시 없이 실시간 조회)
def get_available_dates():
    # Supabase에서 데이터 조회
    response = supabase.table("daily_analysis").select("price_date").range(0, 1000).order("price_date", desc=True).execute()
    if not response.data:
        return []
    # set으로 중복 제거 후 역순 정렬
    unique_dates = sorted(list({item['price_date'] for item in response.data}), reverse=True)
    return unique_dates

def get_data(target_date, all_dates):
    if target_date not in all_dates:
        return pd.DataFrame()
        
    target_idx = all_dates.index(target_date)
    previous_date = all_dates[target_idx + 1] if target_idx + 1 < len(all_dates) else target_date
    
    # 데이터 조회
    df_current = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score").eq("price_date", target_date).order("momentum_rank").limit(50).execute().data)
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", previous_date).execute().data)
    
    # 데이터 전처리
    df_current['momentum_rank'] = pd.to_numeric(df_current['momentum_rank'])
    df_prev['momentum_rank'] = pd.to_numeric(df_prev['momentum_rank'])
    
    df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
    df_merged['momentum_rank_prev'] = df_merged['momentum_rank_prev'].fillna(999)
    df_merged['is_new_top30'] = (df_merged['momentum_rank'] <= 30) & (df_merged['momentum_rank_prev'] > 30)

    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")
    
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'name': '종목명', 'weighted_momentum': 'MOT', 'rs_score': 'RS'})
    df_final['MOT'] = pd.to_numeric(df_final['MOT'], errors='coerce').fillna(0.0)
    df_final['RS'] = pd.to_numeric(df_final['RS'], errors='coerce').fillna(0.0)
    
    return df_final

# 3. 메인 UI
st.set_page_config(layout="wide")
st.markdown('<p style="font-size:24px; font-weight:bold;">📈 모멘텀 분석</p>', unsafe_allow_html=True)

# 실시간 날짜 리스트 로드
all_dates = get_available_dates()
if not all_dates:
    st.error("데이터가 없습니다.")
    st.stop()

# 디버깅: 사이드바에 날짜 정보 표시
st.sidebar.write(f"조회된 날짜 수: {len(all_dates)}")
selected_date = st.selectbox("기준일 선택", options=all_dates)

# 데이터 로드
df_display = get_data(selected_date, all_dates)

display_cols = ['순위', '종목명', 'MOT', 'RS']
tab1, tab2 = st.tabs(["전체 보기 (TOP 50)", "신규 진입주 (TOP 30)"])

with tab1:
    use_filter = st.checkbox("주도주 필터 적용 (RS > 0.03 & 순위 20위 내)")
    df_to_show = df_display.copy()
    if use_filter:
        df_to_show = df_to_show[(df_to_show['RS'] > 0.03) & (df_to_show['순위'] <= 20)]
    
    event = st.dataframe(
        df_to_show.style.apply(highlight_new, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}'}),
        hide_index=True, column_order=display_cols, selection_mode="single-row", on_select="rerun"
    )

with tab2:
    df_new = df_display[df_display['is_new_top30'] == True].copy()
    if not df_new.empty:
        st.dataframe(
            df_new.style.format({'MOT': '{:.2f}', 'RS': '{:.2f}'}), 
            hide_index=True, column_order=display_cols
        )
    else:
        st.info("오늘 신규 진입한 종목이 없습니다.")

# 4. 상세 차트
if event.selection and event.selection["rows"]:
    selected_index = event.selection["rows"][0]
    selected_ticker = df_to_show.iloc[selected_index]['ticker']
    selected_name = df_to_show.iloc[selected_index]['종목명']

    with st.popover(f"📊 {selected_name} 상세 분석", use_container_width=True):
        history_df = pd.DataFrame(supabase.table("daily_analysis").select("price_date, momentum_rank, rs_score").eq("ticker", selected_ticker).order("price_date", desc=True).limit(20).execute().data).sort_values("price_date")
        price_df = pd.DataFrame(supabase.table("stock_prices").select("price_date, close_price").eq("ticker", selected_ticker).order("price_date", desc=True).limit(20).execute().data).sort_values("price_date")
        
        combined_df = pd.merge(history_df, price_df, on="price_date")

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, 
                           subplot_titles=("주가 추이", "모멘텀 순위"), row_heights=[0.6, 0.4])

        fig.add_trace(px.line(combined_df, x='price_date', y='close_price').data[0], row=1, col=1)
        fig.add_trace(px.line(combined_df, x='price_date', y='momentum_rank').data[0], row=2, col=1)

        fig.update_layout(height=500, showlegend=False)
        fig.update_yaxes(autorange="reversed", row=2, col=1)
        
        st.plotly_chart(fig, use_container_width=True)

with st.sidebar:
    st.caption("App Version: 1.1.4")
