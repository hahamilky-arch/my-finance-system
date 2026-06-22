import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px

# Supabase 연결 (secrets 관리)
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1. 고유한 날짜 목록을 최신순으로 가져와 이전 거래일(previous_date) 식별
all_dates = pd.DataFrame(supabase.table("daily_analysis").select("price_date").order("price_date", desc=True).execute().data)
all_dates = all_dates['price_date'].unique()
latest_date = all_dates[0]
previous_date = all_dates[1] # 휴장을 제외한 바로 이전 날짜
# latest_date = supabase.table("daily_analysis").select("price_date").order("price_date", desc=True).limit(1).execute().data[0]['price_date']

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
st.markdown(f'<p class="sub-header">기준일: {latest_date}</p>', unsafe_allow_html=True)
#st.set_page_config(page_title="모멘텀 대시보드", layout="wide")
#st.title("📈 한국 주식 모멘텀 순위 분석")
#st.subheader(f"기준 일자: {latest_date}")

# 2. 오늘(최신) 상위 40개 데이터 조회
df_current = pd.DataFrame(supabase.table("daily_analysis")
                          .select("ticker, momentum_rank, weighted_momentum")
                          .eq("price_date", latest_date)
                          .order("momentum_rank")
                          .limit(40).execute().data)

# 이전 거래일 데이터 조회 (상위 40위권 내 신규 진입 여부를 확인하기 위해 전체 혹은 넉넉하게 조회)
df_prev = pd.DataFrame(supabase.table("daily_analysis")
                       .select("ticker, momentum_rank")
                       .eq("price_date", previous_date)
                       .execute().data)

# 4. 데이터 병합 및 신규 진입 여부 계산
df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
df_merged['is_new'] = df_merged['momentum_rank_prev'].isna() # 이전 날짜에 없으면 신규
df_merged['is_new_top30'] = df_merged['is_new'] & (df_merged['momentum_rank'] <= 30)

# df_analysis = pd.DataFrame(supabase.table("daily_analysis").select("*").eq("price_date", latest_date).limit(50).order("momentum_rank").execute().data)


# stocks 데이터(티커와 이름 매칭용) 조회
df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)

# 종목명 매핑
df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")

# 병합된 데이터에서 필요한 컬럼만 추출하여 display_name 생성
df_final['display_name'] = df_final['ticker'] + " - " + df_final['name']

# 표시용 컬럼 정리
df_display = df_final[['momentum_rank', 'name', 'weighted_momentum', 'is_new_top30', 'display_name', 'ticker']]
df_display = df_display.rename(columns={
    'momentum_rank': '순위',
    'name': '종목명',
    'weighted_momentum': '점수'
})

# 30위까지만 필터링 (표 출력용)
df_table = df_display[df_display['순위'] <= 30].copy()

# 스타일 적용 및 출력
st.dataframe(
    df_table[['순위', '종목명', '점수']].style.apply(highlight_new, axis=1),
    use_container_width=True,
    hide_index=True
)

# 30위까지만 최종 노출
df_display = df_display[df_display['순위'] <= 30]

def highlight_new(row):
    return ['background-color: #ffcccc' if row['is_new_top30'] else '' for _ in row]

# 모바일용: 필요한 컬럼만 보여주기 (순위, 종목명, 점수만)
st.dataframe(
    df_display[['순위', '종목명', '점수']].style.apply(highlight_new, axis=1),
    use_container_width=True, # 화면 너비에 맞춤
    hide_index=True           # 인덱스 숨겨 공간 확보
)

# 2. selectbox 구성
# 사용자는 display_name을 보지만, 반환값(selected_option)은 "005930 - 삼성전자" 전체가 됩니다.
selected_option = st.selectbox("종목 선택", df_display['display_name'].unique())

# 3. 선택된 문자열에서 다시 ticker만 추출
selected_ticker = selected_option.split(" - ")[0]
##selected_ticker = st.selectbox("종목 선택", df_merged['ticker'].unique())
history_df = pd.DataFrame(supabase.table("daily_analysis").select("*").eq("ticker", selected_ticker).limit(10).execute().data)

st.subheader(f"{selected_ticker} 과거 모멘텀 변화")
fig = px.line(history_df, x='price_date', y='momentum_rank', markers=True)
fig.update_yaxes(autorange="reversed") # 순위는 낮을수록 좋으므로 반전
st.plotly_chart(fig)
