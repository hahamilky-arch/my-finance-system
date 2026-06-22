import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px

# Supabase 연결
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# 1. 함수 정의 (사용 전에 정의되어야 함)
def highlight_new(df):
    # 배경색을 적용할 스타일 템플릿 생성
    df_styles = pd.DataFrame('', index=df.index, columns=df.columns)
    # 신규 진입인 경우에만 색상 부여
    mask = df['is_new_top30']
    df_styles.loc[mask, :] = 'background-color: #ffcccc'
    return df_styles

# 데이터 가져오는 함수 (날짜 선택을 위해 분리)
def get_data(target_date=None):
    # 전체 날짜 리스트 가져오기
    all_dates = pd.DataFrame(supabase.table("daily_analysis").select("price_date").order("price_date", desc=True).execute().data)['price_date'].unique()
    
    # 날짜가 선택되지 않았으면 가장 최근 날짜 사용
    target_date = target_date if target_date else all_dates[0]
    previous_date = all_dates[1] if target_date == all_dates[0] else all_dates[all_dates.tolist().index(target_date) + 1]
    
    df_current = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank, weighted_momentum").eq("price_date", target_date).order("momentum_rank").limit(50).execute().data)
    df_prev = pd.DataFrame(supabase.table("daily_analysis").select("ticker, momentum_rank").eq("price_date", previous_date).execute().data)
    # 데이터 타입 명시적 변환 (순위가 숫자인지 확인)
    df_current['momentum_rank'] = pd.to_numeric(df_current['momentum_rank'])
    df_prev['momentum_rank'] = pd.to_numeric(df_prev['momentum_rank'])
    
    # 데이터 병합 및 신규 계산
    df_merged = pd.merge(df_current, df_prev, on="ticker", how="left", suffixes=('', '_prev'))
    #df_merged['is_new'] = df_merged['momentum_rank_prev'].isna()
    #df_merged['is_new_top30'] = df_merged['is_new'] & (df_merged['momentum_rank'] <= 30)
    
    # NaN(이전 데이터 없음)은 999로 변환
    df_merged['momentum_rank_prev'] = df_merged['momentum_rank_prev'].fillna(999)
             
    # 신규 진입 조건: 당일 30위 이내이면서, 이전 순위가 30위 미만(31위 이상 또는 데이터 없음)
    df_merged['is_new_top30'] = (df_merged['momentum_rank'] <= 30) & (df_merged['momentum_rank_prev'] > 30)



    df_stocks = pd.DataFrame(supabase.table("stocks").select("ticker, name").execute().data)
    df_final = pd.merge(df_merged, df_stocks, on="ticker", how="left")
    df_final['display_name'] = df_final['ticker'] + " - " + df_final['name']
    
    return df_final.rename(columns={'momentum_rank': '순위', 'name': '종목명', 'weighted_momentum': 'MOT','rs_score':'RS'}), target_date, all_dates


# 스타일 적용 및 출력
st.markdown('<p class="main-title">📈 모멘텀 분석</p>', unsafe_allow_html=True)
# [추가할 코드] CSS를 사용하여 상단 여백(block-container) 제거
st.markdown("""
    <style>
    .stApp {
        margin-top: -30px;
    }
    .block-container {
        padding-top: 1rem;
        padding-bottom: 0rem;
    }
    </style>
""", unsafe_allow_html=True)

# 날짜 선택기 추가
# 최근 5일 데이터만 가져오도록 슬라이싱
all_dates_full = pd.DataFrame(supabase.table("daily_analysis").select("price_date").order("price_date", desc=True).execute().data)['price_date'].unique()
# 데이터가 2개 이상일 때만 가능하도록 예외 처리
if len(all_dates_full) > 1:
    # 가장 최신 날짜부터 5개를 가져오되, 마지막 날짜(인덱스 4)는 제외
    all_dates_list = all_dates_full[:len(all_dates_full)-1] 
else:
    all_dates_list = all_dates_full

# 선택된 날짜에 따른 데이터 로드
selected_date = st.selectbox("기준일 선택", all_dates_list)
df_display, latest_date, _ = get_data(selected_date)

# 35위까지 표시
df_table = df_display[df_display['순위'] <= 35].copy()

# 표 출력 부분 (불필요한 컬럼 숨기기 및 스타일 적용)
# 출력할 컬럼 정의
display_cols = ['순위', '종목명', 'MOT', 'RS']

# 스타일 적용 및 출력 (axis=None으로 전체 데이터 참조)
event = st.dataframe(
    df_table.style.apply(highlight_new, axis=None).format({'MOT': '{:.2f}', 'RS': '{:.2f}'}),
    use_container_width=True, 
    width="stretch", # 또는 명시적으로 'stretch' 설정 가능
    hide_index=True,
    column_order=display_cols,
    selection_mode="single-row", # 행 클릭 가능
    on_select="rerun" ,           # 클릭 시 앱 재실행
    column_config={
        "순위": st.column_config.NumberColumn(
            "순위",
            width="small",  # "small", "medium", "large" 중 선택 가능
        ),
        "MOT": st.column_config.NumberColumn(
            "MOT",
            width="medium",
        ),
        "RS" : st.column_config.NumberColumn(
            "RS",
            width="medium",
        ),
        "종목명": st.column_config.TextColumn(            
            "종목명",
            width="medium",  # 긴 텍스트를 위해 넓게 설정
        )
    }
)

# 종목 선택 및 차트
#st.subheader("종목별 상세 분석")

# 선택된 행이 있다면 해당 종목의 코드를 가져옴
if event.selection["rows"]:
    selected_index = event.selection["rows"][0]
    selected_ticker = df_display.iloc[selected_index]['display_name'].split(" - ")[0]
    selected_name = df_display.iloc[selected_index]['display_name'].split(" - ")[1]

    #st.divider()

    # st.popover는 1.34 버전 이상에서 사용 가능
    with st.popover(f"📊 {selected_name} 모멘텀 순위 변동"):
        st.subheader(f"📊 {selected_name} ({selected_ticker}) 상세 차트")
                            
        # 하단 그래프 노출
        history_df = pd.DataFrame(supabase.table("daily_analysis").select("*").eq("ticker", selected_ticker).order("price_date", desc=True).limit(10).execute().data)
        history_df = history_df.sort_values("price_date")

        fig = px.line(
            history_df, 
            x='price_date', 
            y='momentum_rank', 
            markers=True,
            # 축 표시명 변경
            labels={'price_date': '날짜', 'momentum_rank': '순위'}
        )                                       
        # [수정된 부분] Y축 범위를 0부터 35로 고정 및 역순 정렬
        #fig.update_yaxes(autorange="reversed")
        # Y축 고정 (0~35, 순위이므로 역순) 및 날짜 형식(YMD) 지정
        fig.update_layout(
            xaxis=dict(
                tickformat="%m-%d"  # 날짜를 YMD 형식으로 표시
            ),
            yaxis=dict(
                range=[35, 0]          # Y축 범위 고정
            )
        )

        # 줌인 및 모드바 제거를 위한 config 설정
        config = {
            #'displayModeBar': False,  # 상단 모드바 전체 숨기기
            'scrollZoom': False,      # 스크롤 줌 비활성화
            'doubleClick': False      # 더블클릭 줌 비활성화
        }
    
        st.plotly_chart(fig, use_container_width=True)
#else:
    #st.info("표에서 종목을 선택하면 하단에 그래프가 나타납니다.")

#selected_option = st.selectbox("종목 선택", df_display['display_name'].unique())
#selected_ticker = selected_option.split(" - ")[0]

#history_df = pd.DataFrame(supabase.table("daily_analysis").select("*").eq("ticker", selected_ticker).order("price_date", desc=True).limit(10).execute().data)
#history_df = history_df.sort_values("price_date")

#st.subheader(f"{selected_ticker} 과거 모멘텀 변화")
#fig = px.line(history_df, x='price_date', y='momentum_rank', markers=True)
#fig.update_yaxes(autorange="reversed")
#st.plotly_chart(fig)

with st.sidebar:
    st.write("---")
    st.caption("App Version: 1.0.2")
    st.caption("Updated: 2026-06-23")