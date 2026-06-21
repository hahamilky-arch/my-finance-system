import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px

# Supabase 연결 (secrets 관리)
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

st.set_page_config(page_title="모멘텀 대시보드", layout="wide")
st.title("📈 한국 주식 모멘텀 순위 분석")

# 1. 가장 최근 날짜 가져오기
latest_date = supabase.table("daily_analysis").select("price_date").order("price_date", desc=True).limit(1).execute().data[0]['price_date']
st.subheader(f"기준 일자: {latest_date}")

# 2. 최근일자 순위 데이터 조회
df = pd.DataFrame(supabase.table("daily_analysis").select("*").eq("price_date", latest_date).order("momentum_rank").execute().data)

st.dataframe(df[['momentum_rank', 'ticker', 'weighted_momentum']].head(40))

# 3. 종목별 과거 순위 변화 (상세 보기)
selected_ticker = st.selectbox("종목 선택", df['ticker'].unique())
history_df = pd.DataFrame(supabase.table("daily_analysis").select("*").eq("ticker", selected_ticker).execute().data)

st.subheader(f"{selected_ticker} 과거 모멘텀 변화")
fig = px.line(history_df, x='price_date', y='momentum_rank', markers=True)
fig.update_yaxes(autorange="reversed") # 순위는 낮을수록 좋으므로 반전
st.plotly_chart(fig)
