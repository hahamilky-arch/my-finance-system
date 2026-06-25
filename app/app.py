import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1. 스타일 함수
def highlight_new(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    mask = df['is_new_top30']
    df_styles.loc[mask, :] = 'background-color: #ffcccc'
    return df_styles

# 2. 데이터 조회 함수
def get_data(target_date=None):
    all_dates = pd.DataFrame(supabase.table("daily_analysis").select("price_date").order("price_date", desc=True).execute().data)['price_date'].unique()
    
    target_date = target_date if target_date else all_dates[0]
    previous_date = all_dates[1] if target_date == all_dates[0] else all_dates[all_dates.tolist().index(target_date) + 1]
    
    # 데이터 로드
    df_current = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score").eq("price_date", target_date).order("momentum_rank").limit(50).execute().data)
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", previous_date).execute().data)
    
    df_current['momentum_rank'] = pd.to_numeric(df_current['momentum_rank'])
    df_prev['momentum_rank'] = pd.to_numeric(df_prev['momentum_rank'])
    
    # 병합
    df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
    df_merged['momentum_rank_prev'] = df_merged['momentum_rank_prev'].fillna(999)
    df_merged['is_new_top30'] = (df_merged['momentum_rank'] <= 30) & (df_merged['momentum_rank_prev'] > 30)

    # 종목명 병합
    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")
    
    return df_final.rename(columns={'momentum_rank': '순위', 'name': '종목명', 'weighted_momentum': 'MOT', 'rs_score': 'RS'}), target_date, all_dates

# 3. 메인 UI
st.set_page_config(layout="wide")
st.markdown('<p style="font-size:24px; font-weight:bold;">📈 모멘텀 분석</p>', unsafe_allow_html=True)

# 날짜 선택
all_dates_full = pd.DataFrame(supabase.table("daily_analysis").select("price_date").order("price_date", desc=True).execute().data)['price_date'].unique()
all_dates_list = all_dates_full[:len(all_dates_full)-1] if len(all_dates_full) > 1 else all_dates_full

selected_date = st.selectbox("기준일 선택", all_dates_list)
df_display, _, _ = get_data(selected_date)

# 탭 구성
tab1, tab2 = st.tabs(["전체 보기 (TOP 50)", "신규 진입주 (TOP 30)"])

with tab1:
    df_table = df_display.copy()
    display_cols = ['순위', '종목명', 'MOT', 'RS']
    
    event = st.dataframe(
        df_table.style.apply(highlight_new, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}'}),
        hide_index=True, column_order=display_cols, selection_mode="single-row", on_select="rerun"
    )

with tab2:
    df_new = df_display[df_display['is_new_top30'] == True].copy()
    if not df_new.empty:
        st.dataframe(df_new.style.format({'MOT': '{:.2f}', 'RS': '{:.2f}'}), hide_index=True, column_order=display_cols)
    else:
        st.info("오늘 신규 진입한 종목이 없습니다.")

# 4. 종목 선택 상세 차트
if event.selection["rows"]:
    selected_index = event.selection["rows"][0]
    selected_ticker = df_display.iloc[selected_index]['ticker']
    selected_name = df_display.iloc[selected_index]['종목명']

    with st.popover(f"📊 {selected_name} 상세 분석", use_container_width=True):
        history_df = pd.DataFrame(supabase.table("daily_analysis").select("*").eq("ticker", selected_ticker).order("price_date", desc=True).limit(10).execute().data).sort_values("price_date")
        fig = px.line(history_df, x='price_date', y='momentum_rank', markers=True, labels={'price_date': '날짜', 'momentum_rank': '순위'})
        fig.update_layout(yaxis=dict(range=[35, 0]))
        st.plotly_chart(fig, use_container_width=True)

with st.sidebar:
    st.caption("App Version: 1.1.0")
