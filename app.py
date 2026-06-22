import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px

# Supabase 연결 (secrets 관리)
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


# st 페이지 설정
st.set_page_config(page_title="모멘텀 대시보드", layout="centered")

# CSS를 사용하여 Title 크기 조정 및 디자인 깔끔하게 적용
st.markdown("""
    <style>
        .main-title { font-size: 24px !important; font-weight: bold; margin-bottom: 10px; color: #2E4053; }
        .sub-header { font-size: 14px !important; color: #7F8C8D; margin-bottom: 20px; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<p class="main-title">📈 모멘텀 분석</p>', unsafe_allow_html=True)
st.markdown(f'<p class="sub-header">기준일: {latest_date}</p>', unsafe_allow_html=True).set_page_config(page_title="모멘텀 대시보드", layout="wide")
#st.title("📈 한국 주식 모멘텀 순위 분석")

# 1. 가장 최근 날짜 가져오기
latest_date = supabase.table("daily_analysis").select("price_date").order("price_date", desc=True).limit(1).execute().data[0]['price_date']
st.subheader(f"기준 일자: {latest_date}")

# 2. 최근일자 순위 데이터 조회
df_analysis = pd.DataFrame(supabase.table("daily_analysis").select("*").eq("price_date", latest_date).order("momentum_rank").execute().data)
# stocks 데이터(티커와 이름 매칭용) 조회
df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
# 두 데이터프레임을 'ticker'를 기준으로 합치기
df_merged = pd.merge(df_analysis, df_stocks, on="ticker", how="left")

# 종목별 과거 순위 변화 (상세 보기)
# 1. 티커와 종목명을 합친 리스트 생성
# "005930 - 삼성전자" 형태로 표시
df_merged['display_name'] = df_merged['ticker'] + " - " + df_merged['name']

# 컬럼명 한글로 변경
df_merged = df_merged.rename(columns={
    'momentum_rank': '순위',
    'ticker': '코드',
    'name': '종목명',
    'weighted_momentum': '점수',
    'display_name' : 'display_name'
})

# 모바일용: 필요한 컬럼만 보여주기 (순위, 종목명, 점수만)
st.dataframe(
    df_merged[['순위', '종목명', '점수']], 
    use_container_width=True, # 화면 너비에 맞춤
    hide_index=True           # 인덱스 숨겨 공간 확보
)

# 2. selectbox 구성
# 사용자는 display_name을 보지만, 반환값(selected_option)은 "005930 - 삼성전자" 전체가 됩니다.
selected_option = st.selectbox("종목 선택", df_merged['display_name'].unique())

# 3. 선택된 문자열에서 다시 ticker만 추출
selected_ticker = selected_option.split(" - ")[0]
##selected_ticker = st.selectbox("종목 선택", df_merged['ticker'].unique())
history_df = pd.DataFrame(supabase.table("daily_analysis").select("*").eq("ticker", selected_ticker).execute().data)

st.subheader(f"{selected_ticker} 과거 모멘텀 변화")
fig = px.line(history_df, x='price_date', y='momentum_rank', markers=True)
fig.update_yaxes(autorange="reversed") # 순위는 낮을수록 좋으므로 반전
st.plotly_chart(fig)
