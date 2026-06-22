import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1. 함수 정의 (사용 전에 정의되어야 함)
def highlight_new(df):
    # 'is_new_top30'이 True인 행의 모든 컬럼 배경색 변경
    is_new = df['is_new_top30']
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    df_styles.loc[is_new, :] = 'background-color: #ffcccc'
    return df_styles

# 2. 데이터 조회
all_dates = pd.DataFrame(supabase.table("daily_analysis").select("price_date").order("price_date", desc=True).execute().data)
all_dates = all_dates['price_date'].unique()
latest_date, previous_date = all_dates[0], all_dates[1]

df_current = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum").eq("price_date", latest_date).order("momentum_rank").limit(40).execute().data)
df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", previous_date).execute().data)

# 3. 데이터 병합 및 신규 진입 계산
df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
df_merged['is_new'] = df_merged['momentum_rank_prev'].isna()
df_merged['is_new_top30'] = df_merged['is_new'] & (df_merged['momentum_rank'] <= 30)

df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")
df_final['display_name'] = df_final['ticker'] + " - " + df_final['name']

# 4. 화면 표시용 데이터 구성 (전체 40위 유지하되 표시용 필터링)
df_display = df_final.rename(columns={'momentum_rank': '순위', 'name': '종목명', 'weighted_momentum': '점수'})

# 5. 스타일 적용 및 출력
st.markdown('<p class="main-title">📈 모멘텀 분석</p>', unsafe_allow_html=True)
st.markdown(f'<p class="sub-header">기준일: {latest_date}</p>', unsafe_allow_html=True)

# 30위까지 표시
df_table = df_display[df_display['순위'] <= 30].copy()
st.dataframe(
    df_table[['순위', '종목명', '점수', 'is_new_top30']].style.apply(highlight_new, axis=None),
    use_container_width=True, hide_index=True
)

# 6. 종목 선택 및 차트
selected_option = st.selectbox("종목 선택", df_display['display_name'].unique())
selected_ticker = selected_option.split(" - ")[0]

history_df = pd.DataFrame(supabase.table("daily_analysis").select("*").eq("ticker", selected_ticker).order("price_date", desc=True).limit(10).execute().data)
history_df = history_df.sort_values("price_date")

st.subheader(f"{selected_ticker} 과거 모멘텀 변화")
fig = px.line(history_df, x='price_date', y='momentum_rank', markers=True)
fig.update_yaxes(autorange="reversed")
st.plotly_chart(fig)
