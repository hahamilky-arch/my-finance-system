import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1. 스타일 함수
def highlight_new(df):
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    # df에 'is_new_top30' 컬럼이 있는 경우에만 적용
    if 'is_new_top30' in df.columns:
        mask = df['is_new_top30']
        df_styles.loc[mask, :] = 'background-color: #ffcccc'
    return df_styles

# 2. 데이터 조회 함수
def get_data(target_date=None):
    all_dates = pd.DataFrame(supabase.table("daily_analysis").select("price_date").order("price_date", desc=True).execute().data)['price_date'].unique()
    
    target_date = target_date if target_date else all_dates[0]
    previous_date = all_dates[1] if target_date == all_dates[0] else all_dates[all_dates.tolist().index(target_date) + 1]
    
    df_current = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum, rs_score").eq("price_date", target_date).order("momentum_rank").limit(50).execute().data)
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", previous_date).execute().data)
    
    df_current['momentum_rank'] = pd.to_numeric(df_current['momentum_rank'])
    df_prev['momentum_rank'] = pd.to_numeric(df_prev['momentum_rank'])
    
    df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
    df_merged['momentum_rank_prev'] = df_merged['momentum_rank_prev'].fillna(999)
    df_merged['is_new_top30'] = (df_merged['momentum_rank'] <= 30) & (df_merged['momentum_rank_prev'] > 30)

    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")
    
    # 데이터 정리: 숫자 타입 강제 변환
    df_final = df_final.rename(columns={'momentum_rank': '순위', 'name': '종목명', 'weighted_momentum': 'MOT', 'rs_score': 'RS'})
    df_final['MOT'] = pd.to_numeric(df_final['MOT'], errors='coerce').fillna(0.0)
    df_final['RS'] = pd.to_numeric(df_final['RS'], errors='coerce').fillna(0.0)
    
    return df_final, target_date, all_dates

# 3. 메인 UI
st.set_page_config(layout="wide")
st.markdown('<p style="font-size:24px; font-weight:bold;">📈 모멘텀 분석</p>', unsafe_allow_html=True)

all_dates_full = pd.DataFrame(supabase.table("daily_analysis").select("price_date").order("price_date", desc=True).execute().data)['price_date'].unique()
all_dates_list = all_dates_full[:len(all_dates_full)-1] if len(all_dates_full) > 1 else all_dates_full

selected_date = st.selectbox("기준일 선택", all_dates_list)
df_display, _, _ = get_data(selected_date)

display_cols = ['순위', '종목명', 'MOT', 'RS']

tab1, tab2 = st.tabs(["전체 보기 (TOP 50)", "신규 진입주 (TOP 30)"])

with tab1:
    st.dataframe(
        df_display.style.apply(highlight_new, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}'}),
        hide_index=True, column_order=display_cols, selection_mode="single-row", on_select="rerun"
    )

with tab2:
    df_new = df_display[df_display['is_new_top30'] == True].copy()
    if not df_new.empty:
        # 동일하게 스타일 및 포맷 적용
        st.dataframe(
            df_new.style.format({'MOT': '{:.2f}', 'RS': '{:.2f}'}), 
            hide_index=True, column_order=display_cols
        )
    else:
        st.info("오늘 신규 진입한 종목이 없습니다.")

with st.sidebar:
    st.caption("App Version: 1.1.1")
